"""
app/upload.py

Blueprint for carrier BOB file uploads. Available to all agents and admins.
Agents upload their own BOB and see only their own import history.
Admins see all import history across all agents.
"""

import json
import os
import uuid
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from datetime import datetime
from app.models import db, Policy, ImportBatch, Customer, CustomerAorHistory, Plan
from app.audit import log_event
from app.parsers import parse_carrier_file, SUPPORTED_CARRIERS
from app.commission.resolver import resolve_customer, member_fact_from_bob_rec

upload_bp = Blueprint("upload", __name__)


def _dedupe_bob_records(records):
    """Collapse BOB rows that share a (carrier, member_id) so a member listed on
    multiple rows (UHC lists multi-plan/segment members repeatedly) doesn't collide
    on the uq_carrier_member unique constraint mid-upload. LAST occurrence wins (the
    later row carries the more current plan/status), but the row keeps its ORIGINAL
    position so import order is stable. Rows missing a member_id are passed through
    untouched (each is unique; never collapse them onto an empty key)."""
    seen = {}          # (carrier, member_id) -> index in `out`
    out = []
    for rec in records:
        mid = rec.get("member_id")
        carrier = rec.get("carrier")
        if not mid:
            out.append(rec)
            continue
        key = (carrier, mid)
        if key in seen:
            out[seen[key]] = rec          # last wins, keep original slot
        else:
            seen[key] = len(out)
            out.append(rec)
    return out


