"""
app/parsers/__init__.py

Unified carrier file parser dispatcher.
Call parse_carrier_file(carrier, filepath) from any route or cron job.
"""

from app.parsers import uhc, humana, aetna, bcbs, devoted, healthspring

CARRIER_PARSERS = {
    "UHC": uhc.parse,
    "Humana": humana.parse,
    "Aetna": aetna.parse,
    "BCBS": bcbs.parse,
    "Devoted": devoted.parse,
    "Healthspring": healthspring.parse,
}

SUPPORTED_CARRIERS = list(CARRIER_PARSERS.keys())


def parse_carrier_file(carrier: str, filepath: str) -> list[dict]:
    """
    Parse a carrier BOB file and return normalized policy records.

    Args:
        carrier: Carrier name string matching CARRIER_PARSERS keys exactly.
        filepath: Absolute path to the uploaded file on disk.

    Returns:
        List of normalized policy dicts, ready to upsert into the Policy table.

    Raises:
        ValueError: If carrier is unsupported or file is malformed.
    """
    if carrier not in CARRIER_PARSERS:
        raise ValueError(
            f"Unsupported carrier: '{carrier}'. "
            f"Supported: {', '.join(SUPPORTED_CARRIERS)}"
        )

    parser_fn = CARRIER_PARSERS[carrier]
    records = parser_fn(filepath)

    if not records:
        raise ValueError(f"{carrier} file parsed successfully but contained 0 active records.")

    return records
