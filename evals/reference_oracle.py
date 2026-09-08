from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "cloudnova_invoices.csv"
DEFAULT_OUTPUT = ROOT / "evals" / "golden.json"

CONTRACT_VERSIONS = {
    "data": 1,
    "metrics": 1,
    "query": 1,
    "evaluation": 1,
}

PLAN_MAP = {
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

CYCLE_MAP = {
    "monthly": "monthly",
    "month": "monthly",
    "annual": "annual",
    "annually": "annual",
    "yearly": "annual",
    "year": "annual",
}

STATUS_MAP = {
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
FX_TO_USD = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
}
LIST_PRICE = {
    "starter": Decimal("49"),
    "pro": Decimal("99"),
    "enterprise": Decimal("299"),
}
MONEY_QUANTUM = Decimal("0.01")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalized_token(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def normalize_required(value: str, mapping: dict[str, str], field: str) -> str:
    token = normalized_token(value)
    if token not in mapping:
        raise ValueError(f"unknown_{field}:{value}")
    return mapping[token]


def parse_decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except Exception as error:
        raise ValueError(f"invalid_{field}:{value}") from error


def parse_integer(value: str, field: str, minimum: int | None = None) -> int:
    try:
        parsed = int(value.strip())
    except Exception as error:
        raise ValueError(f"invalid_{field}:{value}") from error
    if minimum is not None and parsed < minimum:
        raise ValueError(f"invalid_{field}:{value}")
    return parsed


def parse_optional_integer(
    value: str, field: str, minimum: int, maximum: int
) -> int | None:
    if not value.strip():
        return None
    parsed = parse_integer(value, field)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"invalid_{field}:{value}")
    return parsed


def parse_boolean(value: str) -> tuple[bool | None, list[str]]:
    token = normalized_token(value)
    if not token:
        return None, ["churned_unknown"]
    if token in TRUE_VALUES:
        return True, []
    if token in FALSE_VALUES:
        return False, []
    return None, ["unknown_churned"]


def parse_amount(value: str, currency: str) -> tuple[Decimal, list[str]]:
    text = value.strip()
    flags: list[str] = []
    marker_currency: str | None = None

    symbol_map = {"$": "USD", "€": "EUR", "£": "GBP"}
    if text and text[0] in symbol_map:
        marker_currency = symbol_map[text[0]]
        text = text[1:].strip()

    suffix_match = re.search(r"\s*(USD|EUR|GBP)\s*$", text, re.IGNORECASE)
    if suffix_match:
        suffix_currency = suffix_match.group(1).upper()
        if marker_currency and marker_currency != suffix_currency:
            flags.append("amount_currency_marker_mismatch")
        marker_currency = suffix_currency
        text = text[: suffix_match.start()].strip()

    if marker_currency and marker_currency != currency:
        flags.append("amount_currency_marker_mismatch")

    try:
        amount = Decimal(text.replace(",", ""))
    except Exception as error:
        raise ValueError(f"invalid_amount:{value}") from error
    return amount, sorted(set(flags))


def parse_date(value: str, field: str, required: bool) -> tuple[date | None, list[str]]:
    text = value.strip()
    if not text:
        if required:
            raise ValueError(f"invalid_{field}:{value}")
        return None, [f"{field}_invalid"]

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
            if date_format == "%b %d %Y":
                try:
                    parsed = datetime.strptime(text, "%B %d %Y").date()
                except ValueError:
                    break
            else:
                break

        flags: list[str] = []
        if numeric_trailing_year:
            separator = "/" if "/" in text else "-"
            first, second, _ = (int(part) for part in text.split(separator))
            if first <= 12 and second <= 12:
                flags.append(f"{field}_ambiguous")
        return parsed, flags

    if required:
        raise ValueError(f"invalid_{field}:{value}")
    return None, [f"{field}_invalid"]


def parse_source_row(raw: dict[str, str], source_row: int) -> dict[str, Any]:
    required_text = (
        "invoice_id",
        "account_id",
        "account_name",
        "region",
        "plan",
        "billing_cycle",
        "seats",
        "currency",
        "amount",
        "discount_pct",
        "status",
        "invoice_date",
        "support_tickets",
    )
    for field in required_text:
        if not raw[field].strip():
            raise ValueError(f"missing_{field}")

    flags: list[str] = []
    region = raw["region"].strip().upper()
    if region not in {"NA", "EMEA", "APAC", "LATAM"}:
        raise ValueError(f"unknown_region:{raw['region']}")

    plan = normalize_required(raw["plan"], PLAN_MAP, "plan")
    billing_cycle = normalize_required(raw["billing_cycle"], CYCLE_MAP, "billing_cycle")
    status = normalize_required(raw["status"], STATUS_MAP, "status")
    currency = raw["currency"].strip().upper()
    if currency not in FX_TO_USD:
        raise ValueError(f"unknown_currency:{raw['currency']}")

    seats = parse_integer(raw["seats"], "seats", minimum=1)
    discount_pct = parse_decimal(raw["discount_pct"], "discount_pct")
    if discount_pct < 0 or discount_pct > 100:
        raise ValueError(f"invalid_discount_pct:{raw['discount_pct']}")
    support_tickets = parse_integer(raw["support_tickets"], "support_tickets", minimum=0)
    csat_score = parse_optional_integer(raw["csat_score"], "csat_score", 1, 5)

    amount_local, amount_flags = parse_amount(raw["amount"], currency)
    flags.extend(amount_flags)
    invoice_date, invoice_flags = parse_date(raw["invoice_date"], "invoice_date", True)
    signup_date, signup_flags = parse_date(raw["signup_date"], "signup_date", False)
    flags.extend(invoice_flags)
    flags.extend(signup_flags)
    churned, churn_flags = parse_boolean(raw["churned"])
    flags.extend(churn_flags)

    contact_email = raw["contact_email"].strip()
    if not contact_email:
        flags.append("contact_email_missing")
    elif not EMAIL_PATTERN.fullmatch(contact_email):
        flags.append("contact_email_malformed")
    if not raw["industry"].strip():
        flags.append("industry_missing")
    if not raw["payment_method"].strip():
        flags.append("payment_method_missing")
    if csat_score is None:
        flags.append("csat_unknown")
    if status == "refunded" and amount_local >= 0:
        flags.append("refund_non_negative")
    if status != "refunded" and amount_local < 0:
        flags.append("unexpected_negative_amount")

    assert invoice_date is not None
    return {
        "invoice_id": raw["invoice_id"].strip(),
        "account_id": raw["account_id"].strip(),
        "account_name": re.sub(r"\s+", " ", raw["account_name"].strip()),
        "region": region,
        "industry": raw["industry"].strip() or None,
        "plan": plan,
        "billing_cycle": billing_cycle,
        "seats": seats,
        "currency": currency,
        "amount_local": amount_local,
        "amount_usd_unrounded": amount_local * FX_TO_USD[currency],
        "discount_pct": discount_pct,
        "status": status,
        "payment_method": normalized_token(raw["payment_method"]) or None,
        "signup_date": signup_date,
        "invoice_date": invoice_date,
        "churned": churned,
        "csat_score": csat_score,
        "support_tickets": support_tickets,
        "source_row": source_row,
        "quality_flags": sorted(set(flags)),
    }


def ingest_source(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_bytes = path.read_bytes()
    with path.open(newline="", encoding="utf-8") as source_file:
        reader = csv.DictReader(source_file)
        if reader.fieldnames is None:
            raise ValueError("CSV header is missing")
        rows = list(reader)

    parsed_by_row: dict[int, dict[str, Any]] = {}
    disposition: dict[int, dict[str, Any]] = {}
    first_raw_occurrence: dict[tuple[str, ...], int] = {}
    valid_nonduplicates: list[dict[str, Any]] = []

    for source_row, raw in enumerate(rows, start=2):
        try:
            parsed = parse_source_row(raw, source_row)
        except ValueError as error:
            disposition[source_row] = {
                "disposition": "quarantined",
                "reason": str(error),
            }
            continue

        parsed_by_row[source_row] = parsed
        raw_key = tuple(raw[field] for field in reader.fieldnames)
        if raw_key in first_raw_occurrence:
            disposition[source_row] = {
                "disposition": "exact_duplicate",
                "duplicate_of_source_row": first_raw_occurrence[raw_key],
            }
            continue
        first_raw_occurrence[raw_key] = source_row
        valid_nonduplicates.append(parsed)

    invoice_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for parsed in valid_nonduplicates:
        invoice_groups[parsed["invoice_id"]].append(parsed)

    authoritative: list[dict[str, Any]] = []
    for invoice_id, group in invoice_groups.items():
        ordered = sorted(group, key=lambda record: record["source_row"])
        winner = ordered[-1]
        disposition[winner["source_row"]] = {"disposition": "authoritative"}
        authoritative.append(winner)
        for superseded in ordered[:-1]:
            disposition[superseded["source_row"]] = {
                "disposition": "superseded",
                "authoritative_source_row": winner["source_row"],
                "invoice_id": invoice_id,
            }

    snapshots = account_snapshots(authoritative)
    counts = Counter(entry["disposition"] for entry in disposition.values())
    if sum(counts.values()) != len(rows):
        raise AssertionError("row dispositions do not reconcile")
    if len({record["invoice_id"] for record in authoritative}) != len(authoritative):
        raise AssertionError("authoritative invoice IDs are not unique")

    quality_counts = Counter(
        flag for record in authoritative for flag in record["quality_flags"]
    )
    profile = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_bytes": len(source_bytes),
        "source_data_rows": len(rows),
        "dispositions": dict(sorted(counts.items())),
        "authoritative_invoice_count": len(authoritative),
        "account_snapshot_count": len(snapshots),
        "quality_flag_counts": dict(sorted(quality_counts.items())),
    }
    return sorted(authoritative, key=lambda record: record["source_row"]), profile


def account_snapshots(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["account_id"]].append(record)

    snapshots: dict[str, dict[str, Any]] = {}
    for account_id, group in groups.items():
        snapshot = max(group, key=lambda record: (record["invoice_date"], record["source_row"]))
        identity_fields = ("account_name", "region", "industry")
        conflicts = {
            field: sorted({record[field] for record in group if record[field] is not None})
            for field in identity_fields
        }
        conflicts = {field: values for field, values in conflicts.items() if len(values) > 1}
        copied = dict(snapshot)
        copied["identity_conflicts"] = conflicts
        if conflicts:
            copied["quality_flags"] = sorted(
                set(copied["quality_flags"]) | {"account_identity_conflict"}
            )
        snapshots[account_id] = copied
    return snapshots


def rounded(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def decimal_text(value: Decimal) -> str:
    return format(rounded(value), ".2f")


def evidence_entry(record: dict[str, Any], contribution: Decimal | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "invoice_id": record["invoice_id"],
        "source_row": record["source_row"],
    }
    if contribution is not None:
        entry["contribution_usd"] = decimal_text(contribution)
    return entry


def recognized_contribution(record: dict[str, Any]) -> Decimal:
    if record["status"] == "paid":
        return cast(Decimal, record["amount_usd_unrounded"])
    if record["status"] == "refunded" and record["amount_local"] < 0:
        return cast(Decimal, record["amount_usd_unrounded"])
    return Decimal("0")


def metric_recognized_revenue(records: list[dict[str, Any]]) -> dict[str, Any]:
    population = [record for record in records if record["invoice_date"].year == 2024]
    paid = [record for record in population if record["status"] == "paid"]
    refunds = [
        record
        for record in population
        if record["status"] == "refunded" and record["amount_local"] < 0
    ]
    anomalies = [
        record
        for record in population
        if record["status"] == "refunded" and record["amount_local"] >= 0
    ]
    contributing = paid + refunds
    paid_total = sum((record["amount_usd_unrounded"] for record in paid), Decimal("0"))
    refund_total = sum((record["amount_usd_unrounded"] for record in refunds), Decimal("0"))
    return {
        "result": {
            "net_revenue_usd": decimal_text(paid_total + refund_total),
            "paid_revenue_usd": decimal_text(paid_total),
            "refund_impact_usd": decimal_text(refund_total),
            "paid_invoice_count": len(paid),
            "refunded_invoice_count": len(refunds),
            "ambiguous_date_count": sum(
                "invoice_date_ambiguous" in record["quality_flags"]
                for record in contributing
            ),
            "excluded_anomaly_count": len(anomalies),
        },
        "evidence": sorted(
            [
                evidence_entry(record, recognized_contribution(record))
                for record in contributing
            ],
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def account_mrr(snapshot: dict[str, Any]) -> Decimal:
    discount_pct = cast(Decimal, snapshot["discount_pct"])
    plan = cast(str, snapshot["plan"])
    seats = cast(int, snapshot["seats"])
    discount_multiplier = Decimal("1") - discount_pct / Decimal("100")
    return LIST_PRICE[plan] * seats * discount_multiplier


def metric_regional_mrr(records: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = account_snapshots(records)
    active = [snapshot for snapshot in snapshots.values() if snapshot["churned"] is False]
    churned_count = sum(snapshot["churned"] is True for snapshot in snapshots.values())
    unknown_count = sum(snapshot["churned"] is None for snapshot in snapshots.values())
    regional: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in active:
        regional[snapshot["region"]].append(snapshot)

    regions: list[dict[str, Any]] = []
    for region, region_snapshots in regional.items():
        total = sum((account_mrr(snapshot) for snapshot in region_snapshots), Decimal("0"))
        average = total / len(region_snapshots)
        regions.append(
            {
                "region": region,
                "total_mrr_usd": decimal_text(total),
                "account_count": len(region_snapshots),
                "average_mrr_usd": decimal_text(average),
                "_average": average,
            }
        )
    regions.sort(key=lambda item: (-item["_average"], item["region"]))
    for item in regions:
        del item["_average"]

    return {
        "result": {
            "regions": regions,
            "winner": regions[0]["region"] if regions else None,
            "churned_excluded_count": churned_count,
            "unknown_churn_excluded_count": unknown_count,
        },
        "evidence": sorted(
            [evidence_entry(snapshot, account_mrr(snapshot)) for snapshot in active],
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def metric_refunds(records: list[dict[str, Any]]) -> dict[str, Any]:
    refunds = [
        record
        for record in records
        if record["status"] == "refunded" and record["amount_local"] < 0
    ]
    anomalies = [
        record
        for record in records
        if record["status"] == "refunded" and record["amount_local"] >= 0
    ]
    revenue_impact = sum(
        (record["amount_usd_unrounded"] for record in refunds), Decimal("0")
    )
    currency_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in refunds:
        currency_groups[record["currency"]].append(record)
    currency_breakdown = [
        {
            "currency": currency,
            "invoice_count": len(group),
            "local_total_signed": decimal_text(
                sum((record["amount_local"] for record in group), Decimal("0"))
            ),
        }
        for currency, group in sorted(currency_groups.items())
    ]
    return {
        "result": {
            "amount_given_back_usd": decimal_text(abs(revenue_impact)),
            "revenue_impact_usd": decimal_text(revenue_impact),
            "refund_invoice_count": len(refunds),
            "excluded_anomaly_count": len(anomalies),
            "currency_breakdown": currency_breakdown,
        },
        "evidence": sorted(
            [evidence_entry(record, record["amount_usd_unrounded"]) for record in refunds],
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def metric_plan_churn(records: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = account_snapshots(records)
    plans: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    rates: dict[str, Decimal] = {}
    for plan in ("enterprise", "starter"):
        plan_snapshots = [snapshot for snapshot in snapshots.values() if snapshot["plan"] == plan]
        known = [snapshot for snapshot in plan_snapshots if snapshot["churned"] is not None]
        churned = [snapshot for snapshot in known if snapshot["churned"] is True]
        rate = (
            Decimal(len(churned)) / Decimal(len(known)) * Decimal("100")
            if known
            else Decimal("0")
        )
        rates[plan] = rate
        plans[plan] = {
            "churned_account_count": len(churned),
            "known_account_count": len(known),
            "churn_rate_pct": decimal_text(rate),
            "unknown_excluded_count": len(plan_snapshots) - len(known),
        }
        evidence.extend(evidence_entry(snapshot) for snapshot in known)

    return {
        "result": {
            "plans": plans,
            "percentage_point_difference": decimal_text(
                rates["enterprise"] - rates["starter"]
            ),
        },
        "evidence": sorted(
            evidence,
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def metric_top_accounts(records: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = account_snapshots(records)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if recognized_contribution(record) != 0:
            grouped[record["account_id"]].append(record)

    ranked = []
    for account_id, group in grouped.items():
        revenue = sum((recognized_contribution(record) for record in group), Decimal("0"))
        if revenue == 0:
            continue
        snapshot = snapshots[account_id]
        csat_score = snapshot["csat_score"]
        csat_status = "unknown" if csat_score is None else ("low" if csat_score <= 2 else "ok")
        ranked.append(
            {
                "account_id": account_id,
                "account_name": snapshot["account_name"],
                "revenue_usd": decimal_text(revenue),
                "csat_score": csat_score,
                "csat_status": csat_status,
                "contributing_invoice_count": len(group),
                "_revenue": revenue,
            }
        )
    ranked.sort(key=lambda item: (-item["_revenue"], item["account_id"]))
    top_five = ranked[:5]
    top_ids = {item["account_id"] for item in top_five}
    for rank, item in enumerate(top_five, start=1):
        item["rank"] = rank
        del item["_revenue"]

    evidence = [
        evidence_entry(record, recognized_contribution(record))
        for record in records
        if record["account_id"] in top_ids and recognized_contribution(record) != 0
    ]
    return {
        "result": {"accounts": top_five},
        "evidence": sorted(
            evidence,
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def metric_exposure(records: list[dict[str, Any]]) -> dict[str, Any]:
    exposed = [record for record in records if record["status"] in {"pending", "failed"}]
    breakdown: dict[str, Any] = {}
    for status in ("pending", "failed"):
        status_records = [record for record in exposed if record["status"] == status]
        breakdown[status] = {
            "invoice_count": len(status_records),
            "exposure_usd": decimal_text(
                sum(
                    (abs(record["amount_usd_unrounded"]) for record in status_records),
                    Decimal("0"),
                )
            ),
        }
    total = sum((abs(record["amount_usd_unrounded"]) for record in exposed), Decimal("0"))
    return {
        "result": {
            "invoice_count": len(exposed),
            "exposure_usd": decimal_text(total),
            "breakdown": breakdown,
            "negative_amount_anomaly_count": sum(record["amount_local"] < 0 for record in exposed),
        },
        "evidence": sorted(
            [evidence_entry(record, abs(record["amount_usd_unrounded"])) for record in exposed],
            key=lambda item: (item["invoice_id"], item["source_row"]),
        ),
    }


def build_golden(source_path: Path) -> dict[str, Any]:
    records, profile = ingest_source(source_path)
    return {
        "schema_version": 1,
        "contracts": CONTRACT_VERSIONS,
        "dataset": profile,
        "metrics": {
            "recognized_revenue_2024": metric_recognized_revenue(records),
            "regional_average_mrr": metric_regional_mrr(records),
            "refunds_total": metric_refunds(records),
            "plan_churn_comparison": metric_plan_churn(records),
            "top_accounts_revenue": metric_top_accounts(records),
            "payment_exposure": metric_exposure(records),
        },
        "expected_limitation": {
            "intent": "unsupported_metric",
            "question": "What was our monthly churn rate throughout 2024?",
            "missing_data": ["churn_date", "historical_active_periods"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify CloudNova golden values")
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    golden = build_golden(arguments.source)
    rendered = json.dumps(golden, indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not arguments.output.exists():
            print(f"Missing golden file: {arguments.output}")
            return 1
        if arguments.output.read_text(encoding="utf-8") != rendered:
            print("Golden values differ from the independent oracle")
            return 1
        print("Golden values match the independent oracle")
        return 0

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {arguments.output}")
    print(json.dumps(golden["dataset"], indent=2, sort_keys=True))
    for intent, metric in golden["metrics"].items():
        print(f"{intent}: {json.dumps(metric['result'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())