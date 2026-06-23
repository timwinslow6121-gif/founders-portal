from app.names import normalize_person_name


def test_aetna_last_mi_comma_first():
    first, mi, last, full = normalize_person_name("BRYANT D,KATHERINE")
    assert (first, mi, last) == ("Katherine", "D", "Bryant")
    assert full == "Katherine D. Bryant"


def test_aetna_no_middle():
    first, mi, last, full = normalize_person_name("JAMES S,NAOMI")
    assert first == "Naomi" and last == "James" and mi == "S"
    assert full == "Naomi S. James"


def test_commission_format():
    first, mi, last, full = normalize_person_name("WINECOFF, JACK J.")
    assert first == "Jack" and last == "Winecoff"
    assert full == "Jack J. Winecoff"


def test_plain_first_last():
    first, mi, last, full = normalize_person_name("john smith")
    assert full == "John Smith" and first == "John" and last == "Smith"


def test_blank():
    assert normalize_person_name("") == ("", "", "", "")
    assert normalize_person_name(None) == ("", "", "", "")
