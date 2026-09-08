from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from app.models import BillingCycle, CanonicalInvoice, Currency, InvoiceStatus, Plan

PLAN_MAP: dict[str, Plan] = {
    "starter": "starter",
    "start": "starter",
    "tier 1": "starter",
    "pro": "pro",
    "professional": "pro",
    "tier 2": "pro",
    "enterprise": "enterprise",
    "ent": "enterprise",
    "tier 3": "enterprise",
}

CYCLE_MAP: dict[str, BillingCycle] = {
    "monthly": "monthly",
    "month": "monthly",
    "annual": "annual",
    "annually": "annual",
    "yearly": "annual",
    "year": "annual",
}

STATUS_MAP: dict[str, InvoiceStatus] = {
    "paid": "paid",
    "complete": "paid",
    "completed": "paid",
    "success": "paid",
    "pending": "pending",
    "in_review": "pending",
    "awaiting": "pending",
    "failed": "failed",
    "declined": "failed",
    "error": "failed",
    "refunded": "refunded",
    "refund": "refunded",
    "charged_back": "refunded",
    "void": "void",
    "cancelled": "void",
    "canceled": "void",
}

TRUE_VALUES = {"true", "yes", "1", "y"}
FALSE_VALUES = {"false", "no", "0", "n"}
FX_TO_USD: dict[Currency, Decimal] = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NormalizationError(ValueError):
    def __init__(self, code: str, field: str, raw_value: str) -> None:
        self.code = code
        self.field = field
        self.raw_value = raw_value
        super().__init__(f"{code}:{field}={raw_value!r}")


def normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _normalize_required(
    value: str,
    mapping: Mapping[str, str],
    field: str,
) -> str:
    token = normalize_token(value)
    try:
        return mapping[token]
    except KeyError as error:
        raise NormalizationError(f"unknown_{field}", field, value) from error


def normalize_plan(value: str) -> Plan:
    return cast(Plan, _normalize_required(value, PLAN_MAP, "plan"))


def normalize_status(value: str) -> InvoiceStatus:
    return cast(InvoiceStatus, _normalize_required(value, STATUS_MAP, "status"))


def normalize_billing_cycle(value: str) -> BillingCycle:
    return cast(
        BillingCycle,
        _normalize_required(value, CYCLE_MAP, "billing_cycle"),
    )


def parse_churned(value: str) -> tuple[bool | None, tuple[str, ...]]:
    token = normalize_token(value)
    if not token:
        return None, ("churned_unknown",)
    if token in TRUE_VALUES:
        return True, ()
    if token in FALSE_VALUES:
        return False, ()
    return None, ("unknown_churned",)


def parse_amount(value: str, currency: str) -> tuple[Decimal, tuple[str, ...]]:
    canonical_currency = currency.strip().upper()
    if canonical_currency not in FX_TO_USD:
        raise NormalizationError("unknown_currency", "currency", currency)

    text = value.strip()
    marker_currency: str | None = None
    flags: set[str] = set()
    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP"}
    if text and text[0] in symbol_map:
        marker_currency = symbol_map[text[0]]
        text = text[1:].strip()

    suffix_match = re.search(r"\s*(USD|EUR|GBP)\s*$", text, re.IGNORECASE)
    if suffix_match:
        suffix_currency = suffix_match.group(1).upper()
        if marker_currency and marker_currency != suffix_currency:
            flags.add("amount_currency_marker_mismatch")
        marker_currency = suffix_currency
        text = text[: suffix_match.start()].strip()

    if marker_currency and marker_currency != canonical_currency:
        flags.add("amount_currency_marker_mismatch")

    try:
        amount = Decimal(text.replace(",", ""))
    except InvalidOperation as error:
        raise NormalizationError("invalid_amount", "amount", value) from error
    return amount, tuple(sorted(flags))


