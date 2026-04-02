"""Tests for E.164 phone normalization utility."""
import pytest
from app.comms.utils import normalize_e164


def test_already_e164():
    assert normalize_e164("+17705551234") == "+17705551234"


def test_formatted_us():
    assert normalize_e164("(770) 555-1234") == "+17705551234"


def test_hyphenated():
    assert normalize_e164("770-555-1234") == "+17705551234"


def test_digits_only():
    assert normalize_e164("7705551234") == "+17705551234"


def test_invalid_returns_none():
    assert normalize_e164("invalid") is None


def test_empty_returns_none():
    assert normalize_e164("") is None


def test_none_input_returns_none():
    assert normalize_e164(None) is None
