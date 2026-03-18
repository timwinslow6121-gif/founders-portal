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

from app.models import db, Policy, ImportBatch, AuditLog
from app.parsers import parse_carrier_file, SUPPORTED_CARRIERS

upload_bp = Blueprint("upload", __name__)

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

    # Create an ImportBatch record immediately so we can track errors
    batch = ImportBatch(
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
            existing.dob = rec["dob"]
            existing.phone = rec["phone"]
            existing.county = rec["county"]
            existing.agent_id_carrier = rec["agent_id"]
            existing.status = rec["status"]
            existing.last_seen_date = today
            existing.import_batch_id = batch.id
            updated_count += 1
        else:
            policy = Policy(
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
                dob=rec["dob"],
                phone=rec["phone"],
                county=rec["county"],
                agent_id_carrier=rec["agent_id"],
                status=rec["status"],
                last_seen_date=today,
                import_batch_id=batch.id,
            )
            db.session.add(policy)
            new_count += 1

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
