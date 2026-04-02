"""
app/comms/__init__.py

Communications Hub blueprint — Quo webhooks, Calendly, Google Meet, SMS templates.
"""
from flask import Blueprint, jsonify
from flask_login import current_user

comms_bp = Blueprint('comms', __name__, url_prefix='/comms')


@comms_bp.app_context_processor
def inject_unmatched_count():
    """Inject unresolved unmatched-call count into all templates for sidebar badge."""
    from app.models import UnmatchedCall
    try:
        if current_user.is_authenticated:
            agency_id = getattr(current_user, 'agency_id', None)
            if agency_id:
                count = UnmatchedCall.query.filter_by(
                    agency_id=agency_id,
                    resolved=False
                ).count()
                return {"unmatched_call_count": count}
    except Exception:
        pass
    return {"unmatched_call_count": 0}


@comms_bp.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


from app.comms import webhooks  # noqa: E402,F401 — registers /comms/webhook/* routes
