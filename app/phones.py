"""Phone-number normalization — one canonical shape for the whole app.

The book currently holds five different phone formats across 5,400+ customers
(dashed, bare 10-digit, parenthesised, E.164, other). That inconsistency is why
number lookups are unreliable and why the Quo call-matching work found phones
never matched incoming E.164 traffic.

Canonical form is "NNN-NNN-NNNN" — the majority shape already in the book, so
normalizing moves the fewest rows.

Anything that is not a recognisable US 10-digit number is returned unchanged
rather than mangled: a bad guess is worse than an odd-looking value.
"""
import re

__all__ = ["normalize_phone", "phone_digits"]


def normalize_phone(raw) -> str:
    """'(704) 281-4280' / '+17042814280' / '7042814280' -> '704-281-4280'."""
    if raw in (None, ""):
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return str(raw).strip()
    return f"{digits[0:3]}-{digits[3:6]}-{digits[6:]}"


def phone_digits(raw) -> str:
    """Bare last-10-digits, for matching regardless of stored format.

    Use this for lookups (e.g. an inbound call's E.164 number against a stored
    dashed one); use normalize_phone for what gets written.
    """
    if raw in (None, ""):
        return ""
    digits = re.sub(r"\D", "", str(raw))
    return digits[-10:] if len(digits) >= 10 else digits
