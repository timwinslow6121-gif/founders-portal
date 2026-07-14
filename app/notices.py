"""Agency Notice Board — the public-safe board on the pre-login page.
Holds the AEP-countdown helper, the notice-type presentation map, the board
read, and (added in the admin task) the notices_bp CRUD blueprint.
See docs/superpowers/specs/2026-07-14-login-redesign-agency-notice-board-design.md."""
from datetime import date

from app.models import AgencyNotice

# notice_type -> presentation. ONE place; template + tests agree on this.
NOTICE_PRESENTATION = {
    "info":  {"accent": "info",  "icon": "info"},
    "alert": {"accent": "alert", "icon": "alert"},
}


def next_aep(today):
    """(days, year) until the next AEP start (Oct 15). days>=0 (0 on Oct 15);
    rolls to next year once Oct 15 has passed. year = calendar year of that Oct 15."""
    aep = date(today.year, 10, 15)
    if today > aep:
        aep = date(today.year + 1, 10, 15)
    return (aep - today).days, aep.year


def board_notices(agency_id, today=None):
    """Visible notices for the login board (thin seam over the model)."""
    return AgencyNotice.visible_for(agency_id, today or date.today())
