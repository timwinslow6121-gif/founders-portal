"""
app/audit.py — S2 security audit trail seam.

log_event() is the ONLY place that writes AuditLog. It captures request context
(real client IP via S1 ProxyFix, user-agent, agency_id, acting user), inserts
one append-only row, and hands the row to app.alerts.maybe_alert for the alert
decision. A failing alert must NEVER break the caller's request — alert dispatch
is wrapped in try/except.

See docs/superpowers/specs/2026-06-10-s2-audit-log-breach-alerting-design.md
"""
import logging
from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models import AuditLog
from app.alerts import maybe_alert

_log = logging.getLogger(__name__)


def log_event(action, *, category, detail=None, user=None, customer_id=None,
              severity="info", record_count=None, agency_id_override=None):
    """Write one audit row + maybe alert. Safe outside a request context."""
    ip = ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.user_agent.string or "")[:256] or None

    acting = user
    if acting is None and has_request_context():
        try:
            if current_user.is_authenticated:
                acting = current_user
        except Exception:
            acting = None

    user_id = getattr(acting, "id", None)
    agency_id = agency_id_override
    if agency_id is None:
        agency_id = getattr(acting, "agency_id", None)

    row = AuditLog(
        user_id=user_id,
        action=action,
        detail=detail,
        category=category,
        severity=severity,
        record_count=record_count,
        ip_address=ip,
        user_agent=ua,
        agency_id=agency_id,
    )
    db.session.add(row)
    db.session.commit()

    try:
        maybe_alert(row)
    except Exception:
        _log.exception("maybe_alert failed for audit row %s", row.id)

    return row
