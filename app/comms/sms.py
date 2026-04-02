"""
app/comms/sms.py

SMS sending function and POST /comms/sms/send route.

send_sms_template(customer, template, agent_user):
    - Raises ValueError("no_consent") if customer.sms_consent_at is None
    - Raises ValueError("template_not_approved") if template.status != "approved"
    - Calls Twilio to send the SMS
    - Creates a CustomerNote(note_type="sms") with twilio_msg_sid
    - Commits to DB
    - Returns the Twilio message SID

POST /comms/sms/send:
    - Accepts form fields: customer_id, template_id
    - Calls send_sms_template()
    - Flash on error or success; redirect to customer profile on success
"""

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from twilio.rest import Client

from app.comms import comms_bp
from app.comms.utils import normalize_e164
from app.extensions import db
from app.models import Customer, CustomerNote, SmsTemplate


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------

def send_sms_template(customer, template, agent_user):
    """
    Send an approved SMS template to a consenting customer via Twilio.

    Args:
        customer   (Customer)    — recipient; must have sms_consent_at set
        template   (SmsTemplate) — must have status == 'approved'
        agent_user (User)        — agent initiating the send; used for agency_id fallback

    Returns:
        str: Twilio message SID on success

    Raises:
        ValueError("no_consent")           — if customer.sms_consent_at is None
        ValueError("template_not_approved") — if template.status != 'approved'
        TwilioRestException               — propagated from Twilio if send fails
    """
    from flask import current_app

    if customer.sms_consent_at is None:
        raise ValueError("no_consent")

    if template.status != "approved":
        raise ValueError("template_not_approved")

    to_number = normalize_e164(customer.phone_primary)

    client = Client(
        current_app.config["TWILIO_ACCOUNT_SID"],
        current_app.config["TWILIO_AUTH_TOKEN"],
    )
    message = client.messages.create(
        body=template.body,
        from_=current_app.config["TWILIO_FROM_NUMBER"],
        to=to_number,
    )

    note = CustomerNote(
        customer_id=customer.id,
        agent_id=agent_user.id,
        note_type="sms",
        note_text=f"[Template: {template.name}] {template.body}",
        contact_method="sms",
        twilio_msg_sid=message.sid,
    )
    db.session.add(note)
    db.session.commit()

    return message.sid


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@comms_bp.route("/sms/send", methods=["POST"])
@login_required
def sms_send():
    """
    POST /comms/sms/send — send an approved SMS template to a customer.

    Form fields:
        customer_id  (int) — Customer.id
        template_id  (int) — SmsTemplate.id

    On success: flash and redirect to customer profile.
    On error:   flash and redirect back to referring page.
    """
    customer_id = request.form.get("customer_id", type=int)
    template_id = request.form.get("template_id", type=int)

    if not customer_id or not template_id:
        flash("Invalid request — customer and template are required.", "error")
        return redirect(request.referrer or url_for("customers.customers_list"))

    # Scope lookups to current user's agency when available
    agency_id = getattr(current_user, "agency_id", None)

    if agency_id:
        customer = Customer.query.filter_by(id=customer_id).first_or_404()
        template = SmsTemplate.query.filter_by(
            id=template_id, agency_id=agency_id, status="approved"
        ).first_or_404()
    else:
        customer = Customer.query.get_or_404(customer_id)
        template = SmsTemplate.query.filter_by(
            id=template_id, status="approved"
        ).first_or_404()

    try:
        send_sms_template(customer, template, current_user)
    except ValueError as exc:
        if "no_consent" in str(exc):
            flash("Customer has not provided SMS consent.", "error")
        elif "template_not_approved" in str(exc):
            flash("That template has not been approved yet.", "error")
        else:
            flash(f"SMS could not be sent: {exc}", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))
    except Exception:
        flash("SMS delivery failed — check Twilio logs.", "error")
        return redirect(url_for("customers.customer_profile", customer_id=customer_id))

    flash(f"SMS sent to {customer.display_name}.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=customer_id))
