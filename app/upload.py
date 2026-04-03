"""
app/upload.py

Admin-only blueprint for carrier BOB file uploads.
Handles file validation, parsing dispatch, and database upsert.
Only users with is_admin == True can access these routes.
"""

import os
import uuid
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from datetime import datetime
from app.models import db, Policy, ImportBatch, AuditLog, Customer, CustomerAorHistory
from app.parsers import parse_carrier_file, SUPPORTED_CARRIERS

upload_bp = Blueprint("upload", __name__)


def _upsert_customer_from_policy(rec: dict, agent_id: int, batch_id: int, agency_id: int) -> None:
    """
    Create or update a Customer record from a parsed policy row.

    Called after every policy upsert. Uses MBI as the primary key.
    Humana fallback: match on humana_id, then name+DOB+zip (all three required).

    agency_id must be passed explicitly — this function runs in a batch loop
    without guaranteed Flask request context per record.

    Guards:
    - If customer.manually_edited is True, contact fields are not overwritten.
    - BCBS term_date is a renewal date — never copied to AOR end_date.
    """
    carrier = rec.get("carrier", "")
    mbi = rec.get("mbi") or None
    humana_id = rec.get("member_id") if carrier == "Humana" else None

    now = datetime.utcnow()
    customer = None

    # --- Locate existing customer (always scoped to agency) ---
    if mbi:
        customer = Customer.query.filter_by(mbi=mbi, agency_id=agency_id).first()
    elif humana_id:
        customer = Customer.query.filter_by(humana_id=humana_id, agency_id=agency_id).first()
        if not customer:
            # Final fallback: name + DOB + zip (all three must match)
            fn = (rec.get("first_name") or "").strip().lower()
            ln = (rec.get("last_name") or "").strip().lower()
            dob = rec.get("dob")
            zc = (rec.get("zip_code") or "").strip()
            if fn and ln and dob and zc:
                customer = (
                    Customer.query
                    .filter(
                        Customer.agency_id == agency_id,
                        db.func.lower(Customer.first_name) == fn,
                        db.func.lower(Customer.last_name) == ln,
                        Customer.dob == dob,
                        Customer.zip_code == zc,
                    )
                    .first()
                )

    full_name = rec.get("full_name") or f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip()
    address_parts = [rec.get("address1"), rec.get("city"), rec.get("state"), rec.get("zip_code")]
    carrier_address = ", ".join(p for p in address_parts if p)

    if customer:
        # Always update carrier-sourced fields
        customer.last_carrier_sync = now
        customer.carrier_address = carrier_address
        if mbi and not customer.mbi:
            customer.mbi = mbi
        if humana_id and not customer.humana_id:
            customer.humana_id = humana_id

        # Only overwrite contact/address fields if agent hasn't manually edited them
        if not customer.manually_edited:
            customer.first_name = rec.get("first_name") or customer.first_name
            customer.last_name = rec.get("last_name") or customer.last_name
            customer.full_name = full_name or customer.full_name
            customer.dob = rec.get("dob") or customer.dob
            customer.phone_primary = rec.get("phone") or customer.phone_primary
            customer.address1 = rec.get("address1") or customer.address1
            customer.city = rec.get("city") or customer.city
            customer.state = rec.get("state") or customer.state
            customer.zip_code = rec.get("zip_code") or customer.zip_code
            customer.county = rec.get("county") or customer.county

        # Update agent ownership to most recent import
        customer.primary_agent_id = agent_id
    else:
        # New customer — create from policy data
        customer = Customer(
            agency_id=agency_id,
            mbi=mbi,
            humana_id=humana_id,
            first_name=rec.get("first_name") or "",
            last_name=rec.get("last_name") or "",
            full_name=full_name,
            dob=rec.get("dob"),
            phone_primary=rec.get("phone"),
            address1=rec.get("address1"),
            city=rec.get("city"),
            state=rec.get("state"),
            zip_code=rec.get("zip_code"),
            county=rec.get("county"),
            carrier_address=carrier_address,
            primary_agent_id=agent_id,
            last_carrier_sync=now,
        )
        db.session.add(customer)
        db.session.flush()  # get customer.id before AOR insert

    # --- AOR history upsert ---
    # BCBS term_date is a renewal date, not a real end_date — skip it
    effective_date = rec.get("effective_date")
    if effective_date and customer.id:
        existing_aor = CustomerAorHistory.query.filter_by(
            customer_id=customer.id,
            carrier=carrier,
            effective_date=effective_date,
        ).first()
        if not existing_aor:
            aor = CustomerAorHistory(
                agency_id=agency_id,
                customer_id=customer.id,
                agent_id=agent_id,
                carrier=carrier,
                plan_name=rec.get("plan_name"),
                effective_date=effective_date,
                end_date=None,  # BCBS term_date intentionally excluded
                source="carrier_import",
                import_batch_id=batch_id,
            )
            db.session.add(aor)

