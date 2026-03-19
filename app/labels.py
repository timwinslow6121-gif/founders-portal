import csv
import io
import base64
from datetime import date
from flask import Blueprint, Response, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from sqlalchemy import extract
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition
from app.extensions import db
from app.models import Policy

labels_bp = Blueprint("labels", __name__)

MONTH_NAMES = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]

PAGE_WIDTH      = 8.5 * inch
PAGE_HEIGHT     = 11.0 * inch
LABEL_WIDTH     = 2.625 * inch
LABEL_HEIGHT    = 1.0 * inch
LEFT_MARGIN     = 0.19 * inch
TOP_MARGIN      = 0.5 * inch
H_GAP           = 0.125 * inch
COLS            = 3
ROWS            = 10


def _title_case(s):
    if not s:
        return ""
    STATE_ABBREVS = {"AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL",
        "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
        "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX",
        "UT","VT","VA","WA","WV","WI","WY","DC"}
    words = s.strip().split()
    result = []
    for word in words:
        upper = word.upper().rstrip(",.")
        suffix = word[len(upper):]
        result.append(upper + suffix if upper in STATE_ABBREVS else word.capitalize())
    return " ".join(result)


def _get_birthday_policies(month, agent_id):
    policies = (Policy.query
        .filter(
            Policy.agent_id == agent_id,
            Policy.status == "active",
            Policy.dob.isnot(None),
            Policy.address1.isnot(None),
            Policy.address1 != "",
            extract("month", Policy.dob) == month,
        )
        .order_by(Policy.last_name, Policy.first_name)
        .all())
    seen = set()
    unique = []
    for p in policies:
        name_key = (p.full_name or f"{p.first_name} {p.last_name}").strip().lower()
        fp = f"{name_key}|{(p.address1 or '').strip().lower()}|{(p.zip_code or '').strip()}"
        if fp not in seen:
            seen.add(fp)
            unique.append(p)
    return unique


def _policies_missing_address(month, agent_id):
    return (Policy.query
        .filter(
            Policy.agent_id == agent_id,
            Policy.status == "active",
            Policy.dob.isnot(None),
            extract("month", Policy.dob) == month,
            db.or_(Policy.address1.is_(None), Policy.address1 == ""),
        )
        .order_by(Policy.last_name, Policy.first_name)
        .all())


def _build_pdf(policies, month_name):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))

    label_idx = 0
    total     = len(policies)

    while label_idx < total:
        for row in range(ROWS):
            for col in range(COLS):
                if label_idx >= total:
                    break
                p = policies[label_idx]
                label_idx += 1

                x = LEFT_MARGIN + col * (LABEL_WIDTH + H_GAP)
                y = PAGE_HEIGHT - TOP_MARGIN - (row + 1) * LABEL_HEIGHT

                name   = _title_case(p.full_name or f"{p.first_name} {p.last_name}")
                street = _title_case(p.address1 or "")
                city   = _title_case(p.city or "")
                state  = (p.state or "").strip().upper()
                zip_   = (p.zip_code or "").strip()

                if city and state and zip_:
                    csz = f"{city}, {state} {zip_}"
                elif city and state:
                    csz = f"{city}, {state}"
                else:
                    csz = city

                lines      = [l for l in [name, street, csz] if l]
                text_y     = y + LABEL_HEIGHT - 0.18 * inch
                line_height = 0.22 * inch

                for i, line in enumerate(lines):
                    c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 10)
                    c.drawString(x + 0.05 * inch, text_y - i * line_height, line)

            if label_idx >= total:
                break

        if label_idx < total:
            c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()


def _send_labels_email(pdf_bytes, month_name, label_count, no_address_policies, agent_email):
    api_key    = current_app.config.get("SENDGRID_API_KEY")
    to_email   = current_app.config.get("LABELS_EMAIL")
    from_email = current_app.config.get("LABELS_FROM_EMAIL")
    year       = date.today().year
    skipped    = len(no_address_policies)

    subject = f"Birthday Labels: {month_name} {year} ({label_count} labels, {skipped} skipped)"

    body_lines = [
        f"Birthday labels for {month_name} {year} are attached.",
        f"",
        f"Labels generated:     {label_count}",
        f"Skipped (no address): {skipped}",
        f"",
        f"Print on Avery 5160 label sheets (30 labels per sheet).",
        f"Open the PDF and print — no mail merge needed.",
    ]
    if no_address_policies:
        body_lines += [
            f"",
            f"--- SKIPPED CUSTOMERS (missing mailing address) ---",
            f"These customers have birthdays in {month_name} but no address on file.",
            f"Fix by re-importing the carrier file after correcting their address.",
            f"",
        ]
        for p in no_address_policies:
            name = p.full_name or f"{p.first_name} {p.last_name}"
            dob  = p.dob.strftime('%-m/%-d/%Y') if p.dob else "unknown"
            body_lines.append(f"  - {name} ({p.carrier}) — DOB: {dob}")

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        plain_text_content="\n".join(body_lines),
    )

    encoded    = base64.b64encode(pdf_bytes).decode()
    filename   = f"birthday_labels_{month_name.lower()}_{year}.pdf"
    attachment = Attachment(
        FileContent(encoded),
        FileName(filename),
        FileType("application/pdf"),
        Disposition("attachment"),
    )
    message.attachment = attachment

    sg = SendGridAPIClient(api_key)
    sg.send(message)


@labels_bp.route("/birthday-labels")
@login_required
def labels_page():
    today          = date.today()
    selected_month = request.args.get("month", type=int, default=today.month)
    if not (1 <= selected_month <= 12):
        selected_month = today.month
    policies       = _get_birthday_policies(selected_month, current_user.id)
    no_address     = _policies_missing_address(selected_month, current_user.id)
    monthly_counts = {m: len(_get_birthday_policies(m, current_user.id)) for m in range(1, 13)}
    return render_template("labels.html",
        selected_month=selected_month,
        month_name=MONTH_NAMES[selected_month - 1],
        month_names=MONTH_NAMES,
        policies=policies,
        no_address=no_address,
        monthly_counts=monthly_counts,
        today=today)


@labels_bp.route("/birthday-labels/download")
@login_required
def labels_download():
    month = request.args.get("month", type=int)
    if not month or not (1 <= month <= 12):
        flash("Invalid month.", "error")
        return redirect(url_for("labels.labels_page"))

    policies   = _get_birthday_policies(month, current_user.id)
    month_name = MONTH_NAMES[month - 1]

    if not policies:
        flash(f"No customers with addresses have birthdays in {month_name}.", "warning")
        return redirect(url_for("labels.labels_page", month=month))

    pdf_bytes = _build_pdf(policies, month_name)
    filename  = f"birthday_labels_{month_name.lower()}_{date.today().year}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
