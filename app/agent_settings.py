"""
Agent Settings Blueprint
Admin-only page for configuring per-agent carrier contracts,
commission splits, and agent IDs.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required
from app.extensions import db
from app.models import User, AgentCarrierContract

settings_bp = Blueprint("settings", __name__)

CARRIERS = ["UHC", "Humana", "Aetna", "BCBS", "Devoted",
            "Healthspring", "Medico", "GTL"]

ID_TYPES = ["NPN", "writing_number", "agent_code"]


@settings_bp.route("/admin/agent-settings")
@login_required
def settings_index():
    if not current_user.is_admin:
        abort(403)

    agents = (User.query
              .filter(User.email != "admin@foundersinsuranceagency.com")
              .order_by(User.name).all())

    # Build per-agent contract map
    agency_id = current_user.agency_id
    agent_data = []
    for agent in agents:
        contracts = {c.carrier: c for c in
                     AgentCarrierContract.query.filter_by(
                         agent_id=agent.id, agency_id=agency_id).all()}
        # Fill in any missing carriers
        for carrier in CARRIERS:
            if carrier not in contracts:
                contracts[carrier] = AgentCarrierContract(
                    agency_id=agency_id,
                    agent_id=agent.id, carrier=carrier,
                    is_active=False, split_rate=0.55,
                    id_type="NPN", id_value=""
                )
        agent_data.append({"agent": agent, "contracts": contracts})

    return render_template("agent_settings.html",
        agent_data=agent_data,
        carriers=CARRIERS,
        id_types=ID_TYPES,
    )


@settings_bp.route("/admin/agent-settings/<int:agent_id>", methods=["GET","POST"])
@login_required
def settings_agent(agent_id):
    if not current_user.is_admin:
        abort(403)

    agent = User.query.get_or_404(agent_id)

    if request.method == "POST":
        split_rate = float(request.form.get("split_rate", 55)) / 100.0

        for carrier in CARRIERS:
            is_active = request.form.get(f"active_{carrier}") == "on"
            id_type   = request.form.get(f"id_type_{carrier}", "NPN")
            id_value  = request.form.get(f"id_value_{carrier}", "").strip()

            contract = AgentCarrierContract.query.filter_by(
                agent_id=agent.id, carrier=carrier, agency_id=current_user.agency_id
            ).first()

            if contract:
                contract.is_active  = is_active
                contract.split_rate = split_rate
                contract.id_type    = id_type
                contract.id_value   = id_value
            else:
                contract = AgentCarrierContract(
                    agency_id  = current_user.agency_id,
                    agent_id   = agent.id,
                    carrier    = carrier,
                    is_active  = is_active,
                    split_rate = split_rate,
                    id_type    = id_type,
                    id_value   = id_value,
                )
                db.session.add(contract)

        db.session.commit()
        flash(f"✓ Settings saved for {agent.display_name}.", "success")
        return redirect(url_for("settings.settings_agent", agent_id=agent_id))

    contracts = {c.carrier: c for c in
                 AgentCarrierContract.query.filter_by(
                     agent_id=agent.id, agency_id=current_user.agency_id).all()}
    for carrier in CARRIERS:
        if carrier not in contracts:
            contracts[carrier] = AgentCarrierContract(
                agency_id=current_user.agency_id,
                agent_id=agent.id, carrier=carrier,
                is_active=False, split_rate=0.55,
                id_type="NPN", id_value=""
            )

    # Get split rate from first contract (same for all carriers per agent)
    split_pct = round(list(contracts.values())[0].split_rate * 100, 1)

    return render_template("agent_settings_detail.html",
        agent=agent,
        contracts=contracts,
        carriers=CARRIERS,
        id_types=ID_TYPES,
        split_pct=split_pct,
    )
