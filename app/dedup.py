"""No-MBI duplicate detection (spec 2026-06-30). Clusters customers by normalized
full_name and tags each cluster with a corroboration signal. Suggest-only: this
module never writes — it only proposes clusters for human/script review."""
from collections import defaultdict
from dataclasses import dataclass

from app.extensions import db
from app.models import Customer, Policy, CommissionLineItem
from app.integrity import _norm_name


@dataclass
class Cluster:
    keeper_id: int
    member_ids: list
    signal: str = "name_only"


def _keeper_score(c):
    """Most-complete real row wins: non-stub + has mbi + has dob + has name."""
    return (0 if c.stub else 1, 1 if c.mbi else 0, 1 if c.dob else 0,
            1 if (c.full_name or c.first_name or c.last_name) else 0, c.id * -1)


def _shared_carrier_ids(member_ids, agency_id):
    """carrier_member_ids that appear on the cluster's commission line items + policies."""
    ids = set()
    li = (CommissionLineItem.query
          .filter(CommissionLineItem.agency_id == agency_id,
                  CommissionLineItem.customer_id.in_(member_ids),
                  CommissionLineItem.carrier_member_id.isnot(None))
          .with_entities(CommissionLineItem.carrier, CommissionLineItem.carrier_member_id).all())
    ids.update((c, v) for c, v in li if v)
    pol = (Policy.query
           .filter(Policy.agency_id == agency_id,
                   Policy.customer_id.in_(member_ids))
           .with_entities(Policy.carrier, Policy.member_id).all())
    ids.update((c, v) for c, v in pol if v)
    return ids


def cluster_signal(rows, agency_id):
    """Return the merge signal for a set of same-name Customer rows."""
    dobs = {r.dob for r in rows if r.dob is not None}
    mbis = {r.mbi for r in rows if r.mbi}
    if len(dobs) > 1 or len(mbis) > 1:
        return "conflict"
    # >1 row carrying the SAME non-null dob => shared dob.
    if sum(1 for r in rows if r.dob is not None) > 1:
        return "dob_match"
    # A shared carrier id corroborates only if >1 row actually carries it.
    per_row = defaultdict(set)
    for r in rows:
        for c, v in _shared_carrier_ids([r.id], agency_id):
            per_row[(c, v)].add(r.id)
    if any(len(who) > 1 for who in per_row.values()):
        return "shared_id"
    return "name_only"


def count_no_mbi_clusters(agency_id):
    """Cheap count of merge-suggestion clusters for the nav badge. Loads only
    name + dob columns and groups in memory — NO per-row carrier-id signal queries
    (the expensive part of find_no_mbi_clusters), so it is safe to call on every
    page render. Matches find_no_mbi_clusters' DOB-aware splitting so the badge count
    equals the number of clusters actually shown."""
    rows = (Customer.query
            .filter(Customer.agency_id == agency_id)
            .with_entities(Customer.full_name, Customer.first_name,
                           Customer.last_name, Customer.dob)
            .all())
    by_name = defaultdict(list)
    for full, first, last, dob in rows:
        name = full or f"{first or ''} {last or ''}".strip()
        key = _norm_name(name)
        if key:
            by_name[key].append(dob)
    total = 0
    for dobs in by_name.values():
        if len(dobs) < 2:
            continue
        distinct = {d for d in dobs if d is not None}
        if len(distinct) <= 1:
            total += 1                       # one candidate for this name
        else:
            # one candidate per distinct dob that has >1 row carrying it
            per = defaultdict(int)
            for d in dobs:
                if d is not None:
                    per[d] += 1
            total += sum(1 for n in per.values() if n > 1)
    return total


def _split_name_group_by_dob(group):
    """Given same-name Customer rows, return the sub-groups that are real merge
    candidates. DOB-aware (BOB dobs are credible → different present dobs = different
    people, not a dup):
      - 0 or 1 distinct non-null dob in the group → the WHOLE group is one candidate
        (the normal case: same dob, or a null-dob stub joining the single real dob).
      - 2+ distinct non-null dobs → each distinct dob is its OWN sub-group (only the
        rows carrying THAT dob). A null-dob row is ambiguous here (could belong to
        either) → it is left OUT of every sub-group, for human judgment.
    Only sub-groups with >1 row are returned (a lone row is not a suggestion)."""
    dobs = {c.dob for c in group if c.dob is not None}
    if len(dobs) <= 1:
        return [group]                       # unchanged single-candidate behavior
    subs = defaultdict(list)
    for c in group:
        if c.dob is not None:                # null-dob rows dropped (ambiguous)
            subs[c.dob].append(c)
    return [sub for sub in subs.values() if len(sub) > 1]


def find_no_mbi_clusters(agency_id):
    """Cluster customers by normalized full_name, then split each name-group by DOB
    (see _split_name_group_by_dob); return Clusters of size > 1. Includes stubs and
    NULL-dob rows, but same-name rows with DIFFERENT present dobs are treated as
    DIFFERENT people and do NOT surface as a merge suggestion."""
    rows = (Customer.query
            .filter(Customer.agency_id == agency_id)
            .all())
    by_name = defaultdict(list)
    for c in rows:
        name = c.full_name or f"{c.first_name} {c.last_name}".strip()
        key = _norm_name(name)
        if key:
            by_name[key].append(c)
    clusters = []
    for key, group in by_name.items():
        if len(group) < 2:
            continue
        for sub in _split_name_group_by_dob(group):
            if len(sub) < 2:
                continue
            keeper = max(sub, key=_keeper_score)
            clusters.append(Cluster(
                keeper_id=keeper.id,
                member_ids=[c.id for c in sub],
                signal=cluster_signal(sub, agency_id),
            ))
    return clusters
