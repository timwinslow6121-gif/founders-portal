"""
Work queues (SPEC 6.1).

A customer appears in AT MOST ONE queue. The prototype tried to achieve that
with per-predicate exclusions and failed: running its own logic over its own
526-customer book puts 2 customers in both `shp` and `today`, because
callfirst/noreply exclude shp and today/catchup/waiting/undecided do not.

Here the order of QUEUES IS the priority order and the first match wins, so
exclusivity is a property of the structure. Each predicate states only its own
condition -- do NOT add defensive exclusions of higher-priority queues back
into a predicate; that is the O(n^2) invariant this module exists to remove.
"""
import datetime as dt

from app.models import Appointment, is_contactable
from app.pipeline.triage import tier_for

# (id, title, urgent) -- order is priority order. Titles are the prototype's
# wording verbatim; do not "improve" them into CRM jargon.
QUEUES = [
    ("shp",       "State retirees to call",        True),
    ("catchup",   "Write down what happened",      True),
    ("today",     "Appointments today",            False),
    ("waiting",   "Things you are waiting on",     True),
    ("callfirst", "People to call first",          True),
    ("undecided", "Thinking it over",              True),
    ("noreply",   "People who have not called back", False),
]


def _latest_appointment(state):
    """Most recent appointment for this customer, agency-scoped."""
    return (Appointment.query
            .filter_by(customer_id=state.customer_id, agency_id=state.agency_id)
            .order_by(Appointment.starts_at.desc()).first())


def stalled_reason(state, cfg, today):
    """How long someone has sat in a stage. Stalled is a property, not a stage."""
    since = state.stage_since.date() if state.stage_since else today
    days = (today - since).days

    if state.stage == "contact":
        if state.attempts >= 2 and state.first_try_at:
            waited = (today - state.first_try_at.date()).days
            if waited >= cfg.stall_contact_days:
                return f"No reply in {waited} days"
        return None
    if state.stage == "scheduled":
        appt = _latest_appointment(state)
        if appt and appt.starts_at.date() < today and appt.outcome_recorded_at is None:
            return "Outcome not logged"
        return None
    if state.stage == "deciding":
        return f"Undecided {days} days" if days >= cfg.stall_deciding_days else None
    if state.stage == "submitted":
        return f"Unconfirmed {days} days" if days >= cfg.stall_submitted_days else None
    return None


def _has_appointment_today(state, today):
    appt = _latest_appointment(state)
    return bool(appt and appt.starts_at.date() == today)


def queue_for(customer, state, cfg, today=None):
    """The ONE queue this customer belongs in, or None.

    First match wins. Adding a queue means inserting it at the right position,
    not editing every other predicate.
    """
    today = today or dt.date.today()

    # Never surface someone who is finished or must not be contacted.
    # is_contactable() is the portal's single suppression seam (models.py);
    # it covers deceased_date so nothing here reads that column directly.
    if not is_contactable(customer):
        return None
    if state.stage == "done":
        return None

    stalled = stalled_reason(state, cfg, today)

    if cfg.shp_enabled and state.shp_flag and state.shp_confirmed_at is None:
        return "shp"
    if state.stage == "scheduled" and stalled:
        return "catchup"
    if state.stage == "scheduled" and _has_appointment_today(state, today):
        return "today"
    if state.waiting_due and state.waiting_due <= today:
        return "waiting"
    if state.stage == "contact" and state.attempts == 0:
        if tier_for(customer, state, cfg, today).tier == 1:
            return "callfirst"
        return None
    if state.stage == "deciding" and stalled and not state.waiting_due:
        return "undecided"
    if state.stage == "contact" and stalled:
        return "noreply"
    return None


def queue_counts(agency_id, agent_id, cfg, today=None):
    """{queue_id: count} for one agent's book. Sums to 'people with any work'."""
    from app.models import Customer, PipelineState

    today = today or dt.date.today()
    rows = (PipelineState.query
            .join(Customer, Customer.id == PipelineState.customer_id)
            .filter(PipelineState.agency_id == agency_id,
                    Customer.agency_id == agency_id,
                    Customer.primary_agent_id == agent_id,
                    Customer.deceased_date.is_(None))
            .all())
    counts = {qid: 0 for qid, _, _ in QUEUES}
    for state in rows:
        q = queue_for(state.customer, state, cfg, today)
        if q:
            counts[q] += 1
    return counts
