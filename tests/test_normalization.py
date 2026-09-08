from datetime import date
from decimal import Decimal

import pytest

from app.normalization import (
    NormalizationError,
    normalize_billing_cycle,
    normalize_plan,
    normalize_status,
    parse_amount,
    parse_churned,
    parse_date,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Starter", "starter"),
        (" STARTER ", "starter"),
        ("Start", "starter"),
        ("Tier 1", "starter"),
        ("Professional", "pro"),
        ("Tier 2", "pro"),
        ("ENT", "enterprise"),
        ("Tier 3", "enterprise"),
    ],
)
def test_normalize_plan_aliases(raw: str, expected: str) -> None:
    assert normalize_plan(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Paid", "paid"),
        ("completed", "paid"),
        ("success", "paid"),
        ("awaiting", "pending"),
        ("in_review", "pending"),
        ("declined", "failed"),
        ("error", "failed"),
        ("REFUND", "refunded"),
        ("charged_back", "refunded"),
        ("cancelled", "void"),
        ("canceled", "void"),
    ],
)
def test_normalize_status_aliases(raw: str, expected: str) -> None:
    assert normalize_status(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Monthly", "monthly"),
        ("annual", "annual"),
        ("annually", "annual"),
        ("yearly", "annual"),
    ],
)
def test_normalize_billing_cycle_aliases(raw: str, expected: str) -> None:
    assert normalize_billing_cycle(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected", "flags"),
    [
        ("TRUE", True, ()),
        ("Yes", True, ()),
        ("1", True, ()),
        ("N", False, ()),
        ("false", False, ()),
        ("", None, ("churned_unknown",)),
        ("maybe", None, ("unknown_churned",)),
    ],
)
def test_parse_churned(raw: str, expected: bool | None, flags: tuple[str, ...]) -> None:
    assert parse_churned(raw) == (expected, flags)


@pytest.mark.parametrize(
    ("raw", "currency", "expected", "flags"),
    [
        ("$4,900.00", "USD", Decimal("4900.00"), ()),
        ("€5,292.00", "EUR", Decimal("5292.00"), ()),
        ("1,200.00 EUR", "EUR", Decimal("1200.00"), ()),
        ("31432", "GBP", Decimal("31432"), ()),
        ("£-10.50", "GBP", Decimal("-10.50"), ()),
        ("$100.00", "EUR", Decimal("100.00"), ("amount_currency_marker_mismatch",)),
    ],
)
def test_parse_amount(
    raw: str,
    currency: str,
    expected: Decimal,
    flags: tuple[str, ...],
) -> None:
    assert parse_amount(raw, currency) == (expected, flags)


@pytest.mark.parametrize(
    ("raw", "expected", "flags"),
    [
        ("2024-01-05", date(2024, 1, 5), ()),
        ("2024/01/05", date(2024, 1, 5), ()),
        ("Jan 5 2024", date(2024, 1, 5), ()),
        ("01/05/2024", date(2024, 1, 5), ("invoice_date_ambiguous",)),
        ("05/13/2024", date(2024, 5, 13), ()),
        ("05-01-2024", date(2024, 1, 5), ("invoice_date_ambiguous",)),
        ("22-11-2025", date(2025, 11, 22), ()),
    ],
)
def test_parse_date_policy(raw: str, expected: date, flags: tuple[str, ...]) -> None:
    assert parse_date(raw, "invoice_date", required=True) == (expected, flags)


@pytest.mark.parametrize(
    ("function", "raw"),
    [
        (normalize_plan, "Gold"),
        (normalize_status, "unknown"),
        (normalize_billing_cycle, "weekly"),
    ],
)
def test_unknown_required_categories_raise(function: object, raw: str) -> None:
    with pytest.raises(NormalizationError):
        function(raw)  # type: ignore[operator]


def test_invalid_required_date_raises() -> None:
    with pytest.raises(NormalizationError, match="invalid_invoice_date"):
        parse_date("99/99/9999", "invoice_date", required=True)


def test_invalid_optional_date_is_flagged() -> None:
    assert parse_date("99/99/9999", "signup_date", required=False) == (
        None,
        ("signup_date_invalid",),
    )