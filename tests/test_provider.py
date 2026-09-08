from __future__ import annotations

import json

import httpx

from app.provider import OpenAICompatibleSynthesizer


def test_openai_compatible_synthesizer_sends_only_grounded_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Grounded answer."}}]},
        )

    synthesizer = OpenAICompatibleSynthesizer(
        api_key="test-secret",
        base_url="https://provider.example/v1/",
        model="test-model",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )

    answer = synthesizer.synthesize(
        "How much was refunded for billing@example.com?",
        "refunds_total",
        {"amount_given_back_usd": "10.00"},
        [
            {
                "invoice_id": "INV-1",
                "account_id": "ACC-1",
                "account_name": "Acme",
                "source_row": 2,
                "reason": "refund contribution",
                "fields": {"status": "refunded"},
            }
        ],
    )

    assert answer == "Grounded answer."
    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "test-model"
    messages = body["messages"]
    assert isinstance(messages, list)
    grounded_payload = json.loads(messages[1]["content"])
    assert grounded_payload["structured_result"]["amount_given_back_usd"] == "10.00"
    serialized = json.dumps(body)
    assert "contact_email" not in serialized
    assert "billing@example.com" not in serialized
    assert "test-secret" not in serialized