"""
Agent Settings Blueprint
Admin-only page for configuring per-agent carrier contracts,
commission splits, and agent IDs.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for, abort
from flask_login import current_user, login_required
from app.extensions import db
from app.models import User, AgentCarrierContract, Pharmacy
from app.audit import log_event

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

    pharmacies = Pharmacy.query.filter_by(agency_id=agency_id).order_by(Pharmacy.name).all()

    return render_template("agent_settings.html",
        agent_data=agent_data,
        carriers=CARRIERS,
        id_types=ID_TYPES,
        pharmacies=pharmacies,
    )


@settings_bp.route("/admin/agent-settings/<int:agent_id>", methods=["GET","POST"])
@login_required
def settings_agent(agent_id):
    if not current_user.is_admin:
        abort(403)

    agent = User.query.get_or_404(agent_id)

    if request.method == "POST":
        split_rate = float(request.form.get("split_rate", 55)) / 100.0

        # Pharmacy location assignments (many-to-many via pharmacy_agents)
        pharmacy_ids = request.form.getlist("pharmacy_ids", type=int)
        assigned_pharmacies = Pharmacy.query.filter(
            Pharmacy.id.in_(pharmacy_ids),
            Pharmacy.agency_id == current_user.agency_id,
        ).all() if pharmacy_ids else []
        # Update pharmacy.agents lists — add agent where checked, remove where unchecked
        all_pharmacies = Pharmacy.query.filter_by(agency_id=current_user.agency_id).all()
        for pharm in all_pharmacies:
            if pharm in assigned_pharmacies and agent not in pharm.agents:
                pharm.agents.append(agent)
            elif pharm not in assigned_pharmacies and agent in pharm.agents:
                pharm.agents.remove(agent)

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

        log_event("agent_role_change", category="admin", severity="warning",
                  detail=f"updated settings/contracts for {agent.display_name} (#{agent.id})")
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

    pharmacies = Pharmacy.query.filter_by(
        agency_id=current_user.agency_id
    ).order_by(Pharmacy.name).all()

    return render_template("agent_settings_detail.html",
        agent=agent,
        contracts=contracts,
        carriers=CARRIERS,
        id_types=ID_TYPES,
        split_pct=split_pct,
        pharmacies=pharmacies,
    )
