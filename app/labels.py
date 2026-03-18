"""
Birthday Labels Blueprint
Generates Avery 5160 CSV (30 labels/sheet, 3 cols × 10 rows) for active
customers whose birthday falls in the selected month.

Deduplication rule: one label per unique (full_name + address1 + zip_code)
household — same logic as the Google Sheets version.

Route: /labels
"""

import csv
import io
import re
from datetime import date, datetime

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import extract

from app.extensions import db
from app.models import Policy

labels_bp = Blueprint("labels", __name__)

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _title_case(s: str) -> str:
    """Convert a string to title case, preserving state abbreviations."""
    if not s:
        return ""
    # State abbreviations we want to keep uppercase
    STATE_ABBREVS = {
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
        "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
        "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI",
        "SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC",
    }
    words = s.strip().split()
    result = []
    for word in words:
        upper = word.upper().rstrip(",.")
        if upper in STATE_ABBREVS:
            # Preserve any trailing punctuation
            suffix = word[len(upper):]
            result.append(upper + suffix)
        else:
            result.append(word.capitalize())
    return " ".join(result)


def _build_label(policy: Policy) -> str:
    """Build a 3-line mailing label string for a policy record."""
    name = _title_case(policy.full_name or f"{policy.first_name} {policy.last_name}")

    # Build address line 1
    street = _title_case(policy.address1 or "")

    # Build city/state/zip line
    city  = _title_case(policy.city or "")
    state = (policy.state or "").strip().upper()
    zip_  = (policy.zip_code or "").strip()

    city_state_zip_parts = [p for p in [city, state, zip_] if p]
    city_state_zip = ", ".join(
        [city] + ([state + " " + zip_] if state or zip_ else [])
    ).strip(", ")

    # Compact: "Charlotte, NC 28202"
    if city and state and zip_:
        city_state_zip = f"{city}, {state} {zip_}"
    elif city and state:
        city_state_zip = f"{city}, {state}"
    elif city:
        city_state_zip = city

    lines = [name]
    if street:
        lines.append(street)
    if city_state_zip:
        lines.append(city_state_zip)

    return "\n".join(lines)


def _get_birthday_policies(month: int, agent_id: int):
    """
    Return active policies for the given agent whose DOB month matches.
    Filters:
      - status == 'active'
      - dob is not null
      - dob month == month
      - address1 is not null (need a mailing address)
    Deduplication: one label per (normalized_name + address1 + zip_code).
    """
    policies = (
        Policy.query
        .filter(
            Policy.agent_id == agent_id,
            Policy.status == "active",
            Policy.dob.isnot(None),
            Policy.address1.isnot(None),
            Policy.address1 != "",
            extract("month", Policy.dob) == month,
        )
        .order_by(Policy.last_name, Policy.first_name)
        .all()
    )

    seen = set()
    unique = []
    for p in policies:
        name_key = (p.full_name or f"{p.first_name} {p.last_name}").strip().lower()
        addr_key = (p.address1 or "").strip().lower()
        zip_key  = (p.zip_code or "").strip()
        fingerprint = f"{name_key}|{addr_key}|{zip_key}"
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(p)

    return unique


def _policies_missing_address(month: int, agent_id: int):
    """Return active policies for the month that have no address — needs attention."""
    return (
        Policy.query
        .filter(
            Policy.agent_id == agent_id,
            Policy.status == "active",
            Policy.dob.isnot(None),
            extract("month", Policy.dob) == month,
            db.or_(
                Policy.address1.is_(None),
                Policy.address1 == "",
            ),
        )
        .order_by(Policy.last_name, Policy.first_name)
        .all()
    )


def _build_avery5160_csv(policies) -> str:
    """
    Avery 5160: 3 columns × 10 rows = 30 labels per sheet.
    Output: CSV with columns Label1, Label2, Label3.
    Each cell contains a newline-separated label (name / street / city,st zip).
    Word/mail-merge compatible — newlines are literal \\n in the cell value.
    """
    labels = [_build_label(p) for p in policies]

    # Pad to a multiple of 3 so the grid fills evenly
    while len(labels) % 3 != 0:
        labels.append("")

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["Label1", "Label2", "Label3"])

    for i in range(0, len(labels), 3):
        writer.writerow([labels[i], labels[i + 1], labels[i + 2]])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@labels_bp.route("/labels")
@login_required
def labels_page():
    today = date.today()
    selected_month = request.args.get("month", type=int, default=today.month)

    if not (1 <= selected_month <= 12):
        selected_month = today.month

    policies   = _get_birthday_policies(selected_month, current_user.id)
    no_address = _policies_missing_address(selected_month, current_user.id)

    # Workload preview — count per month for the sidebar summary
    monthly_counts = {}
    for m in range(1, 13):
        monthly_counts[m] = len(_get_birthday_policies(m, current_user.id))

    return render_template(
        "labels.html",
        selected_month=selected_month,
        month_name=MONTH_NAMES[selected_month - 1],
        month_names=MONTH_NAMES,
        policies=policies,
        no_address=no_address,
        monthly_counts=monthly_counts,
        today=today,
    )


@labels_bp.route("/labels/download")
@login_required
def labels_download():
    month = request.args.get("month", type=int)
    if not month or not (1 <= month <= 12):
        flash("Invalid month selected.", "error")
        return redirect(url_for("labels.labels_page"))

    policies = _get_birthday_policies(month, current_user.id)

    if not policies:
        flash(f"No customers with complete addresses have birthdays in {MONTH_NAMES[month - 1]}.", "warning")
        return redirect(url_for("labels.labels_page", month=month))

    csv_content = _build_avery5160_csv(policies)
    month_name  = MONTH_NAMES[month - 1]
    year        = date.today().year
    filename    = f"birthday_labels_{month_name.lower()}_{year}.csv"

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
