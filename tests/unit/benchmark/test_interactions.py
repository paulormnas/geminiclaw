import pytest

from scripts.benchmark import interactions

pytestmark = pytest.mark.unit


def test_summarize_events_counts_messages_and_verdicts():
    events = [
        {"event_type": "spawn", "payload": {}},
        {"event_type": "plan_generated", "payload": {}},
        {"event_type": "plan_validation", "payload": {"approved": False, "issues": ["sem critérios"]}},
        {"event_type": "plan_validation", "payload": {"approved": True}},
        {"event_type": "subtask_review", "payload": {"approved": False, "issues": ["artefato ausente"]}},
        {"event_type": "subtask_review", "payload": {"approved": True}},
        {"event_type": "ask_researcher",
         "payload": {"question": "Qual split?", "why_cant_proceed": "x", "options": ["a"]}},
    ]
    out = interactions.summarize_events(events)
    assert out["messages"] == 6  # tudo menos 'spawn'
    assert out["plan_validations"] == {"total": 2, "approved": 1, "rejections": [["sem critérios"]]}
    assert out["subtask_reviews"]["rejections"] == [["artefato ausente"]]
    assert out["ask_researcher"][0]["question"] == "Qual split?"


def test_tokens_by_agent_share_sums_to_100():
    rows = [
        {"agent_id": "developer", "calls": 3, "prompt_tokens": 600, "completion_tokens": 200, "cost_usd": 0.1,
         "avg_latency_ms": 10.4},
        {"agent_id": "reviewer", "calls": 1, "prompt_tokens": 100, "completion_tokens": 100, "cost_usd": None,
         "avg_latency_ms": 5},
    ]
    out = interactions.tokens_by_agent(rows)
    assert [r["agent"] for r in out] == ["developer", "reviewer"]
    assert out[0]["share_pct"] == 80.0 and out[1]["cost_usd"] == 0.0


def test_report_renders_interactions():
    from scripts.benchmark import report

    data = {"tokens_by_agent": [{"agent": "developer", "share_pct": 80.0, "calls": 3}], "messages": 4,
            "event_counts": {"plan_generated": 1},
            "plan_validations": {"total": 2, "approved": 1, "rejections": [["sem critérios"]]},
            "subtask_reviews": {"total": 1, "approved": 1, "rejections": []},
            "ask_researcher": [{"question": "Qual split?", "why": "ambíguo", "options": []}]}
    text = report.render_interactions([{"name": "a", "status": "exit 0", "db": {"interactions": data}},
                                       {"name": "b", "status": "skipped"}])
    assert "developer 80.0% (3 chamadas)" in text and "1/2 aprovadas" in text and "Qual split?" in text
    assert "### b" not in text
