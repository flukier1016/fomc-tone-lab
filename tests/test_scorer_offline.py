"""The Claude scoring engine against a stub client: request shape, records, caching, refusals.

No network and no API key: these tests exercise our code, they are not model results.
"""

import json
from types import SimpleNamespace

import pytest

from fomc.llm import scorer

TEXT = "Inflation remains elevated. The Committee is prepared to adjust the stance of policy as appropriate."
GOOD = {
    "policy_relevance": "high",
    "policy_action": None,
    "forward_guidance": 1,
    "inflation_assessment": 2,
    "activity_labor_assessment": 0,
    "risk_balance": 1,
    "balance_sheet": None,
    "overall_stance": 1,
    "stance_score": 0.45,
    "confidence": 0.8,
    "evidence": [
        {"dimension": "inflation_assessment", "quote": "Inflation remains elevated"},
        {"dimension": "overall", "quote": "a sentence that is not in the text"},
    ],
    "rationale": "Inflation concern dominates.",
}


def message(payload, stop="end_turn"):
    usage = SimpleNamespace(to_dict=lambda: {"input_tokens": 1200, "output_tokens": 300})
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(payload))]
    return SimpleNamespace(
        id="msg_test", model="claude-opus-5-5", stop_reason=stop, usage=usage, content=blocks, stop_details=None
    )


class StubClient:
    def __init__(self, payload=GOOD, stop="end_turn"):
        self.calls = []
        create = self._create(payload, stop)
        raw = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(with_raw_response=raw))
        self.messages = SimpleNamespace(with_raw_response=raw)

    def _create(self, payload, stop):
        def create(**kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(headers={"request-id": "req_test"}, parse=lambda: message(payload, stop))

        return create


@pytest.fixture()
def tmp_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(scorer, "LLM_DIR", tmp_path)
    return tmp_path


def test_request_shape_records_and_cache(tmp_llm):
    client = StubClient()
    sc = scorer.Scorer(model="claude-opus-5-5", effort="medium", client=client)
    job = scorer.live_job(TEXT, "statement")
    rec = sc.call(job)
    kw = client.calls[0]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["effort"] == "medium" and kw["thinking"] == {"type": "adaptive"}
    assert kw["fallbacks"] == "default" and kw["betas"] == [scorer.FALLBACK_BETA]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "2024" not in kw["messages"][0]["content"]  # no date is sent with the text
    assert rec["status"] == "ok" and rec["request_id"] == "req_test" and rec["message_id"] == "msg_test"
    ev = rec["checks"]["evidence"]
    assert ev["verified"] == 1 and ev["n"] == 2  # the invented quote is caught
    assert rec["checks"]["stance_score_in_range"] and rec["checks"]["confidence_in_range"]
    sc.call(job)  # same input: served from disk
    assert len(client.calls) == 1
    saved = json.loads(sc.path(job).read_text())
    assert saved["input_sha256"] == job.input_sha


def test_refusal_and_truncation_are_not_scored(tmp_llm):
    for stop, status in (("refusal", "refusal"), ("max_tokens", "truncated")):
        sc = scorer.Scorer(model="claude-opus-5-5", client=StubClient(stop=stop), run_tag=stop)
        rec = sc.call(scorer.live_job(TEXT, "speech"))
        assert rec["status"] == status and rec["parsed"] is None
        assert not sc.done(scorer.live_job(TEXT, "speech"))  # will be retried


def test_models_without_server_fallback_use_plain_endpoint(tmp_llm):
    client = StubClient()
    scorer.Scorer(model="claude-haiku-5-5", client=client).call(scorer.live_job(TEXT, "speech"))
    assert "fallbacks" not in client.calls[0]


def test_changed_rubric_input_means_new_request(tmp_llm):
    client = StubClient()
    sc = scorer.Scorer(model="claude-opus-5-5", client=client)
    sc.call(scorer.live_job(TEXT, "speech"))
    sc.call(scorer.live_job(TEXT + " Additional sentence.", "speech"))
    assert len(client.calls) == 2
