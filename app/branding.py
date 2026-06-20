"""Single source of truth for carrier brand colors (was duplicated in recap.html JS)."""

CARRIER_BRAND = {
    "UnitedHealthcare": "#002677", "UHC": "#002677",
    "Humana": "#5EA908",
    "Devoted": "#FF4F00", "Devoted Health": "#FF4F00",
    "BCBS": "#0080C7", "BCBS NC": "#0080C7",
    "Aetna": "#7D3F98",
    "HealthSpring": "#9E28B5", "Healthspring": "#9E28B5",
    "GTL": "#2F61FE",
    "Medico": "#EDC319", "Wellable": "#EDC319",
}
DEFAULT_BRAND = "#266EA5"

def carrier_color(name: str) -> str:
    return CARRIER_BRAND.get(name, DEFAULT_BRAND)
