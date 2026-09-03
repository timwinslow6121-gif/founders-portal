"""Carrier termination-reason codes.

Aetna states its termination reason as a code in column T of the member book of
business. The column mixes FOUR vocabularies — bare/NG (08/NG08), zero-padded/QN
(090/QN090), T### (T090), and word codes (SBT2) — documented in
docs/Carrier BOB DL/Enrollment_Termination_Codes.xlsx (updated 9/8/25).

Four codes mean death. `92`/`NG92` does NOT: it is RELOCATION OUT OF PLAN SERVICE
AREA and is the most common code in the book, so matching on frequency rather
than meaning would suppress dozens of living members.

Zero-padding is significant — `08` and `090` are distinct death codes, while `92`
and `092` are both relocation. Compare the raw string; never strip leading zeros.
"""

AETNA_DEATH_CODES = frozenset({
    "08", "NG08",      # REPORT OF DEATH
    "090", "QN090",    # Member Date of Death received on the DTRR
    "T090",            # Deceased
    "SBT2",            # Deceased
})


def is_aetna_death(code) -> bool:
    """True when an Aetna Term Reason Code means the member died."""
    if not code:
        return False
    return str(code).strip().upper() in AETNA_DEATH_CODES