def _import_bob_row(rec, batch, bulk_agency_id, bulk_agent_id, today, unresolvable):
    """Import ONE BOB record: match/update-or-create its Policy + upsert the
    Customer master. Returns "new", "updated", or "skipped" (for an unresolvable
    no-MBI row). Runs inside a per-row savepoint in the caller, so a raise here
    rolls back only this row."""
    # Quarantine non-Humana rows missing MBI — these cannot create a customer (D-11)
    is_unresolvable = (not rec.get("mbi")) and rec.get("carrier") != "Humana"
    if is_unresolvable:
        unresolvable.append({
            "carrier": rec.get("carrier"),
            "member_id": rec.get("member_id"),
            "full_name": rec.get("full_name"),
            "dob": str(rec.get("dob")) if rec.get("dob") else None,
            "plan_name": rec.get("plan_name"),
            "effective_date": str(rec.get("effective_date")) if rec.get("effective_date") else None,
        })

    # Primary match: carrier + member_id
    existing = Policy.query.filter_by(
        carrier=rec["carrier"], member_id=rec["member_id"],
        agency_id=bulk_agency_id,
    ).first()
    # Fallback: match by MBI when member_id changed between import formats
    if not existing and rec.get("mbi"):
        existing = Policy.query.filter_by(
            carrier=rec["carrier"], mbi=rec["mbi"],
            agency_id=bulk_agency_id,
        ).first()
        if existing:
            existing.member_id = rec["member_id"]   # adopt new member_id as authoritative
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
        if bulk_agent_id:
            existing.agent_id = bulk_agent_id
        outcome = "updated"
    else:
        db.session.add(Policy(
            agency_id=bulk_agency_id,
            agent_id=bulk_agent_id,
            carrier=rec["carrier"], member_id=rec["member_id"], mbi=rec["mbi"] or None,
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
        outcome = "new"

    # Flush the policy NOW so the resolver's crosswalk (which runs under
    # no_autoflush and therefore won't flush it for us) can SEE this just-created
    # policy and adopt it — instead of creating a SECOND policy for the same
    # (carrier, member_id) and tripping uq_carrier_member. (The June 2026 500.)
    db.session.flush()

    # Upsert the customer master record from this policy row. Skip unresolvable
    # rows (no MBI means no reliable customer match). A failure here RAISES — the
    # caller's savepoint rolls back the whole row (policy + customer together).
    effective_agent_id = bulk_agent_id or (existing.agent_id if existing else None)
    if not is_unresolvable:
        _upsert_customer_from_policy(rec, effective_agent_id, batch.id, bulk_agency_id)
    return "skipped" if is_unresolvable else outcome


def _upsert_customer_from_policy(rec: dict, agent_id: int, batch_id: int, agency_id: int) -> None:
    """
    Create or update a Customer from a parsed BOB policy row.

    Identity resolution (crosswalk → MBI → name+DOB → stub) is delegated to the
    shared resolve_customer() service so BOB and commission upload share ONE
    identity codepath. BOB-specific PII rules are applied here afterward:
    - manually_edited customers keep their contact/address fields.
    - BCBS AOR end_date stays None (handled inside the resolver's interval logic).
    """
    fact = member_fact_from_bob_rec(rec)
    result = resolve_customer(fact, agency_id=agency_id, agent_id=agent_id,
                              batch_id=batch_id, source="bob")
    customer = result.customer
    if customer is None:
        return

    now = datetime.utcnow()
    full_name = rec.get("full_name") or f"{rec.get('first_name', '')} {rec.get('last_name', '')}".strip()
    address_parts = [rec.get("address1"), rec.get("city"), rec.get("state"), rec.get("zip_code")]
    carrier_address = ", ".join(p for p in address_parts if p)

    # A BOB row is authoritative carrier data → clear the stub flag if set.
    if customer.stub:
        customer.stub = False
    customer.last_carrier_sync = now
    customer.carrier_address = carrier_address
    mbi = rec.get("mbi") or None
    humana_id = rec.get("member_id") if rec.get("carrier") == "Humana" else None
    if mbi and not customer.mbi:
        customer.mbi = mbi
    if humana_id and not customer.humana_id:
        customer.humana_id = humana_id

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

    # Agent ownership transfer: close previous agent's open AOR row for this carrier.
    if customer.primary_agent_id and customer.primary_agent_id != agent_id:
        open_aor = CustomerAorHistory.query.filter_by(
            customer_id=customer.id, agent_id=customer.primary_agent_id,
            carrier=rec.get("carrier", ""), end_date=None,
        ).first()
        if open_aor:
            open_aor.end_date = now.date()
    customer.primary_agent_id = agent_id

# File extensions allowed per carrier
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Max upload size — enforce in nginx too, but double-check here
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


@upload_bp.route("/upload", methods=["GET"])
@login_required
def upload_page():
    """Render the carrier file upload page with recent import history.

    Agents see only their own batches; admins see all.
    """
    q = ImportBatch.query.filter_by(agency_id=current_user.agency_id)
    if not current_user.is_admin:
        q = q.filter_by(uploaded_by_id=current_user.id)
    recent_batches = q.order_by(ImportBatch.upload_date.desc()).limit(20).all()
    return render_template(
        "upload.html",
        carriers=SUPPORTED_CARRIERS,
        recent_batches=recent_batches,
    )


@upload_bp.route("/upload", methods=["POST"])
@login_required
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

    # Capture context once from current_user for use throughout this upload
    upload_agency_id = current_user.agency_id
    # For agent uploads: policies and customers are attributed to the uploader.
    # For admin uploads: agent_id stays None here — admin matches via carrier file later.
    upload_agent_id = current_user.id if not current_user.is_admin else None

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

    # Build plan alias map for this agency — used to resolve plan_id on each policy row
    def _plan_alias_map(agency_id):
        """Return dict of lowercase BOB plan_name → Plan.id for this agency."""
        m = {}
        for plan in Plan.query.filter_by(agency_id=agency_id).all():
            if plan.plan_name_aliases:
                for alias in plan.plan_name_aliases.split(","):
                    alias = alias.strip()
                    if alias:
                        m[alias.lower()] = plan.id
            if plan.plan_name:
                m[plan.plan_name.lower()] = plan.id
        return m

    alias_map = _plan_alias_map(upload_agency_id)

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
            if upload_agent_id:
                existing.agent_id = upload_agent_id
            existing.plan_id = alias_map.get((rec["plan_name"] or "").strip().lower())
            updated_count += 1
        else:
            policy = Policy(
                agency_id=upload_agency_id,
                agent_id=upload_agent_id,
                carrier=rec["carrier"],
                member_id=rec["member_id"],
                mbi=rec["mbi"] or None,
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
                plan_id=alias_map.get((rec["plan_name"] or "").strip().lower()),
            )
            db.session.add(policy)
            new_count += 1

        # Upsert the customer master record from this policy row
        effective_agent_id = upload_agent_id or (existing.agent_id if existing else None)
        try:
            _upsert_customer_from_policy(
                rec,
                effective_agent_id,
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
    db.session.commit()
    log_event("carrier_upload", category="business",
              detail=f"{carrier} | {filename} | {len(records)} records ({new_count} new, {updated_count} updated)")

    flash(
        f"{carrier} upload complete — {len(records)} active members "
        f"({new_count} new, {updated_count} updated).",
        "success",
    )
    return redirect(url_for("upload.upload_page"))


@upload_bp.route("/upload/batch/<int:batch_id>/delete", methods=["POST"])
@login_required
def delete_batch(batch_id):
    """Delete an import batch record. Only pending/error batches can be deleted.
    Agents can only delete their own; admins can delete any."""
    batch = ImportBatch.query.filter_by(
        id=batch_id, agency_id=current_user.agency_id).first_or_404()
    if not current_user.is_admin and batch.uploaded_by_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    if batch.status == "success":
        return jsonify({"error": "Cannot delete a successful import — it has already modified policy records."}), 400
    db.session.delete(batch)
    db.session.commit()
    return jsonify({"ok": True})


@upload_bp.route("/upload/batch/<int:batch_id>/detail")
@login_required
def batch_detail(batch_id):
    """Return detail for a single import batch — new, updated, and missing policies."""
    batch = ImportBatch.query.filter_by(
        id=batch_id, agency_id=current_user.agency_id).first_or_404()
    if not current_user.is_admin and batch.uploaded_by_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    # New policies: added in this batch
    new_policies = Policy.query.filter_by(
        import_batch_id=batch_id, agency_id=current_user.agency_id
    ).filter(Policy.created_at >= batch.upload_date).all()

    # All policies seen in this batch
    seen_in_batch = Policy.query.filter_by(
        import_batch_id=batch_id, agency_id=current_user.agency_id).all()
    seen_ids = {p.id for p in seen_in_batch}

    # Updated: seen in this batch but existed before it (not new)
    new_ids = {p.id for p in new_policies}
    updated = [p for p in seen_in_batch if p.id not in new_ids]

    # Missing (lost): same carrier + agent, last seen in a PREVIOUS batch
    missing = []
    if batch.status == "success":
        agent_id_filter = batch.uploaded_by_id if not current_user.is_admin else None
        q = Policy.query.filter(
            Policy.agency_id == current_user.agency_id,
            Policy.carrier == batch.carrier,
            Policy.import_batch_id != batch_id,
            Policy.import_batch_id.isnot(None),
        )
        if agent_id_filter:
            q = q.filter(Policy.agent_id == agent_id_filter)
        missing = q.all()

    def _pol(p):
        return {
            "member_id": p.member_id,
            "full_name": p.full_name or f"{p.first_name} {p.last_name}".strip(),
            "plan_name": p.plan_name or "",
            "plan_type": p.plan_type or "",
            "effective_date": str(p.effective_date) if p.effective_date else "",
            "term_date": str(p.term_date) if p.term_date else "",
            "last_seen_date": str(p.last_seen_date) if p.last_seen_date else "",
        }

    unresolvable = []
    if batch.unresolvable_json:
        try:
            unresolvable = json.loads(batch.unresolvable_json)
        except (json.JSONDecodeError, TypeError):
            unresolvable = []

    return jsonify({
        "batch": {
            "id": batch.id,
            "carrier": batch.carrier,
            "filename": batch.filename,
            "upload_date": batch.upload_date.strftime("%b %d, %Y %I:%M %p") if batch.upload_date else "",
            "record_count": batch.record_count,
            "new_count": batch.new_count,
            "updated_count": batch.updated_count,
            "status": batch.status,
        },
        "new": [_pol(p) for p in new_policies],
        "updated": [_pol(p) for p in updated],
        "missing": [_pol(p) for p in missing],
        "unresolvable": unresolvable,
    })


@upload_bp.route("/upload/unresolvable/resolve", methods=["POST"])
@login_required
def resolve_unresolvable():
    """Resolve one row from a batch's unresolvable_json list.

    Request body (JSON):
      batch_id: int
      row_idx: int — index into the unresolvable_json array
      action: 'assign_existing' | 'enter_mbi' | 'create_new'
      customer_id: int — required for 'assign_existing'
      mbi: str — required for 'enter_mbi' and 'create_new'
    """
    from app.models import Customer

    data = request.get_json(silent=True) or request.form

    try:
        batch_id = int(data.get("batch_id", 0))
        row_idx = int(data.get("row_idx", -1))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid batch_id or row_idx."}), 400

    action = data.get("action", "")

    batch = ImportBatch.query.filter_by(
        id=batch_id, agency_id=current_user.agency_id
    ).first_or_404()

    if not batch.unresolvable_json:
        return jsonify({"error": "No unresolvable rows on this batch."}), 400

    try:
        rows = json.loads(batch.unresolvable_json)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Could not parse unresolvable rows."}), 500

    if row_idx < 0 or row_idx >= len(rows):
        return jsonify({"error": "Invalid row index."}), 400

    row = rows[row_idx]

    if action == "assign_existing":
        try:
            cid = int(data.get("customer_id", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "customer_id must be an integer."}), 400
        target = Customer.query.filter_by(
            id=cid, agency_id=current_user.agency_id
        ).first_or_404()
        # Link the policy by updating its MBI to match the target customer's MBI
        if target.mbi and row.get("member_id"):
            Policy.query.filter_by(
                agency_id=current_user.agency_id,
                carrier=row.get("carrier"),
                member_id=row.get("member_id"),
            ).update({"mbi": target.mbi})

    elif action in ("enter_mbi", "create_new"):
        mbi = (data.get("mbi") or "").strip().upper()
        if not mbi:
            return jsonify({"error": "MBI is required."}), 400

        # Try to match existing customer by MBI first
        existing = Customer.query.filter_by(
            agency_id=current_user.agency_id, mbi=mbi
        ).first()

        if existing and action == "enter_mbi":
            # MBI already known — just link the policy
            pass
        else:
            # Create a new customer from the row data
            full_name = row.get("full_name") or ""
            parts = full_name.split(" ", 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""
            from datetime import date as _date
            new_c = Customer(
                agency_id=current_user.agency_id,
                primary_agent_id=current_user.id,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                mbi=mbi,
                dob=row.get("dob"),
            )
            db.session.add(new_c)
            db.session.flush()

        # Update the corresponding Policy row to carry this MBI
        if row.get("member_id"):
            Policy.query.filter_by(
                agency_id=current_user.agency_id,
                carrier=row.get("carrier"),
                member_id=row.get("member_id"),
            ).update({"mbi": mbi})

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    # Remove the resolved row from the unresolvable list
    rows.pop(row_idx)
    batch.unresolvable_json = json.dumps(rows) if rows else None
    db.session.commit()

    return jsonify({"ok": True, "remaining": len(rows)})


@upload_bp.route("/upload/history")
@login_required
def import_history():
    """JSON endpoint — returns recent import batches for the history table.

    Agents see only their own batches; admins see all.
    """
    q = ImportBatch.query.filter_by(agency_id=current_user.agency_id)
    if not current_user.is_admin:
        q = q.filter_by(uploaded_by_id=current_user.id)
    batches = q.order_by(ImportBatch.upload_date.desc()).limit(50).all()
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
    """
    Fingerprint a BOB file by its column headers to determine the carrier.
    All 7 carriers now send XLSX. Each has a unique combination of header strings.
    """
    import openpyxl
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ('.xlsx', '.xls', '.csv'):
        raise ValueError(f"Unsupported file type: {ext}")

    try:
        if ext == '.csv':
            import pandas as pd
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
            raise ValueError("Could not identify carrier from CSV headers.")

        # XLSX/XLS — scan first 15 rows to find the real header row
        # (some carriers include multi-row preambles before the column headers)
        # Some .xls files are actually HTML — detect and handle separately
        with open(filepath, "rb") as _f:
            _magic = _f.read(2)
        if _magic[:1] == b"<":
            # HTML-disguised-as-XLS (e.g. Healthspring XLS export)
            import pandas as _pd
            from io import StringIO as _StringIO
            with open(filepath, "r", encoding="ISO-8859-1", errors="replace") as _f:
                _content = _f.read()
            _tables = _pd.read_html(_StringIO(_content), header=0)
            headers = list(_tables[0].columns) if _tables else []
        else:
            wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
            ws = wb.active
            headers = []
            for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
                candidate = [str(c or "").strip() for c in row]
                named = [c for c in candidate if c]
                if len(named) >= 3:
                    headers = candidate
                    break
            wb.close()
        header_set = set(h.lower() for h in headers)
        header_str = " ".join(str(h) for h in headers).lower()

        # UHC BOB portal download: "mbiNumber" + "memberFirstName" + "agentId"
        if "mbinumber" in header_set and "memberfirstname" in header_set:
            return "UHC"
        # Humana BOB: "CommRunDt" + "WaName" + "PaidAmount"
        if "commrundt" in header_set and "waname" in header_set:
            return "Humana"
        # Humana BOB portal export (XLSX or CSV): "MbrFirstName" + "Humana ID"
        if "mbrfirstname" in header_set and "humana id" in header_set:
            return "Humana"
        # BCBS BOB: "Agent #" + "Agent Name" + "ORIGEFFDATE"
        if "agent #" in header_set and "origeffdate" in header_set:
            return "BCBS"
        # Devoted BOB: "Agent NPN" + "Member HICN"
        if "agent npn" in header_set and "member hicn" in header_set:
            return "Devoted"
        # Aetna BOB: "Medicare Number" + "Sales Event" + "Writing Agent Name"
        if "medicare number" in header_set and "sales event" in header_set:
            return "Aetna"
        # Healthspring BOB portal: "Medicare Number" + "First Name" + "Disenroll Effective Date"
        if "medicare number" in header_set and "first name" in header_set and "disenroll effective date" in header_str:
            return "Healthspring"
        # Wellable BOB: "Distributor Number" + "Writing Agent Number"
        if "distributor number" in header_set and "writing agent number" in header_set:
            return "Wellable"

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read file: {e}")

    raise ValueError("Could not identify carrier from file headers.")


@upload_bp.route("/upload/bulk", methods=["POST"])
@login_required
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

        bulk_agency_id = current_user.agency_id
        bulk_agent_id = current_user.id if not current_user.is_admin else None

        batch = ImportBatch(
            agency_id=bulk_agency_id,
            carrier=carrier,
            filename=filename,
            uploaded_by_id=current_user.id,
            status="pending",
        )
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

        # Collapse repeated (carrier, member_id) rows BEFORE the loop so a member
        # listed multiple times in the file can't collide on uq_carrier_member.
        records = _dedupe_bob_records(records)

        new_count = updated_count = 0
        unresolvable = []
        skipped_rows = []
        for rec in records:
            # Per-row savepoint: if ANY DB op for this row fails (e.g. a unique-
            # constraint violation we didn't pre-empt), roll back JUST this row so
            # the failed flush can't poison the session and 500 the whole upload.
            # The bad row is skipped + logged; the rest of the file still imports.
            try:
                with db.session.begin_nested():
                    outcome = _import_bob_row(
                        rec, batch, bulk_agency_id, bulk_agent_id, today, unresolvable)
                if outcome == "new":
                    new_count += 1
                elif outcome == "updated":
                    updated_count += 1
            except Exception as e:
                current_app.logger.warning(
                    f"BOB row skipped ({rec.get('carrier')} {rec.get('member_id')}): {e}")
                skipped_rows.append({"carrier": rec.get("carrier"),
                                     "member_id": rec.get("member_id"),
                                     "full_name": rec.get("full_name"), "error": str(e)})

        # Persist quarantined rows onto the batch for inline resolution via the modal
        if unresolvable:
            batch.unresolvable_json = json.dumps(unresolvable)

        batch.record_count = len(records)
        batch.new_count = new_count
        batch.updated_count = updated_count
        batch.status = "success"
        db.session.commit()
        log_event("carrier_upload", category="business",
                  detail=f"{carrier} | {filename} | {len(records)} records "
                         f"({new_count} new, {updated_count} updated, {len(skipped_rows)} skipped)")
        result = f"{carrier}: {len(records)} records"
        if skipped_rows:
            result += f" ({len(skipped_rows)} rows skipped — see logs)"
        results.append(result)

    msg_parts = []
    if results:
        msg_parts.append("Imported — " + ", ".join(results))
    if errors:
        msg_parts.append("Errors — " + "; ".join(errors))

    flash(" · ".join(msg_parts) if msg_parts else "Nothing processed.",
          "success" if results and not errors else "warning")
    return redirect(url_for("upload.upload_page"))
