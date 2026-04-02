"""
app/comms/resolution.py

UnmatchedCall resolution queue.

Routes:
    GET  /comms/resolution              — list unresolved calls (agent-scoped or all for admin)
    POST /comms/resolution/<id>/link    — link an unmatched call to an existing customer

Agents review unmatched calls that could not be automatically matched to a
Customer record and manually link them.  Linking creates a CustomerNote and
marks the UnmatchedCall resolved.
"""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from flask import current_app

from app.comms import comms_bp
from app.extensions import db
from app.models import Customer, CustomerNote, UnmatchedCall


def _agency_id():
    """
    Return the current user's agency_id.

    User.agency_id column is added in Plan 07.  Until then, fall back to
    DEFAULT_AGENCY_ID from config so queries remain multi-tenant-safe.
    """
    agency_id = getattr(current_user, "agency_id", None)
    if agency_id is None:
        agency_id = current_app.config.get("DEFAULT_AGENCY_ID", 1)
    return agency_id


@comms_bp.route("/resolution")
@login_required
def resolution_queue():
    """
    List unresolved UnmatchedCall records for the current agent (or all for admin).
    Scoped by agency_id for multi-tenant safety.
    """
    q = UnmatchedCall.query.filter_by(agency_id=_agency_id(), resolved=False)
    if not current_user.is_admin:
        q = q.filter_by(agent_id=current_user.id)
    calls = q.order_by(UnmatchedCall.occurred_at.desc()).all()
    return render_template("comms/unmatched_calls.html", calls=calls)


@comms_bp.route("/resolution/<int:call_id>/link", methods=["POST"])
@login_required
def link_unmatched_call(call_id):
    """
    Link an unmatched call to an existing customer.

    1. Validate call belongs to current agency and is unresolved.
    2. Validate customer_id from form.
    3. Create CustomerNote with appropriate note_type.
    4. Mark UnmatchedCall resolved.
    5. Redirect back to resolution queue.

    NOTE: Customer.agency_id filter is deferred to Plan 07 when the column exists.
    """
    uc = UnmatchedCall.query.filter_by(
        id=call_id,
        agency_id=_agency_id(),
        resolved=False,
    ).first_or_404()

    customer_id = request.form.get("customer_id", type=int)
    if not customer_id:
        flash("Customer ID is required.", "error")
        return redirect(url_for("comms.resolution_queue"))

    # NOTE: agency_id not on Customer yet (Plan 07) — omit agency_id filter for now
    customer = Customer.query.filter_by(id=customer_id).first_or_404()

    note_type = "appointment_scheduled" if uc.provider == "calendly" else "call"

    note = CustomerNote(
        customer_id=customer.id,
        agent_id=current_user.id,
        note_type=note_type,
        note_text=f"Linked from unmatched {uc.provider} call — {uc.from_number or uc.call_sid}",
        contact_method="phone",
        created_at=datetime.utcnow(),
    )
    db.session.add(note)
    db.session.flush()  # populate note.id before assigning to uc

    uc.resolved = True
    uc.resolved_at = datetime.utcnow()
    uc.resolved_by_id = current_user.id
    uc.resolved_note_id = note.id

    db.session.commit()

    flash(f"Call linked to {customer.display_name}.", "success")
    return redirect(url_for("comms.resolution_queue"))