# File extensions allowed per carrier
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Max upload size — enforce in nginx too, but double-check here
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


def _admin_required(f):
    """Decorator: redirect non-admin users to dashboard with a flash message."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)

    return decorated


@upload_bp.route("/upload", methods=["GET"])
@login_required
@_admin_required
def upload_page():
    """Render the carrier file upload page with recent import history."""
    recent_batches = (
        ImportBatch.query
        .order_by(ImportBatch.upload_date.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "upload.html",
        carriers=SUPPORTED_CARRIERS,
        recent_batches=recent_batches,
    )


@upload_bp.route("/upload", methods=["POST"])
@login_required
@_admin_required
def process_upload():
    """
    Accept a carrier BOB file upload, parse it, and upsert into the Policy table.

    Form fields:
        carrier  — one of SUPPORTED_CARRIERS
        file     — the BOB file (CSV, XLSX, or XLS)
    """
    carrier = request.form.get("carrier", "").strip()
    if carrier not in SUPPORTED_CARRIERS:
        flash(f"Invalid carrier selection: '{carrier}'.", "error")
        return redirect(url_for("upload.upload_page"))

    if "file" not in request.files:
        flash("No file was included in the upload.", "error")
        return redirect(url_for("upload.upload_page"))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("upload.upload_page"))

    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash(f"File type '{ext}' is not allowed. Upload CSV, XLSX, or XLS.", "error")
        return redirect(url_for("upload.upload_page"))

    # Save to temp upload dir
    upload_dir = os.path.join(current_app.instance_path, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    # Prefix with UUID to avoid collisions
    safe_filename = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(upload_dir, safe_filename)
    file.save(filepath)

    # Check file size after saving
    filesize = os.path.getsize(filepath)
    if filesize > MAX_FILE_BYTES:
        os.remove(filepath)
        flash("File exceeds the 50 MB size limit.", "error")
        return redirect(url_for("upload.upload_page"))

    # Capture agency_id once from current_user for use throughout this upload
    upload_agency_id = current_user.agency_id

    # Create an ImportBatch record immediately so we can track errors
    batch = ImportBatch(
        agency_id=upload_agency_id,
        carrier=carrier,
        filename=filename,
        uploaded_by_id=current_user.id,
        status="pending",
    )
    db.session.add(batch)
    db.session.commit()

    # Parse the file
    try:
        records = parse_carrier_file(carrier, filepath)
    except ValueError as e:
        batch.status = "error"
        batch.error_message = str(e)
        db.session.commit()
        os.remove(filepath)
        flash(f"Parse error: {e}", "error")
        return redirect(url_for("upload.upload_page"))
    except Exception as e:
        batch.status = "error"
        batch.error_message = f"Unexpected error: {e}"
        db.session.commit()
        os.remove(filepath)
        flash("An unexpected error occurred while reading the file. Check the import log.", "error")
        current_app.logger.error(f"Upload error for {carrier}: {e}", exc_info=True)
        return redirect(url_for("upload.upload_page"))
    finally:
        # Clean up the temp file regardless of outcome
        if os.path.exists(filepath):
            os.remove(filepath)

    # Upsert records into the Policy table
    today = date.today()
    new_count = 0
    updated_count = 0

    for rec in records:
        existing = Policy.query.filter_by(
            carrier=rec["carrier"],
            member_id=rec["member_id"],
            agency_id=upload_agency_id,
        ).first()

        if existing:
            # Update in place
            existing.mbi = rec["mbi"] or existing.mbi
            existing.first_name = rec["first_name"]
            existing.last_name = rec["last_name"]
            existing.full_name = rec["full_name"]
            existing.plan_name = rec["plan_name"]
            existing.plan_type = rec["plan_type"]
            existing.effective_date = rec["effective_date"]
            existing.term_date = rec["term_date"]
            existing.renewal_date = rec.get("renewal_date")
            existing.dob = rec["dob"]
            existing.phone = rec["phone"]
            existing.address1 = rec.get("address1", "")
            existing.city = rec.get("city", "")
            existing.state = rec.get("state", "")
            existing.zip_code = rec.get("zip_code", "")
            existing.county = rec["county"]
            existing.agent_id_carrier = rec["agent_id"]
            existing.status = rec["status"]
            existing.last_seen_date = today
            existing.import_batch_id = batch.id
            updated_count += 1
        else:
            policy = Policy(
                agency_id=upload_agency_id,
                carrier=rec["carrier"],
                member_id=rec["member_id"],
                mbi=rec["mbi"],
                first_name=rec["first_name"],
                last_name=rec["last_name"],
                full_name=rec["full_name"],
                plan_name=rec["plan_name"],
                plan_type=rec["plan_type"],
                effective_date=rec["effective_date"],
                term_date=rec["term_date"],
                renewal_date=rec.get("renewal_date"),
                dob=rec["dob"],
                phone=rec["phone"],
                address1=rec.get("address1", ""),
                city=rec.get("city", ""),
                state=rec.get("state", ""),
                zip_code=rec.get("zip_code", ""),
                county=rec["county"],
                agent_id_carrier=rec["agent_id"],
                status=rec["status"],
                last_seen_date=today,
                import_batch_id=batch.id,
            )
            db.session.add(policy)
            new_count += 1

        # Upsert the customer master record from this policy row
        try:
            _upsert_customer_from_policy(
                rec,
                existing.agent_id if existing else None,
                batch.id,
                upload_agency_id,
            )
        except Exception as e:
            current_app.logger.warning(f"Customer upsert failed for {rec.get('member_id')}: {e}")

    # Finalize batch record
    batch.record_count = len(records)
    batch.new_count = new_count
    batch.updated_count = updated_count
    batch.status = "success"

    # Audit log
    log = AuditLog(
        user_id=current_user.id,
        action="carrier_upload",
        detail=f"{carrier} | {filename} | {len(records)} records ({new_count} new, {updated_count} updated)",
    )
    db.session.add(log)
    db.session.commit()

    flash(
        f"{carrier} upload complete — {len(records)} active members "
        f"({new_count} new, {updated_count} updated).",
        "success",
    )
    return redirect(url_for("upload.upload_page"))


@upload_bp.route("/upload/history")
@login_required
@_admin_required
def import_history():
    """JSON endpoint — returns recent import batches for the history table."""
    batches = (
        ImportBatch.query
        .order_by(ImportBatch.upload_date.desc())
        .limit(50)
        .all()
    )
    return jsonify([
        {
            "id": b.id,
            "carrier": b.carrier,
            "filename": b.filename,
            "uploaded_by": b.uploaded_by.display_name if b.uploaded_by else "Unknown",
            "upload_date": b.upload_date.strftime("%b %d, %Y %I:%M %p") if b.upload_date else "",
            "record_count": b.record_count,
            "new_count": b.new_count,
            "updated_count": b.updated_count,
            "status": b.status,
            "error_message": b.error_message or "",
        }
        for b in batches
    ])


def _detect_carrier(filepath: str, filename: str) -> str:
    import pandas as pd
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext in ('.xlsx', '.xls'):
            try:
                df = pd.read_excel(filepath, header=2, nrows=0, dtype=str)
                df.columns = df.columns.str.strip()
                if 'mbiNumber' in df.columns and 'memberFirstName' in df.columns:
                    return 'UHC'
            except Exception:
                pass
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    chunk = f.read(4096)
                if '<table' in chunk.lower() or '<html' in chunk.lower():
                    from io import StringIO
                    tables = pd.read_html(StringIO(chunk))
                    if tables:
                        cols = set(str(c).strip() for c in tables[0].columns)
                        if 'Medicare Number' in cols:
                            return 'Healthspring'
            except Exception:
                pass
        else:
            df = pd.read_csv(filepath, nrows=0, dtype=str)
            cols = set(df.columns.str.strip())
            if 'mbiNumber' in cols:
                return 'UHC'
            if 'MbrFirstName' in cols and 'Humana ID' in cols:
                return 'Humana'
            if 'Medicare Number' in cols and 'Member Status' in cols:
                return 'Aetna'
            if 'BCBSNC Member Number' in cols:
                return 'BCBS'
            if 'member_id' in cols and 'first_name' in cols and 'status' in cols:
                return 'Devoted'
            if 'Medicare Number' in cols and 'First Name' in cols:
                return 'Healthspring'
    except Exception as e:
        raise ValueError(f"Could not read file: {e}")
    raise ValueError("Could not identify carrier from file headers.")


@upload_bp.route("/upload/bulk", methods=["POST"])
@login_required
@_admin_required
def bulk_upload():
    today = date.today()
    upload_dir = os.path.join(current_app.instance_path, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    results = []
    errors = []

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        flash("No files were submitted.", "warning")
        return redirect(url_for("upload.upload_page"))

    for file in files:
        if not file or file.filename == "":
            continue
        filename = secure_filename(file.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in {".csv", ".xlsx", ".xls"}:
            errors.append(f"{filename}: unsupported file type")
            continue

        safe_filename = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(upload_dir, safe_filename)
        file.save(filepath)

        try:
            carrier = _detect_carrier(filepath, filename)
        except ValueError as e:
            os.remove(filepath)
            errors.append(f"{filename}: {e}")
            continue

        batch = ImportBatch(carrier=carrier, filename=filename,
                           uploaded_by_id=current_user.id, status="pending")
        db.session.add(batch)
        db.session.commit()

        try:
            records = parse_carrier_file(carrier, filepath)
        except Exception as e:
            batch.status = "error"
            batch.error_message = str(e)
            db.session.commit()
            if os.path.exists(filepath): os.remove(filepath)
            errors.append(f"{filename} ({carrier}): {e}")
            continue
        finally:
            if os.path.exists(filepath): os.remove(filepath)

        new_count = updated_count = 0
        for rec in records:
            existing = Policy.query.filter_by(
                carrier=rec["carrier"], member_id=rec["member_id"]
            ).first()
            if existing:
                existing.mbi = rec["mbi"] or existing.mbi
                existing.first_name = rec["first_name"]
                existing.last_name = rec["last_name"]
                existing.full_name = rec["full_name"]
                existing.plan_name = rec["plan_name"]
                existing.plan_type = rec["plan_type"]
                existing.effective_date = rec["effective_date"]
                existing.term_date = rec["term_date"]
                existing.renewal_date = rec.get("renewal_date")
                existing.dob = rec["dob"]
                existing.phone = rec["phone"]
                existing.county = rec["county"]
                existing.address1 = rec.get("address1", "")
                existing.city = rec.get("city", "")
                existing.state = rec.get("state", "")
                existing.zip_code = rec.get("zip_code", "")
                existing.agent_id_carrier = rec["agent_id"]
                existing.status = rec["status"]
                existing.last_seen_date = today
                existing.import_batch_id = batch.id
                updated_count += 1
            else:
                db.session.add(Policy(
                    carrier=rec["carrier"], member_id=rec["member_id"], mbi=rec["mbi"],
                    first_name=rec["first_name"], last_name=rec["last_name"],
                    full_name=rec["full_name"], plan_name=rec["plan_name"],
                    plan_type=rec["plan_type"], effective_date=rec["effective_date"],
                    term_date=rec["term_date"], renewal_date=rec.get("renewal_date"),
                    dob=rec["dob"], phone=rec["phone"], county=rec["county"],
                    address1=rec.get("address1", ""), city=rec.get("city", ""),
                    state=rec.get("state", ""), zip_code=rec.get("zip_code", ""),
                    agent_id_carrier=rec["agent_id"], status=rec["status"],
                    last_seen_date=today, import_batch_id=batch.id,
                ))
                new_count += 1

            # Upsert the customer master record from this policy row
            try:
                _upsert_customer_from_policy(rec, existing.agent_id if existing else None, batch.id)
            except Exception as e:
                current_app.logger.warning(f"Customer upsert failed for {rec.get('member_id')}: {e}")

        batch.record_count = len(records)
        batch.new_count = new_count
        batch.updated_count = updated_count
        batch.status = "success"
        db.session.add(AuditLog(
            user_id=current_user.id, action="carrier_upload",
            detail=f"{carrier} | {filename} | {len(records)} records ({new_count} new, {updated_count} updated)"
        ))
        db.session.commit()
        results.append(f"{carrier}: {len(records)} records")

    msg_parts = []
    if results:
        msg_parts.append("Imported — " + ", ".join(results))
    if errors:
        msg_parts.append("Errors — " + "; ".join(errors))

    flash(" · ".join(msg_parts) if msg_parts else "Nothing processed.",
          "success" if results and not errors else "warning")
    return redirect(url_for("upload.upload_page"))
