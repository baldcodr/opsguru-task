import pytest

from app.router import route_question


@pytest.mark.parametrize(
    ("intent", "questions"),
    [
        (
            "recognized_revenue_2024",
            [
                "What was our total recognized revenue in USD for paid invoices in 2024?",
                "How much revenue did CloudNova recognize during 2024?",
                "Give me 2024 paid invoice revenue net of refunds.",
            ],
        ),
        (
            "regional_average_mrr",
            [
                "Which region has the highest average MRR per account?",
                "Rank regions by average monthly recurring revenue.",
                "Where is average MRR per customer greatest?",
            ],
        ),
        (
            "refunds_total",
            [
                "How much have we given back in refunds?",
                "What is the total refunded amount?",
                "Show the USD value of charged back invoices.",
            ],
        ),
        (
            "plan_churn_comparison",
            [
                "What's the churn rate among Enterprise accounts vs Starter?",
                "Compare Enterprise and Starter customer churn.",
                "Are Starter accounts churning more than Enterprise accounts?",
            ],
        ),
        (
            "top_accounts_revenue",
            [
                "List the top 5 accounts by revenue and flag CSAT <= 2.",
                "Who are our five highest revenue customers?",
                "Rank the top accounts by recognized revenue with low CSAT warnings.",
            ],
        ),
        (
            "payment_exposure",
            [
                "How many invoices are stuck in pending/failed and what's the exposed $?",
                "What is our unpaid exposure from failed and pending invoices?",
                "Count pending or failed bills and total their risk in USD.",
            ],
        ),
    ],
)
def test_supported_metric_paraphrases(intent: str, questions: list[str]) -> None:
    for question in questions:
        assert route_question(question).intent == intent


@pytest.mark.parametrize(
    "question",
    [
        "What was our monthly churn rate throughout 2024?",
        "What is ARR?",
        "What is the average invoice value by industry?",
    ],
)
def test_unsupported_aggregations_are_not_sent_to_retrieval(question: str) -> None:
    decision = route_question(question)

    assert decision.intent == "unsupported_metric"
    assert decision.mode == "unsupported"
    assert decision.reason


def test_descriptive_lookup_routes_to_retrieval() -> None:
    decision = route_question("Find annual Starter invoices for Initech in LATAM")

    assert decision.intent == "semantic_lookup"
    assert decision.mode == "retrieval"