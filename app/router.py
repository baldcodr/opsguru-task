from __future__ import annotations

import re

from app.models import RouteDecision


def _normalized(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9$]+", question.casefold()))


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def route_question(question: str) -> RouteDecision:
    text = _normalized(question)
    if not text:
        raise ValueError("question must not be blank")

    if "churn" in text and _contains_any(
        text,
        ("monthly", "month by month", "throughout 2024", "cohort", "over time"),
    ):
        return RouteDecision(
            intent="unsupported_metric",
            mode="unsupported",
            reason=(
                "Monthly or cohort churn requires a churn date and historical active-period "
                "data, which the source does not contain."
            ),
        )

    if (
        _contains_any(text, ("top 5", "top five", "highest revenue", "rank the top"))
        and _contains_any(text, ("account", "customer"))
        and "revenue" in text
    ):
        return RouteDecision(
            intent="top_accounts_revenue",
            mode="metric",
            reason="Question requests the approved account revenue ranking.",
        )

    if (
        _contains_any(text, ("pending", "failed"))
        and _contains_any(text, ("exposure", "exposed", "risk", "stuck"))
    ):
        return RouteDecision(
            intent="payment_exposure",
            mode="metric",
            reason="Question requests the approved pending/failed exposure metric.",
        )

    if _contains_any(text, ("refund", "refunded", "charged back", "chargeback")) and not (
        "revenue" in text and "2024" in text
    ):
        return RouteDecision(
            intent="refunds_total",
            mode="metric",
            reason="Question requests the approved refund total.",
        )

    if _contains_any(text, ("mrr", "monthly recurring revenue")) and _contains_any(
        text,
        ("region", "where"),
    ):
        return RouteDecision(
            intent="regional_average_mrr",
            mode="metric",
            reason="Question requests the approved regional average MRR metric.",
        )

    if (
        "churn" in text
        and "enterprise" in text
        and _contains_any(text, ("starter", "start"))
    ):
        return RouteDecision(
            intent="plan_churn_comparison",
            mode="metric",
            reason="Question requests the approved Enterprise versus Starter churn comparison.",
        )

    if "revenue" in text and _contains_any(
        text,
        ("2024", "recognized", "paid invoice", "net of refunds"),
    ):
        return RouteDecision(
            intent="recognized_revenue_2024",
            mode="metric",
            reason="Question requests the approved 2024 recognized revenue metric.",
        )

    unsupported_aggregation_terms = (
        " arr ",
        "annual recurring revenue",
        "average ",
        " total ",
        " rate ",
        " rank ",
        " count ",
        "how much",
        "how many",
    )
    padded = f" {text} "
    if _contains_any(padded, unsupported_aggregation_terms):
        return RouteDecision(
            intent="unsupported_metric",
            mode="unsupported",
            reason="No approved deterministic metric matches this aggregation request.",
        )

    return RouteDecision(
        intent="semantic_lookup",
        mode="retrieval",
        reason="Question requests descriptive invoice or account records.",
    )