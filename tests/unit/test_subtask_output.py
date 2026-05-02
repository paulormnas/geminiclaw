import pytest
import json
from src.subtask_output import SubtaskOutput
from src.orchestrator import AgentResult

def test_subtask_output_serialization():
    output = SubtaskOutput(
        task_name="t1",
        agent_id="researcher",
        status="success",
        text_summary="Summary",
        sources=[{"title": "S1", "url": "http://s1.com"}]
    )
    
    json_str = output.to_json()
    new_output = SubtaskOutput.from_json(json_str)
    
    assert new_output.task_name == "t1"
    assert new_output.sources[0]["title"] == "S1"

def test_subtask_output_context_string():
    output = SubtaskOutput(
        task_name="t1",
        agent_id="researcher",
        status="success",
        text_summary="This is a summary.",
        sources=[{"title": "Source 1", "url": "http://example.com"}],
        artifacts=[{"name": "report.md", "path": "/outputs/report.md"}]
    )
    
    ctx = output.to_context_string()
    assert "### Resultado de `t1` (Agente: researcher)" in ctx
    assert "This is a summary." in ctx
    assert "[Source 1](http://example.com)" in ctx
    assert "`report.md` em `/outputs/report.md`" in ctx

def test_from_agent_result_with_json():
    result = AgentResult(
        agent_id="researcher",
        session_id="s1",
        status="success",
        response={"text": '{"summary": "Short summary", "sources": [{"title": "S1"}]}'}
    )
    
    output = SubtaskOutput.from_agent_result("t1", "researcher", result)
    assert output.text_summary == "Short summary"
    assert output.sources[0]["title"] == "S1"

def test_from_agent_result_with_review():
    result = AgentResult(agent_id="base", session_id="s1", status="success", response={"text": "Hello"})
    review = {"status": "fail", "issues": ["issue 1"], "confidence": 0.5}
    
    output = SubtaskOutput.from_agent_result("t1", "base", result, review)
    assert output.status == "failed_review"
    assert output.confidence == 0.5
