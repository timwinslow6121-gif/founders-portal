"""Resolve a carrier writing-ID to a portal agent (book ownership).

The Founders override is a COMMISSION classification (same writing-id, same agent;
split_breakdown keeps the money), never a separate book attribution — so it creates
no ambiguity here. The only ambiguity is a map-integrity collision: the same id_value
under two different agents' contract rows for one carrier (a seeding typo). We refuse
to guess in that case and return None so the policy surfaces in the Unattributed view.
"""
from app.extensions import db
from app.models import AgentCarrierContract


def resolve_writing_agent(carrier, writing_id, agency_id):
    wid = (writing_id or "").strip()
    if not wid:
        return None
    rows = (AgentCarrierContract.query
            .filter_by(carrier=carrier, id_value=wid, agency_id=agency_id)
            .all())
    agent_ids = {r.agent_id for r in rows}
    if len(agent_ids) == 1:
        return agent_ids.pop()
    return None  # 0 matches or a collision → don't guess
