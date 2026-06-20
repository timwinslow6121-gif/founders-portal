from app.branding import carrier_color, CARRIER_BRAND

def test_known_carrier_colors():
    assert carrier_color("UHC") == "#002677"
    assert carrier_color("Humana") == "#5EA908"
    assert carrier_color("BCBS") == "#0080C7"

def test_alias_and_default():
    assert carrier_color("UnitedHealthcare") == "#002677"
    assert carrier_color("Nonexistent") == "#266EA5"

def test_map_is_dict():
    assert isinstance(CARRIER_BRAND, dict) and "Aetna" in CARRIER_BRAND
