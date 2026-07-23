"""Sorting keys for BOB plan rows → the plan buckets. Pure functions: they identify
which bucket a row belongs to; they NEVER create buckets. plan_type is unreliable in
real data (often the plan NAME, blank, or a carrier code), so classification uses
keywords across plan_type AND plan_name."""
import re
from typing import Optional

PERPETUAL = 0   # year sentinel for plans whose benefits are NOT annual (medigap/DVH/etc.)

# H#### / S#### / R#### + plan(3) + optional segment(3), '-' OR '_' (Humana dash,
# Healthspring underscore). Normalized to dash form.
_CODE_RE = re.compile(r"([HSR]\d{4})[-_](\d{3})(?:[-_](\d{3}))?")
_MEDIGAP_LETTER_RE = re.compile(r"\bPLAN\s+([A-N])\b|\b(?:MED\s*SUP|SUPPLEMENT|SUPP)\w*\s+([A-N])\b")
_MEDIGAP_KW_RE = re.compile(r"\b(?:SUPPLEMENT|MED\s*SUPP?|AARPMODMEDSUP|MEDSUP|SUPP|MES)\b")
_NAMED_KW = ("DVH", "DENTAL", "VISION", "HOSPITAL", "INDEMNITY", "IDV", "GTL", "EXTEND")


def classify_plan(plan_type: str, plan_name: str) -> str:
    blob = f"{plan_type or ''} {plan_name or ''}".upper()
    if _MEDIGAP_KW_RE.search(blob) or _MEDIGAP_LETTER_RE.search(blob):
        return "medigap"
    if any(k in blob for k in _NAMED_KW):
        return "named"
    return "year_bound"


def extract_contract_code(carrier: str, rec: dict) -> Optional[str]:
    c = (carrier or "").strip().lower()
    if c == "aetna":
        contract = (rec.get("cms_contract_number") or "").strip().upper()
        pbp = (rec.get("pbp_code") or "").strip()
        if contract and pbp:
            return f"{contract}-{pbp.zfill(3)}"
    if c == "devoted":
        code = (rec.get("contract_code") or "").strip().upper()
        if code:
            return code
    name = (rec.get("plan_name") or "").upper()
    m = _CODE_RE.search(name)
    if not m:
        return None
    parts = [m.group(1), m.group(2)] + ([m.group(3)] if m.group(3) else [])
    return "-".join(parts)


def cms_plan_id_of(contract_code: str) -> Optional[str]:
    if not contract_code:
        return None
    parts = contract_code.strip().upper().split("-")
    return f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else None


def medigap_letter(plan_name: str) -> Optional[str]:
    m = _MEDIGAP_LETTER_RE.search((plan_name or "").upper())
    return (m.group(1) or m.group(2)) if m else None
