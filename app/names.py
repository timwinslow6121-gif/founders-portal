"""Shared person-name normalizer → the agency's "First MI. Last" standard.
Structured (first, middle_initial, last, full) so parsers store the parts AND a
clean full_name. Handles the comma'd formats where the middle initial can be on
EITHER side of the comma:
  - Aetna 'Member Name'  "BRYANT D,KATHERINE"  (LAST [MI],FIRST)  → "Katherine D. Bryant"
  - commission           "WINECOFF, JACK J."   (LAST, FIRST [MI]) → "Jack J. Winecoff"
  - plain                "john smith"                              → "John Smith"
"""


def _tc(w):
    return w[:1].upper() + w[1:].lower() if w else w


def normalize_person_name(raw):
    """Return (first, middle_initial, last, full) in "First MI. Last" form."""
    s = (raw or "").strip()
    if not s:
        return ("", "", "", "")

    mi = ""
    if "," in s:
        last_side, first_side = [p.strip() for p in s.split(",", 1)]
        lp = last_side.split()
        # a trailing single-letter token on the LAST side = middle initial (Aetna)
        if len(lp) > 1 and len(lp[-1].rstrip(".")) == 1:
            mi = lp[-1].rstrip(".")
            lp = lp[:-1]
        last = " ".join(lp)
        fp = first_side.split()
        first = fp[0] if fp else ""
        # else a trailing single-letter on the FIRST side = middle initial (commission)
        if not mi and len(fp) > 1 and len(fp[-1].rstrip(".")) == 1:
            mi = fp[-1].rstrip(".")
    else:
        parts = s.split()
        first = parts[0] if parts else ""
        last = " ".join(parts[1:]) if len(parts) > 1 else ""

    first = _tc(first)
    last = " ".join(_tc(w) for w in last.split())
    mi = mi.upper()
    full = " ".join(x for x in [first, (mi + "." if mi else ""), last] if x)
    return (first, mi, last, full)
