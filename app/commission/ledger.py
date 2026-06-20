"""
app/commission/ledger.py

R1 — Commission ledger completeness. Per-carrier *extractors* that mirror EVERY
amount-bearing row of a commission file into CommissionLineItem rows (the "money
facts" layer). Unlike app/commission/normalizers.py, extractors do NOT collapse
paired rows — the Founders-override / Service-Fee row is kept so that
"Σ raw_amount = Σ agent_payout + Σ founders_keep" is provable.

split_breakdown() is the single derivation seam: agent_payout / founders_keep
are always derived from raw_amount + split_rate + classification, never stored.

See docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md.
"""
import contextvars
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

# Set by the upload path to the original uploaded filename, so multi-batch carriers
# (Healthspring) can derive a per-file token from it without threading it through
# every extractor/normalizer signature. Thread-safe under gthread workers.
current_upload_filename = contextvars.ContextVar("current_upload_filename", default="")

# Classification constants (plain strings; no DB enum, forward-compat).
AGENT_COMMISSION = "agent_commission"
FOUNDERS_OVERRIDE = "founders_override"
HRA_BONUS = "hra_bonus"
CHARGEBACK = "chargeback"
NEEDS_MANUAL_REVIEW = "needs_manual_review"  # UHC HA-bonus / DVH / garbage rows AJ handles by hand


@dataclass
class LineItemDraft:
    """In-memory line item before it is persisted as a CommissionLineItem.
    One per amount-bearing sheet row (paired rows NOT collapsed)."""
    carrier: str
    source_ref: str
    raw_amount: float
    classification: str
    split_rate: Optional[float] = None
    payment_type: Optional[str] = None
    member_name: str = ""
    mbi: Optional[str] = None
    carrier_member_id: Optional[str] = None
    writing_agent_raw: str = ""
    effective_date: Optional[date] = None
    term_date: Optional[date] = None


def split_breakdown(line) -> Tuple[float, float]:
    """Derive (agent_payout, founders_keep) from a line item / draft.

    - founders_override: agent gets nothing; Founders keeps the whole amount.
    - everything else (agent_commission / hra_bonus / chargeback): the amount is
      pre-split; agent_payout = raw_amount * split_rate, Founders keeps the rest.
      A None split_rate (no contract) yields payout 0 / keep = raw_amount.
    The two ALWAYS sum back to raw_amount (balance holds by construction)."""
    raw = line.raw_amount or 0.0
    if line.classification == FOUNDERS_OVERRIDE:
        return 0.0, raw
    rate = line.split_rate
    if rate is None:
        return 0.0, raw
    payout = raw * rate
    return payout, raw - payout


from app.commission.payments import _parse_date
from app.extensions import db
from app.models import CommissionLineItem


def _to_float(v):
    s = str(v).replace("$", "").replace(",", "").strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):   # accounting-style negative
        s = s[1:-1].strip()
        neg = True
    try:
        n = float(s or 0)
    except (ValueError, TypeError):
        return 0.0
    return -n if neg else n


def _hs_classify(desc, amount):
    d = str(desc or "").lower()
    if "service fee" in d:
        return FOUNDERS_OVERRIDE
    if amount < 0:
        return CHARGEBACK
    return AGENT_COMMISSION


def _healthspring_filetoken(sheets):
    """Healthspring ships MULTIPLE statement-batch files per month (NN_NNNNNN.xlsx).
    The files carry NO batch id in their content, so the per-file token comes from
    the original FILENAME, provided by the upload path via current_upload_filename
    (a ContextVar — keeps extractor/normalizer signatures uniform and is thread-safe
    under gthread workers). Token = the 'NN_NNNNNN' batch stem, e.g. 'b68_486966'.
    Falls back to 'batch' (single-batch / unknown filename) so behaviour is safe."""
    import re, os
    fname = str(current_upload_filename.get() or "")
    stem = os.path.splitext(os.path.basename(fname))[0]
    m = re.match(r"\d+_\d+", stem)
    return f"b{m.group(0)}" if m else "batch"


