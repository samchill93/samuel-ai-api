"""
Tests for the tool-using agent (Module 5): the tool implementations (pure, over the real
corpus files) and the agent loop (driven by a fake client, so no API key or network needed).
"""

from agent import (
    _list_skills, _list_projects, _list_services, _run_tool, run_agent,
    TOOL_SCHEMAS, MAX_ITERATIONS,
)


# --- Tools -------------------------------------------------------------------
def test_list_skills_splits_shipped_and_building():
    all_ = _list_skills("all")
    assert all_["shipped"], "shipped list should not be empty"
    assert all_["currently_building_not_shipped"], "building list should not be empty"


def test_list_skills_status_filters():
    assert set(_list_skills("shipped")) == {"shipped"}
    assert set(_list_skills("building")) == {"currently_building_not_shipped"}


def test_list_projects_returns_titles_and_summaries():
    projects = _list_projects()["projects"]
    assert len(projects) >= 3
    for p in projects:
        assert p["title"] and p["summary"] and p["file"].startswith("projects/")


def test_list_services_has_real_starting_prices():
    services = _list_services()["services"]
    assert len(services) == 5
    assert "Starter Support Bot" in {s["name"] for s in services}
    for s in services:
        assert isinstance(s["starting_usd"], int) and s["starting_usd"] > 0


def test_run_tool_unknown_is_reported_not_raised():
    assert "error" in _run_tool("nope", {})


def test_tool_schemas_match_implementations():
    for schema in TOOL_SCHEMAS:
        assert schema["name"] and schema["description"]
        assert schema["input_schema"]["type"] == "object"
    assert {s["name"] for s in TOOL_SCHEMAS} == {
        "search_portfolio", "list_skills", "list_projects", "list_services"}


# --- Agent loop (fake client, no network) ------------------------------------
class _Block:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type, self.text, self.name, self.input, self.id = type, text, name, input, id


class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Resp:
    def __init__(self, content, stop_reason, usage):
        self.content, self.stop_reason, self.usage = content, stop_reason, usage


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_agent_runs_a_tool_then_answers():
    responses = [
        _Resp([_Block("text", text="Let me check the packages."),
               _Block("tool_use", name="list_services", input={}, id="t1")],
              stop_reason="tool_use", usage=_Usage(100, 20)),
        _Resp([_Block("text", text="Samuel offers a Starter Support Bot from $1,500.")],
              stop_reason="end_turn", usage=_Usage(50, 30)),
    ]
    client = _FakeClient(responses)
    result = run_agent("What can Samuel build for a support bot and what does it cost?", client)

    assert result["stopped"] == "complete"
    assert result["iterations"] == 2
    assert result["input_tokens"] == 150 and result["output_tokens"] == 50
    kinds = [s["type"] for s in result["steps"]]
    assert "thought" in kinds and "tool_call" in kinds          # both recorded
    call = next(s for s in result["steps"] if s["type"] == "tool_call")
    assert call["tool"] == "list_services"
    assert "services" in call["output"]                         # the real tool actually ran
    assert "1,500" in result["answer"] or "1500" in result["answer"]


def test_agent_feeds_tool_results_back_to_the_model():
    responses = [
        _Resp([_Block("tool_use", name="list_skills", input={"status": "shipped"}, id="t1")],
              stop_reason="tool_use", usage=_Usage(80, 10)),
        _Resp([_Block("text", text="done")], stop_reason="end_turn", usage=_Usage(40, 5)),
    ]
    client = _FakeClient(responses)
    run_agent("List his shipped skills.", client)

    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_msgs = [
        m for m in second_call_messages
        if m["role"] == "user" and isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
    ]
    assert tool_result_msgs, "tool results must be fed back for the next turn"
    assert tool_result_msgs[0]["content"][0]["tool_use_id"] == "t1"


def test_agent_stops_at_iteration_cap():
    # A client that ALWAYS asks for a tool would loop forever without the cap.
    always_tool = _Resp([_Block("tool_use", name="list_services", input={}, id="t")],
                        stop_reason="tool_use", usage=_Usage(10, 5))
    client = _FakeClient([always_tool] * (MAX_ITERATIONS + 3))
    result = run_agent("loop forever", client)
    assert result["stopped"] == "max_iterations"
    assert result["iterations"] == MAX_ITERATIONS