def parse_date(
    value: str,
    field: str,
    *,
    required: bool,
) -> tuple[date | None, tuple[str, ...]]:
    text = value.strip()
    if not text:
        if required:
            raise NormalizationError(f"invalid_{field}", field, value)
        return None, (f"{field}_invalid",)

    patterns = (
        (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d", False),
        (r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d", False),
        (r"^[A-Za-z]+\s+\d{1,2}\s+\d{4}$", "%b %d %Y", False),
        (r"^\d{1,2}/\d{1,2}/\d{4}$", "%m/%d/%Y", True),
        (r"^\d{1,2}-\d{1,2}-\d{4}$", "%d-%m-%Y", True),
    )

    for pattern, date_format, numeric_trailing_year in patterns:
        if not re.fullmatch(pattern, text):
            continue
        try:
            parsed = datetime.strptime(text, date_format).date()
        except ValueError:
            if date_format != "%b %d %Y":
                break
            try:
                parsed = datetime.strptime(text, "%B %d %Y").date()
            except ValueError:
                break

        flags: tuple[str, ...] = ()
        if numeric_trailing_year:
            separator = "/" if "/" in text else "-"
            first, second, _ = (int(part) for part in text.split(separator))
            if first <= 12 and second <= 12:
                flags = (f"{field}_ambiguous",)
        return parsed, flags

    if required:
        raise NormalizationError(f"invalid_{field}", field, value)
    return None, (f"{field}_invalid",)


def _required_text(raw: Mapping[str, str], field: str) -> str:
    value = raw.get(field, "").strip()
    if not value:
        raise NormalizationError(f"missing_{field}", field, raw.get(field, ""))
    return value


def _parse_integer(value: str, field: str, *, minimum: int) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as error:
        raise NormalizationError(f"invalid_{field}", field, value) from error
    if parsed < minimum:
        raise NormalizationError(f"invalid_{field}", field, value)
    return parsed


def _parse_optional_integer(
    value: str,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    if not value.strip():
        return None
    parsed = _parse_integer(value, field, minimum=minimum)
    if parsed > maximum:
        raise NormalizationError(f"invalid_{field}", field, value)
    return parsed


def _normalize_payment_method(value: str) -> str | None:
    token = normalize_token(value)
    if not token:
        return None
    aliases = {
        "credit card": "credit_card",
        "credit_card": "credit_card",
        "ach": "ach",
        "wire transfer": "wire",
        "wire": "wire",
        "invoice": "invoice",
    }
    return aliases.get(token, token.replace(" ", "_"))


def normalize_invoice(raw: Mapping[str, str], source_row: int) -> CanonicalInvoice:
    invoice_id = _required_text(raw, "invoice_id")
    account_id = _required_text(raw, "account_id")
    account_name = re.sub(r"\s+", " ", _required_text(raw, "account_name"))
    region = _required_text(raw, "region").upper()
    if region not in {"NA", "EMEA", "APAC", "LATAM"}:
        raise NormalizationError("unknown_region", "region", raw.get("region", ""))

    plan = normalize_plan(_required_text(raw, "plan"))
    billing_cycle = normalize_billing_cycle(_required_text(raw, "billing_cycle"))
    status = normalize_status(_required_text(raw, "status"))
    currency_text = _required_text(raw, "currency").upper()
    if currency_text not in FX_TO_USD:
        raise NormalizationError("unknown_currency", "currency", currency_text)
    currency = cast(Currency, currency_text)

    seats = _parse_integer(_required_text(raw, "seats"), "seats", minimum=1)
    support_tickets = _parse_integer(
        _required_text(raw, "support_tickets"),
        "support_tickets",
        minimum=0,
    )
    try:
        discount_pct = Decimal(_required_text(raw, "discount_pct"))
    except InvalidOperation as error:
        raise NormalizationError(
            "invalid_discount_pct",
            "discount_pct",
            raw.get("discount_pct", ""),
        ) from error
    if discount_pct < 0 or discount_pct > 100:
        raise NormalizationError(
            "invalid_discount_pct",
            "discount_pct",
            raw.get("discount_pct", ""),
        )

    csat_score = _parse_optional_integer(
        raw.get("csat_score", ""),
        "csat_score",
        minimum=1,
        maximum=5,
    )
    amount_local, amount_flags = parse_amount(_required_text(raw, "amount"), currency)
    invoice_date_value, invoice_date_flags = parse_date(
        _required_text(raw, "invoice_date"),
        "invoice_date",
        required=True,
    )
    signup_date, signup_date_flags = parse_date(
        raw.get("signup_date", ""),
        "signup_date",
        required=False,
    )
    churned, churned_flags = parse_churned(raw.get("churned", ""))

    flags = set(amount_flags + invoice_date_flags + signup_date_flags + churned_flags)
    contact_email = raw.get("contact_email", "").strip()
    if not contact_email:
        flags.add("contact_email_missing")
    elif not EMAIL_PATTERN.fullmatch(contact_email):
        flags.add("contact_email_malformed")
    if not raw.get("industry", "").strip():
        flags.add("industry_missing")
    if not raw.get("payment_method", "").strip():
        flags.add("payment_method_missing")
    if csat_score is None:
        flags.add("csat_unknown")
    if status == "refunded" and amount_local >= 0:
        flags.add("refund_non_negative")
    if status != "refunded" and amount_local < 0:
        flags.add("unexpected_negative_amount")

    assert invoice_date_value is not None
    fx_to_usd = FX_TO_USD[currency]
    return CanonicalInvoice(
        invoice_id=invoice_id,
        account_id=account_id,
        account_name=account_name,
        region=region,
        industry=raw.get("industry", "").strip() or None,
        plan=plan,
        billing_cycle=billing_cycle,
        seats=seats,
        currency=currency,
        amount_local=amount_local,
        fx_to_usd=fx_to_usd,
        amount_usd_unrounded=amount_local * fx_to_usd,
        discount_pct=discount_pct,
        status=status,
        payment_method=_normalize_payment_method(raw.get("payment_method", "")),
        signup_date=signup_date,
        invoice_date=invoice_date_value,
        churned=churned,
        csat_score=csat_score,
        support_tickets=support_tickets,
        source_row=source_row,
        quality_flags=tuple(sorted(flags)),
        raw_values=dict(raw),
    )