def extract_lineitems_healthspring(sheets, split_lookup) -> List[LineItemDraft]:
    """One LineItemDraft per Detail row (paired rows NOT collapsed).
    split_lookup(writing_agent_raw) -> Optional[float] split rate for that agent.
    Healthspring is multi-batch: source_ref carries a per-file batch token so
    re-uploading one batch replaces only its rows (file-scoped replace)."""
    rows = sheets.get("Detail", [])
    filetoken = _healthspring_filetoken(sheets)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        amount = _to_float(row[7])
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        classification = _hs_classify(desc, amount)
        writing = str(row[3] or "").strip()
        out.append(LineItemDraft(
            carrier="Healthspring",
            source_ref=f"healthspring::{filetoken}::Detail::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=None if classification == FOUNDERS_OVERRIDE else split_lookup(writing),
            payment_type=str(row[0] or "").strip().lower() or None,
            member_name=str(row[10] or "").strip(),
            mbi=str(row[9] or "").strip() or None,
            carrier_member_id=member_id or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_healthspring(sheets) -> float:
    """Independent re-sum of EVERY Detail-row Payment Amount (col 7). Compared
    against the line-item sum to catch a dropped/mis-summed row."""
    rows = sheets.get("Detail", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        total += _to_float(row[7])
    return total


def _bcbs_filetoken(sheets):
    """BCBS ships ONE file per agent. The per-file token is the agent's BCBS
    'P Number' (Agent #, column A) so each agent's file gets a distinct
    source_ref prefix and a re-upload of one agent's file replaces only that
    agent's rows (never another agent's). Falls back to 'unknown' if absent."""
    rows = sheets.get("Sheet1", [])
    for row in rows[1:]:
        if any(row) and len(row) > 0:
            pnum = str(row[0] or "").strip()
            if pnum:
                return f"p{pnum}"
    return "punknown"


def extract_lineitems_bcbs(sheets, split_lookup) -> List[LineItemDraft]:
    rows = sheets.get("Sheet1", [])
    filetoken = _bcbs_filetoken(sheets)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 14:
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row
            continue
        amount = _to_float(row[14])            # Commission column, NOT Billed
        gt = str(row[2] or "").upper().strip()
        classification = CHARGEBACK if (amount < 0 or gt == "ADJUSTMENT") else AGENT_COMMISSION
        writing = str(row[1] or "").strip()
        out.append(LineItemDraft(
            carrier="BCBS",
            source_ref=f"bcbs::{filetoken}::Sheet1::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=gt.lower() or None,
            member_name=name,
            mbi=None,
            carrier_member_id=customer_no,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
        ))
    return out


def money_rows_total_bcbs(sheets) -> float:
    rows = sheets.get("Sheet1", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 14:
            continue
        if not str(row[4] or "").strip() or not str(row[5] or "").strip():
            continue
        total += _to_float(row[14])
    return total


def extract_lineitems_aetna(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    first = next(iter(sheets.values()))
    out = []
    for idx, row in enumerate(first[1:], start=1):
        if not any(row) or len(row) < 21:
            continue
        name = str(row[4] or "").strip()
        if not name:
            continue
        amount = _to_float(row[20])
        classification = CHARGEBACK if amount < 0 else AGENT_COMMISSION
        writing = str(row[16] or "").strip()
        out.append(LineItemDraft(
            carrier="Aetna",
            source_ref=f"aetna::0::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[6] or "").strip().lower() or None,
            member_name=name,
            mbi=str(row[1] or "").strip() or None,
            carrier_member_id=str(row[2] or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_aetna(sheets) -> float:
    if not sheets:
        return 0.0
    first = next(iter(sheets.values()))
    total = 0.0
    for row in first[1:]:
        if not any(row) or len(row) < 21:
            continue
        if not str(row[4] or "").strip():
            continue
        total += _to_float(row[20])
    return total


def _devoted_sheet_rows(sheets, sheet_name):
    return sheets.get(sheet_name, [])


def _devoted_format(sheets):
    """Devoted ships two file shapes. Detect which by sheet names:
      - "agency"    : the agency book-of-business (Total/Override/Agent Portion/HRA)
      - "statement" : a per-agent statement (Summary/Detail/Misc)
    Raises ValueError on an unrecognized shape (fail loud, never silently 0 rows)."""
    if "Agent Portion" in sheets:
        return "agency"
    if "Detail" in sheets and "Misc" in sheets:
        return "statement"
    raise ValueError(
        f"Unrecognized Devoted file shape; sheets={list(sheets)}. "
        "Expected agency (Agent Portion) or statement (Detail+Misc).")


def _devoted_filetoken(sheets):
    """Stable per-file token so the two Devoted files coexist under one statement.
      - agency    → "agency"
      - statement → "npn" + the Agent NPN from the Detail sheet (col 1)
    """
    fmt = _devoted_format(sheets)
    if fmt == "agency":
        return "agency"
    detail = sheets.get("Detail", [])
    npn = ""
    for row in detail[1:]:
        if any(row) and len(row) > 1:
            npn = str(row[1] or "").strip()
            if npn:
                break
    return f"npn{npn}" if npn else "npn_unknown"


def _extract_devoted_agency(sheets, filetoken, split_lookup) -> List[LineItemDraft]:
    out = []
    # Agent Portion → agent_commission / chargeback
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Agent Portion")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Agent Portion::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    # Override → founders_override (positive) / chargeback (negative clawback).
    # Either way no agent split: split_rate=None means Founders keeps/absorbs all.
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Override")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Override::{idx}",
            raw_amount=amount,
            classification=CHARGEBACK if amount < 0 else FOUNDERS_OVERRIDE,
            split_rate=None,
            payment_type="override",
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=str(row[2] or "").strip(),
        ))
    # HRA → hra_bonus (split applies)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "HRA")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::HRA::{idx}",
            raw_amount=amt,
            classification=HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA Bonus",
            writing_agent_raw=rep,
        ))
    return out


def _extract_devoted_statement(sheets, filetoken, split_lookup) -> List[LineItemDraft]:
    """Rebekah per-agent statement: Detail (member commissions) + Misc (HRA, often
    clawbacks). Summary is NOT extracted (its Balance is a prior-period carryforward
    that would double-count). Detail columns match the agency Agent Portion layout."""
    out = []
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Detail")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Detail::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Misc")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::{filetoken}::Misc::{idx}",
            raw_amount=amt,
            classification=CHARGEBACK if amt < 0 else HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA",
            writing_agent_raw=rep,
        ))
    return out


def extract_lineitems_devoted(sheets, split_lookup) -> List[LineItemDraft]:
    fmt = _devoted_format(sheets)
    filetoken = _devoted_filetoken(sheets)
    if fmt == "statement":
        return _extract_devoted_statement(sheets, filetoken, split_lookup)
    return _extract_devoted_agency(sheets, filetoken, split_lookup)


def money_rows_total_devoted(sheets) -> float:
    fmt = _devoted_format(sheets)
    total = 0.0
    if fmt == "statement":
        for row in _devoted_sheet_rows(sheets, "Detail")[1:]:
            if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
                continue
            total += _to_float(row[17])
        for row in _devoted_sheet_rows(sheets, "Misc")[1:]:
            if not any(row) or len(row) <= 3:
                continue
            if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
                continue
            total += _to_float(row[2])
        return total
    for row in _devoted_sheet_rows(sheets, "Agent Portion")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "Override")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "HRA")[1:]:
        if not any(row) or len(row) <= 3:
            continue
        if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
            continue
        total += _to_float(row[2])
    return total


