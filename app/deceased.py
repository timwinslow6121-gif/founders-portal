"""Recording that a member has died, from carrier files or an agent.

Suppression is person-level and immediate; TERMINATION is carrier-scoped. A
carrier reporting a death terms only its own policies — death propagates
SSA -> CMS -> carriers, so the other carriers report it themselves within a
month or two, and auto-terming their policies front-runs data already coming
while taking on false-positive risk. Ancillary products (hospital indemnity,
DVH) may pay a benefit or convert rather than simply ending, so terming them
automatically would encode a guess.

Manual marking passes no carrier and therefore terms nothing.
"""
from datetime import date
from typing import Optional

from app.customer_provenance import set_carrier_value
from app.models import Policy


def death_date_from_uhc_fact(fact) -> Optional[date]:
    """The date of death a UHC commission row implies, or None.

    UHC states it in plain English in its Term Reason column ("Death"), so no
    code lookup is needed. Every other value there -- "Member Termination",
    "Enrollment in Another Plan", "Star Plan Change" -- is NOT a death.
    """
    if (getattr(fact, "term_reason_raw", "") or "").strip().lower() != "death":
        return None
    return getattr(fact, "term_date", None)


def apply_death(customer, when, source, agency_id, carrier=None) -> bool:
    """Mark `customer` deceased and, when `carrier` is given, term that carrier's
    active policies for them. Returns True if the mark was written.

    Writes through set_carrier_value, so the never-erase rule and the trust
    ladder apply: a None date refuses, and an agent's mark outranks a carrier's.
    """
    if customer is None:
        return False
    wrote = set_carrier_value(customer, "deceased_date", when, source)
    if not wrote:
        return False
    if carrier:
        for pol in Policy.query.filter_by(agency_id=agency_id, carrier=carrier,
                                          customer_id=customer.id,
                                          status="active").all():
            pol.status = "termed"
            if pol.term_date is None:
                pol.term_date = when
            if not pol.term_reason_raw:
                pol.term_reason_raw = "Death"
    return True