def _humana_cols(rows):
    header = rows[0]
    return {h: i for i, h in enumerate(header)}


def extract_lineitems_humana(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return []
    col = _humana_cols(rows)

    def g(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        umid = str(g(row, "UMID") or "").strip()
        grp = str(g(row, "GrpName") or "").strip()
        if not umid and not grp:
            continue
        amount = _to_float(g(row, "PaidAmount"))
        txn = str(g(row, "TxnTypeCd") or "").upper().strip()
        if txn == "HRAP":
            classification = HRA_BONUS
        elif amount < 0:
            classification = CHARGEBACK
        else:
            classification = AGENT_COMMISSION
        writing = str(g(row, "WaName") or "").strip()
        out.append(LineItemDraft(
            carrier="Humana",
            source_ref=f"humana::{name}::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=txn.lower() or None,
            member_name=grp,
            mbi=umid or None,
            carrier_member_id=str(g(row, "PID") or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(g(row, "EffDate")),
        ))
    return out


def money_rows_total_humana(sheets) -> float:
    if not sheets:
        return 0.0
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return 0.0
    col = _humana_cols(rows)
    pi = col.get("PaidAmount")
    ui = col.get("UMID")
    gi = col.get("GrpName")
    total = 0.0
    for row in rows[1:]:
        if not any(row):
            continue
        umid = str(row[ui] or "").strip() if ui is not None and ui < len(row) else ""
        grp = str(row[gi] or "").strip() if gi is not None and gi < len(row) else ""
        if not umid and not grp:
            continue
        if pi is not None and pi < len(row):
            total += _to_float(row[pi])
    return total


# ──────────────────────────────────────────────────────────────────────────
# UHC — RAW carrier statement parser (R4, ~98% auto). Ingests the raw
# `statement-NNNN-YYYYMMDD.xlsx` (sheet "Commission Transactions"), auto-splits
# the routine rows, and QUARANTINES the genuinely-hard few for AJ. Saves AJ from
# hand-splitting ~3,100 lines/month (only ~2% need manual review now).
#
# THE MODEL (confirmed with Tim + VALIDATED against AJ's per-agent files,
# 2026-06-11): every payment is ONE of two money types —
#   • RENEWAL          → agent_commission, SPLITS agent%/Founders% (split_rate)
#   • FOUNDERS OVERRIDE → founders_override, 100% Founders, NO split (rate=None)
# The override is a flat $4.59/mo on every override-bearing family (MA + Part D).
# The raw file emits the pair as TWO lines ($28.92 + $4.59) OR ONE combined line
# ($33.51 = 28.92+4.59 for HMO; $30.68 = 26.09+4.59 for non-SNP PPO) — combined
# lines are DECOMPOSED. Med-Supp (AARPMODMEDSUP) pays premium-based amounts as a
# PAIRED renewal+override per member (override = the smaller line), only for the
# LOA agents who write it. HA payments ($50) → split, no override. PARTD "dust"
# (<$1, e.g. $0.26) → quarantine (AJ drops these). "New" enrollments (complex
# cols L/T/AA/AB) → quarantine pending deeper analysis.
#
# VALIDATION (the real invariant): line items per agent sum EXACTLY to the raw
# file's per-agent total — every dollar reclassified, none lost/created (all 11
# agents balance to the penny; see verify_statement_balance completeness check).
# Tim's renewal-only reconciles to his AJ file ($6,549.05 exact). NOTE: AJ's
# per-agent files are inconsistent (some keep $33.51 combined, some pre-split to
# $28.92+$4.59), so "match AJ's renewal sum" is NOT a clean target — the per-agent
# completeness balance is the ground truth. Spec:
# docs/superpowers/specs/2026-06-11-uhc-raw-parser-design.md
# ──────────────────────────────────────────────────────────────────────────
_UHC_SHEET = "Commission Transactions"
# RAW file columns (0-indexed, header=row 0), verified against real statement:
_UHC_WRITING_ID = 4  # Writing Agent ID — the STABLE per-agent key. Attribute by THIS.
_UHC_AGENT = 5      # Writing Agent Name — UNRELIABLE: Rebekah (and others) write as
                    # "FOUNDERS INSURANCE AGENCY, LLC", so name attribution is wrong.
_UHC_MEMBER = 7     # Member Name
_UHC_MBI = 8        # MedicareID
_UHC_PLANTYPE = 12  # Plan Type (MAPD/DSNP/CSNP/MA = MA family; PARTD/AARP... = other)
_UHC_ACTION = 19    # Commission Action
_UHC_AMOUNT = 23    # Commission ($)
_UHC_EFFDATE = 11

# UHC per-member money constants (monthly), confirmed with Tim + the data.
# Two money types only: a "renewal" (SPLITS agent%/Founders%) and a fixed
# "Founders override" (100% Founders, NO split). The override is a flat $4.59 on
# every override-bearing plan family (MA AND Part D). The raw file emits the pair
# as two lines OR one combined line; combined lines are decomposed.
_UHC_OVERRIDE = 4.59    # ~$55/yr ÷ 12 — the Founders override (no split), all families
_UHC_NEW_OVERRIDE = 125.0   # flat 'New' Founders override fee (100% Founders, no split)
_UHC_PARTD_OVERRIDE = 0.26  # fixed monthly Founders override on a Part D plan renewal
                            # (no split — 100% Founders), per Tim. NOT dust.
_UHC_RENEWAL_HMO = 28.92   # standard HMO MA renewal ($347/yr ÷ 12) — splits
_UHC_RENEWAL_PPO = 26.09   # non-SNP PPO renewal (different comp) — splits
_UHC_COMBINED_HMO = round(_UHC_RENEWAL_HMO + _UHC_OVERRIDE, 2)  # 33.51 = 28.92+4.59
_UHC_COMBINED_PPO = round(_UHC_RENEWAL_PPO + _UHC_OVERRIDE, 2)  # 30.68 = 26.09+4.59
# (renewal, combined) pairs to test for decomposition, in match order.
_UHC_COMBINED_PAIRS = [(_UHC_RENEWAL_HMO, _UHC_COMBINED_HMO),
                       (_UHC_RENEWAL_PPO, _UHC_COMBINED_PPO)]
# Plan families that carry the $4.59 Founders override (MA + Part D).
_UHC_OVERRIDE_FAMILY = {"MAPD", "DSNP", "CSNP", "MA", "PARTD"}
_UHC_MEDSUPP = {"AARPMODMEDSUP"}   # premium-based; renewal+override PAIRED per member
# Med-Supp pairing applies to ANY agent who writes it — the smaller line of a
# per-member pair is the Founders override (structural, not agent-specific). A
# lone Med-Supp line (no pair) can't be decomposed → quarantine. (Was previously
# gated to a hardcoded LOA agent list, which dropped Anjana/Brian Med-Supp pairs
# into quarantine — the June 2026 "overrides not caught" bug.)
_CENT = 0.005  # match tolerance for the fixed amounts


def _uhc_rows(sheets):
    """The raw UHC data lives in the 'Commission Transactions' sheet. Skip
    'Commission Summary' (payment totals) and 'Held Transactions' (not yet paid)."""
    rows = sheets.get(_UHC_SHEET)
    if rows is None:
        rows = next(iter(sheets.values())) if sheets else []
    return rows or []


def _uhc_writing_id_map(agency_id):
    """Writing Agent ID (UHC col 4) -> portal agent display name, from each agent's
    UHC AgentCarrierContract.id_value. This is the AUTHORITATIVE attribution: the
    name column is unusable (Rebekah & others write as 'FOUNDERS INSURANCE AGENCY,
    LLC'). Returns {} if contracts aren't seeded (extractor then falls back to name)."""
    from app.models import AgentCarrierContract, User
    out = {}
    q = AgentCarrierContract.query.filter_by(carrier="UHC")
    if agency_id is not None:
        q = q.filter_by(agency_id=agency_id)
    for c in q.all():
        wid = (c.id_value or "").strip()
        if not wid:
            continue
        u = User.query.get(c.agent_id)
        if u:
            out[wid] = u.name
    return out


def _near(a, b):
    return abs(a - b) < _CENT


import re

# UHC HA (HRA) rows carry no member column; the member is named inside the action
# string: "HA payment for agent ID 6337213 for member JEANETTE CATHCART MBI *****8VD98 ...".
_UHC_HA_MEMBER_RE = re.compile(r"for member (.+?)\s+MBI\b", re.IGNORECASE)

# DVH Manual Payment rows also carry no member column; the member + writing agent ID
# are inside the action string:
#   "New, DVH Manual Payment, ... written by 6435806 for JANA BENSON, State: NC, ...".
_UHC_DVH_MEMBER_RE = re.compile(r"\bfor ([A-Za-z][A-Za-z .,'-]+?)\s*,\s*State\b", re.IGNORECASE)
_UHC_DVH_AGENTID_RE = re.compile(r"written by\s+(\d+)", re.IGNORECASE)


def _uhc_ha_member(action):
    """Extract the member name from a UHC HA-payment action string, else ''."""
    m = _UHC_HA_MEMBER_RE.search(str(action or ""))
    return m.group(1).strip() if m else ""


def _uhc_dvh_member(action):
    """Extract the member name from a DVH Manual Payment action string, else ''.
    e.g. '... for JANA BENSON, State: NC, ...' -> 'JANA BENSON'."""
    m = _UHC_DVH_MEMBER_RE.search(str(action or ""))
    return m.group(1).strip() if m else ""


def _uhc_dvh_agent_id(action):
    """Extract the writing-agent ID from a DVH action string ('written by 6435806'), else ''."""
    m = _UHC_DVH_AGENTID_RE.search(str(action or ""))
    return m.group(1).strip() if m else ""


def _uhc_medsupp_overrides(rows, writing_for):
    """Med-Supp pays per-member as TWO lines (premium-based): a larger renewal
    (splits) + a smaller Founders override (no split). Pre-pass to identify, per
    (member, agent), which Med-Supp amount is the override (the SMALLER of the
    pair) so the main loop can classify each line. Applies to ANY agent who writes
    Med-Supp — the split is structural (smaller-of-pair = override), not
    agent-specific. `writing_for(row)` resolves the agent (by Writing Agent ID).
    Returns (overrides, paired_members):
      - overrides:       set of (member, AGENT_UPPER, amount) OVERRIDE tuples
      - paired_members:  set of (member, AGENT_UPPER) that have a 2+ line pair
    both keyed on the SAME resolved writing the main loop uses. A lone Med-Supp
    line is in NEITHER set → the main loop quarantines it (can't decompose one
    line into renewal+override)."""
    by_member = defaultdict(list)
    for row in rows[1:]:
        if not any(row) or len(row) <= _UHC_AMOUNT:
            continue
        plan = str(row[_UHC_PLANTYPE] or "").strip().upper()
        if plan not in _UHC_MEDSUPP:
            continue
        writing = writing_for(row).upper()
        amt = round(_to_float(row[_UHC_AMOUNT]), 2)
        if amt == 0:
            continue
        member = str(row[_UHC_MEMBER] or "").strip()
        by_member[(member, writing)].append(amt)
    overrides = set()
    paired_members = set()
    for (member, writing), amts in by_member.items():
        if len(amts) >= 2:
            paired_members.add((member, writing))
            smaller = min(amts, key=abs)   # the override is the smaller line
            overrides.add((member, writing, smaller))
    return overrides, paired_members


def extract_lineitems_uhc(sheets, split_lookup, writing_id_to_name=None,
                          agency_id=None) -> List[LineItemDraft]:
    rows = _uhc_rows(sheets)
    if not rows:
        return []
    # Attribute by Writing Agent ID (col 4), NOT name (col 5) — the name is the
    # agency for Rebekah & others. Map ID -> portal name; fall back to the raw name
    # only when an ID isn't seeded on a contract. Build from contracts when not
    # supplied (guarded: tests without an app context pass an explicit map / get {}).
    if writing_id_to_name is None:
        try:
            writing_id_to_name = _uhc_writing_id_map(agency_id)
        except RuntimeError:
            writing_id_to_name = {}

    def _writing_for(row):
        wid = str(row[_UHC_WRITING_ID] or "").strip() if len(row) > _UHC_WRITING_ID else ""
        return writing_id_to_name.get(wid) or str(row[_UHC_AGENT] or "").strip()

    medsupp_overrides, medsupp_paired_members = _uhc_medsupp_overrides(rows, _writing_for)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= _UHC_AMOUNT:
            continue
        amount = round(_to_float(row[_UHC_AMOUNT]), 2)
        if amount == 0:
            continue
        action = str(row[_UHC_ACTION] or "").strip()
        action_l = action.lower()
        plan = str(row[_UHC_PLANTYPE] or "").strip().upper()
        writing = _writing_for(row)
        member = str(row[_UHC_MEMBER] or "").strip()
        mbi = str(row[_UHC_MBI] or "").strip() or None
        eff = _parse_date(row[_UHC_EFFDATE]) if len(row) > _UHC_EFFDATE else None
        sref = f"uhc::0::{idx}"
        rate = split_lookup(writing)

        def draft(raw, cls, srate, ref, ptype=None, member_name=None):
            return LineItemDraft(
                carrier="UHC", source_ref=ref, raw_amount=raw, classification=cls,
                split_rate=srate, payment_type=(ptype or action_l or None),
                member_name=(member_name if member_name is not None else member),
                mbi=mbi, writing_agent_raw=writing, effective_date=eff)

        # ── HA payment/chargeback ($50): an HRA bonus. No override, but DOES split
        #    agent/Founders. Classify as HRA_BONUS (its own "HRA" recap group), not
        #    a renewal. A negative HA is an HRA clawback → chargeback. The HA rows
        #    carry no member col — the name is embedded in the action string
        #    ("... for member JANE DOE MBI *****1234 ..."), so pull it out for display.
        if action_l.startswith("ha payment") or action_l.startswith("ha chargeback"):
            cls = CHARGEBACK if amount < 0 else HRA_BONUS
            ha_member = _uhc_ha_member(action) or member
            out.append(draft(amount, cls, rate, sref, ptype="hra", member_name=ha_member))
            continue

        is_renewal = "renewal" in action_l
        is_new = "new" in action_l and "chargeback" not in action_l
        in_override_family = plan in _UHC_OVERRIDE_FAMILY

        # ── Flat $125.00 'New' = a 100% Founders override fee (no agent split), per
        #    Tim (June 2026). Appears as a standalone line beside the real New
        #    enrollment commission. (New CHARGEBACKs are excluded — those are still
        #    under review.)
        if is_new and _near(abs(amount), _UHC_NEW_OVERRIDE):
            signed = _UHC_NEW_OVERRIDE if amount >= 0 else -_UHC_NEW_OVERRIDE
            out.append(draft(signed, FOUNDERS_OVERRIDE, None, sref, ptype="new override"))
            continue

        # ── Fixed $0.26 PARTD renewal = Founders override for a Part D plan (per
        #    Tim): 100% Founders, no split. (Was previously quarantined as "dust".)
        if is_renewal and plan == "PARTD" and _near(abs(amount), _UHC_PARTD_OVERRIDE):
            signed = _UHC_PARTD_OVERRIDE if amount >= 0 else -_UHC_PARTD_OVERRIDE
            out.append(draft(signed, FOUNDERS_OVERRIDE, None, sref, ptype="partd override"))
            continue

        # ── Any OTHER sub-threshold PARTD renewal (not 0.26, not 4.59): still
        #    quarantine — unexpected, route to AJ.
        if is_renewal and plan == "PARTD" and abs(amount) < 1.00 \
                and not _near(amount, _UHC_OVERRIDE):
            out.append(draft(amount, NEEDS_MANUAL_REVIEW, None, sref, ptype="partd dust"))
            continue

        # ── MA / Part D renewals: override-aware (the $4.59 / combined logic).
        if is_renewal and in_override_family:
            if _near(amount, _UHC_OVERRIDE):
                out.append(draft(_UHC_OVERRIDE, FOUNDERS_OVERRIDE, None, sref))
                continue
            if _near(amount, -_UHC_OVERRIDE):
                out.append(draft(-_UHC_OVERRIDE, FOUNDERS_OVERRIDE, None, sref))
                continue
            decomposed = False
            for renewal_amt, combined_amt in _UHC_COMBINED_PAIRS:
                if _near(amount, combined_amt):          # e.g. 33.51 or 30.68
                    out.append(draft(renewal_amt, AGENT_COMMISSION, rate, sref + "::r"))
                    out.append(draft(_UHC_OVERRIDE, FOUNDERS_OVERRIDE, None, sref + "::o"))
                    decomposed = True; break
                if _near(amount, -combined_amt):
                    out.append(draft(-renewal_amt, CHARGEBACK, rate, sref + "::r"))
                    out.append(draft(-_UHC_OVERRIDE, FOUNDERS_OVERRIDE, None, sref + "::o"))
                    decomposed = True; break
            if decomposed:
                continue
            # any other amount = a plain renewal (incl. partial-month proration).
            cls = CHARGEBACK if amount < 0 else AGENT_COMMISSION
            out.append(draft(amount, cls, rate, sref))
            continue

        # ── Med-Supp renewals (paired per member; ANY agent). The split rule is
        #    structural (the smaller line of a per-member pair = the Founders
        #    override), not agent-specific — so it applies to whoever wrote it.
        #    A lone Med-Supp line (no pair) is NOT in medsupp_overrides and has no
        #    sibling, so it falls through to quarantine below (correct).
        if is_renewal and plan in _UHC_MEDSUPP and \
                (member, writing.upper(), amount) in medsupp_overrides:
            out.append(draft(amount, FOUNDERS_OVERRIDE, None, sref))       # smaller = override
            continue
        if is_renewal and plan in _UHC_MEDSUPP and \
                (member, writing.upper()) in medsupp_paired_members:
            cls = CHARGEBACK if amount < 0 else AGENT_COMMISSION
            out.append(draft(amount, cls, rate, sref))                     # larger = renewal split
            continue

        # ── Everything else: "New" enrollments (complex cols L/T/AA/AB — analyze
        #    later), other-agent Med-Supp, PDP edge cases, DVH manual, garbage.
        #    Keep the full action string (AJ reads it in the quarantine tab) but
        #    cap to the payment_type column width (256) so an upload can never
        #    fail on a long description. DVH Manual Payment rows carry no member
        #    column — pull the member name (and writing-agent ID) out of the action
        #    string so the quarantine row isn't '(unnamed)'.
        q_member = member
        if not q_member:
            dvh_name = _uhc_dvh_member(action)
            if dvh_name:
                q_member = dvh_name
                dvh_wid = _uhc_dvh_agent_id(action)
                if dvh_wid and writing_id_to_name.get(dvh_wid):
                    writing = writing_id_to_name[dvh_wid]
        out.append(draft(amount, NEEDS_MANUAL_REVIEW, None, sref,
                         ptype=(action[:256] or None), member_name=q_member))
    return out


def money_rows_total_uhc(sheets) -> float:
    """Independent re-sum of every amount-bearing UHC row (for the completeness
    check). Sums ALL non-zero Commission cells incl. hard rows."""
    rows = _uhc_rows(sheets)
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= _UHC_AMOUNT:
            continue
        total += _to_float(row[_UHC_AMOUNT])
    return total


# (extractor, money_rows_total) per carrier.
# UHC was validated 2026-06-11 (97.7% auto-split, every agent balances to the
# penny; the ~2.3% it can't auto-split — "New" enrollment proration, PARTD dust,
# other-agent Med-Supp — are tagged NEEDS_MANUAL_REVIEW and surfaced in the
# upload's quarantine tab for AJ). Now live through the normalized upload path.
EXTRACTORS = {
    "Healthspring": (extract_lineitems_healthspring, money_rows_total_healthspring),
    "Devoted": (extract_lineitems_devoted, money_rows_total_devoted),
    "BCBS": (extract_lineitems_bcbs, money_rows_total_bcbs),
    "Aetna": (extract_lineitems_aetna, money_rows_total_aetna),
    "Humana": (extract_lineitems_humana, money_rows_total_humana),
    "UHC": (extract_lineitems_uhc, money_rows_total_uhc),
}


# Per-agent carriers ship MULTIPLE files per month under one (carrier, period)
# statement — one file per agent (BCBS) or a mix (Devoted: agency file + Rebekah).
# Their line items carry a per-file token in source_ref (carrier::<token>::...), so
# re-uploading one file must delete ONLY that file's rows, never another agent's.
# Agency-wide carriers (UHC/Humana/Aetna/Healthspring) ship ONE file and use the
# default blanket replace. Map carrier -> (source_ref scheme prefix, token deriver).
PER_AGENT_CARRIERS = {
    "BCBS": ("bcbs", _bcbs_filetoken),            # one file per agent (token = P-Number)
    "Devoted": ("devoted", _devoted_filetoken),   # agency + Rebekah (token = npn/agency)
    "Healthspring": ("healthspring", _healthspring_filetoken),  # batch files (token = filename NN_NNNNNN)
}


def file_scoped_prefix(carrier, sheets):
    """For a per-agent carrier, return the source_ref LIKE-prefix identifying ONLY
    the uploaded file's rows (e.g. 'bcbs::p12345::%'), used to scope the
    replace-on-reupload delete so other agents'/files' rows survive. Returns None
    for agency-wide carriers (caller does a blanket replace)."""
    entry = PER_AGENT_CARRIERS.get(carrier)
    if not entry:
        return None
    scheme, token_fn = entry
    return f"{scheme}::{token_fn(sheets)}::%"


@dataclass
class BalanceReport:
    carrier: str
    lineitem_total: float
    money_rows_total: float
    agent_payout_total: float
    founders_keep_total: float
    internal_ok: bool
    completeness_ok: bool

    def __str__(self):
        return (f"<BalanceReport {self.carrier} li={self.lineitem_total} "
                f"sheet={self.money_rows_total} payout={self.agent_payout_total} "
                f"keep={self.founders_keep_total} internal_ok={self.internal_ok} "
                f"completeness_ok={self.completeness_ok}>")


def verify_statement_balance(carrier, line_items, sheets, tol=0.01) -> BalanceReport:
    """Assert (1) internal balance: Σ raw == Σ payout + Σ keep (true by
    construction), and (2) completeness: Σ line-item raw == independent re-sum of
    the carrier's money rows from the raw sheets. A row the extractor dropped or
    mis-summed makes the two diverge → completeness_ok=False, naming the carrier.
    line_items may be LineItemDraft or persisted CommissionLineItem (both expose
    raw_amount / split_rate / classification)."""
    _, money_total_fn = EXTRACTORS[carrier]
    li_total = round(sum((li.raw_amount or 0.0) for li in line_items), 2)
    payout_total = 0.0
    keep_total = 0.0
    for li in line_items:
        p, k = split_breakdown(li)
        payout_total += p
        keep_total += k
    payout_total = round(payout_total, 2)
    keep_total = round(keep_total, 2)
    money_total = round(money_total_fn(sheets), 2)
    internal_ok = abs(li_total - (payout_total + keep_total)) <= tol
    completeness_ok = abs(li_total - money_total) <= tol
    return BalanceReport(
        carrier=carrier, lineitem_total=li_total, money_rows_total=money_total,
        agent_payout_total=payout_total, founders_keep_total=keep_total,
        internal_ok=internal_ok, completeness_ok=completeness_ok)


def _snapshot_line(line) -> dict:
    """The mutable money fields of a line item — the unit of undo. Captured
    before a resolve/edit so undo can restore the EXACT prior state."""
    return {
        "classification": line.classification,
        "raw_amount": line.raw_amount,
        "split_rate": line.split_rate,
        "agent_id": line.agent_id,
        "payment_type": line.payment_type,
    }


def resolve_quarantine_line(line, agent_id, override_amount, split_rate, *, user_id=None):
    """Resolve ONE quarantined (needs_manual_review) line item in place: split its
    lump amount into an agent_commission part (the remainder, which splits at
    `split_rate`) and a founders_override part (`override_amount`, 100% Founders).

    Records a CommissionLineItemRevision(action="resolve") snapshotting the
    pre-resolution state so the action is auditable + undoable. Faithful to the
    ledger invariant: the two new rows' raw_amounts sum back to the original
    raw_amount, so Σ raw is unchanged. Caller commits."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    before = _snapshot_line(line)
    raw = round(line.raw_amount or 0.0, 2)
    ov = round(override_amount or 0.0, 2)
    # override must share the sign of the row and not exceed it in magnitude
    if abs(ov) > abs(raw):
        raise ValueError("override amount exceeds the line amount")

    commission_part = round(raw - ov, 2)
    # The original row becomes the agent commission remainder (splits).
    line.classification = (CHARGEBACK if commission_part < 0 else AGENT_COMMISSION)
    line.agent_id = agent_id
    line.raw_amount = commission_part
    line.split_rate = split_rate
    line.payment_type = (line.payment_type or "")[:240] + " [resolved]"

    override_row = None
    ovr_ref = f"{line.source_ref}::ovr"
    existing_ovr = CommissionLineItem.query.filter_by(
        statement_id=line.statement_id, source_ref=ovr_ref).first()
    # Snapshot the sibling's state BEFORE this resolve mutates/deletes/creates it,
    # so undo can restore EXACTLY what was there before (None = it didn't exist).
    sibling_before = _snapshot_line(existing_ovr) if existing_ovr is not None else None
    if abs(ov) >= 0.005:
        override_row = existing_ovr or CommissionLineItem(
            agency_id=line.agency_id, statement_id=line.statement_id,
            carrier=line.carrier, period_label=line.period_label,
            statement_date=line.statement_date, source_ref=ovr_ref,
            member_name=line.member_name, mbi=line.mbi,
            carrier_member_id=line.carrier_member_id)
        override_row.raw_amount = ov
        override_row.split_rate = None
        override_row.classification = FOUNDERS_OVERRIDE
        override_row.agent_id = None
        override_row.payment_type = "override [resolved]"
        if existing_ovr is None:
            db.session.add(override_row)
    elif existing_ovr is not None:
        db.session.delete(existing_ovr)   # override cleared on a re-resolve

    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="resolve", user_id=user_id,
        before_json=json.dumps(before), after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=(ovr_ref if (abs(ov) >= 0.005 or existing_ovr is not None) else None),
        sibling_before_json=(json.dumps(sibling_before) if sibling_before is not None else None)))
    return override_row


def undo_last_change(line, *, user_id=None) -> bool:
    """Undo the most recent un-undone human change to `line`. Restores the line's
    mutable fields from that revision's before_json, reverses the sibling ::ovr
    row it created (delete if the override didn't exist before; restore if it did),
    marks the revision undone, and records an action="undo" revision. Returns True
    if a change was undone, False if there was nothing to undo. Caller commits."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    rev = (CommissionLineItemRevision.query
           .filter_by(line_item_id=line.id, undone=False)
           .filter(CommissionLineItemRevision.action != "undo")
           .order_by(CommissionLineItemRevision.id.desc())
           .first())
    if rev is None:
        return False

    before = json.loads(rev.before_json or "{}")
    after_undo_snapshot = _snapshot_line(line)   # for the undo revision's "before"
    # restore mutable fields
    for k, v in before.items():
        setattr(line, k, v)

    # reverse the sibling override row this revision created/changed.
    # sibling_before_json tells us what the sibling looked like BEFORE this
    # revision's resolve touched it:
    #   - None  -> the sibling did not exist before -> undo DELETES it.
    #   - a dict -> the sibling existed before (this was a re-resolve) -> undo
    #     RESTORES it to that prior state, re-creating it if the resolve deleted
    #     it outright (the override-amount->0 case).
    if rev.sibling_source_ref:
        sib = CommissionLineItem.query.filter_by(
            statement_id=line.statement_id, source_ref=rev.sibling_source_ref).first()
        sibling_before = (json.loads(rev.sibling_before_json)
                           if rev.sibling_before_json else None)
        if sibling_before is None:
            # sibling didn't exist before this revision's change -> remove it.
            if sib is not None:
                db.session.delete(sib)
        else:
            # sibling existed before -> restore it (re-create if it was deleted).
            if sib is None:
                sib = CommissionLineItem(
                    agency_id=line.agency_id, statement_id=line.statement_id,
                    carrier=line.carrier, period_label=line.period_label,
                    statement_date=line.statement_date,
                    source_ref=rev.sibling_source_ref,
                    member_name=line.member_name, mbi=line.mbi,
                    carrier_member_id=line.carrier_member_id)
                db.session.add(sib)
            for k, v in sibling_before.items():
                setattr(sib, k, v)

    rev.undone = True
    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="undo", user_id=user_id,
        before_json=json.dumps(after_undo_snapshot),
        after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=rev.sibling_source_ref))
    return True


def edit_line_split(line, *, agent_amount, override_amount, agent_id, split_rate, user_id=None):
    """Correct a line's agent-commission / founders-override split in place. The
    two amounts MUST sum to the line's current combined total (its raw plus any
    existing ::ovr sibling) — an edit can never change Σ raw or break the
    agent+override==combined invariant. Records an action="edit" revision. Caller
    commits. Raises ValueError if the amounts don't sum to the original combined."""
    from app.models import CommissionLineItem, CommissionLineItemRevision
    import json
    ovr_ref = f"{line.source_ref}::ovr"
    existing_ovr = CommissionLineItem.query.filter_by(
        statement_id=line.statement_id, source_ref=ovr_ref).first()
    original_combined = round((line.raw_amount or 0.0) +
                              (existing_ovr.raw_amount if existing_ovr else 0.0), 2)
    agent_amount = round(agent_amount or 0.0, 2)
    override_amount = round(override_amount or 0.0, 2)
    if round(agent_amount + override_amount, 2) != original_combined:
        raise ValueError(
            f"agent ${agent_amount} + override ${override_amount} must equal "
            f"the line total ${original_combined}")

    before = _snapshot_line(line)
    line.classification = (CHARGEBACK if agent_amount < 0 else AGENT_COMMISSION)
    line.raw_amount = agent_amount
    line.agent_id = agent_id
    line.split_rate = split_rate

    # Snapshot the sibling's state BEFORE this edit mutates/deletes/creates it,
    # so undo can restore EXACTLY what was there before (None = it didn't exist).
    sibling_before = _snapshot_line(existing_ovr) if existing_ovr is not None else None
    if abs(override_amount) >= 0.005:
        ovr = existing_ovr or CommissionLineItem(
            agency_id=line.agency_id, statement_id=line.statement_id,
            carrier=line.carrier, period_label=line.period_label,
            statement_date=line.statement_date, source_ref=ovr_ref,
            member_name=line.member_name, mbi=line.mbi,
            carrier_member_id=line.carrier_member_id)
        ovr.raw_amount = override_amount
        ovr.split_rate = None
        ovr.classification = FOUNDERS_OVERRIDE
        ovr.agent_id = None
        ovr.payment_type = "override [edited]"
        if existing_ovr is None:
            db.session.add(ovr)
    elif existing_ovr is not None:
        db.session.delete(existing_ovr)

    db.session.add(CommissionLineItemRevision(
        agency_id=line.agency_id, line_item_id=line.id, statement_id=line.statement_id,
        action="edit", user_id=user_id,
        before_json=json.dumps(before), after_json=json.dumps(_snapshot_line(line)),
        sibling_source_ref=(ovr_ref if (abs(override_amount) >= 0.005 or existing_ovr is not None) else None),
        sibling_before_json=(json.dumps(sibling_before) if sibling_before is not None else None)))


def persist_line_items(carrier, drafts, statement, agency_id, agent_resolver=None) -> int:
    """Insert/update CommissionLineItem rows for a statement, idempotent on
    (statement_id, source_ref). agent_resolver(writing_agent_raw) -> user_id|None
    resolves each draft's writing agent. Each row is also back-linked to its
    Customer by MBI (the ingest resolver already created/matched the customer), so
    the recap can hyperlink the member name to their profile. Returns count written."""
    from app.models import Customer
    # One query for all MBIs in this batch → customer_id map (cheap; customers
    # already exist post-ingest). Humana keys on humana_id, not mbi.
    mbis = {(d.mbi or "").strip() for d in drafts if (d.mbi or "").strip()}
    cust_by_mbi = {}
    if mbis:
        col = Customer.humana_id if carrier == "Humana" else Customer.mbi
        for cid, key in (db.session.query(Customer.id, col)
                         .filter(Customer.agency_id == agency_id, col.in_(mbis)).all()):
            if key:
                cust_by_mbi[key] = cid
    count = 0
    for d in drafts:
        agent_id = None
        if agent_resolver is not None and d.writing_agent_raw:
            agent_id = agent_resolver(d.writing_agent_raw)
        existing = (CommissionLineItem.query
                    .filter_by(statement_id=statement.id, agency_id=agency_id,
                               source_ref=d.source_ref)
                    .first())
        if existing is None:
            existing = CommissionLineItem(
                agency_id=agency_id, statement_id=statement.id,
                source_ref=d.source_ref, carrier=carrier)
            db.session.add(existing)
        existing.carrier = carrier
        existing.period_label = statement.period_label
        existing.statement_date = statement.statement_date
        existing.agent_id = agent_id
        existing.customer_id = cust_by_mbi.get((d.mbi or "").strip())
        existing.member_name = d.member_name
        existing.mbi = d.mbi
        existing.carrier_member_id = d.carrier_member_id
        existing.raw_amount = d.raw_amount
        existing.split_rate = d.split_rate
        existing.classification = d.classification
        existing.payment_type = d.payment_type
        count += 1
    return count
