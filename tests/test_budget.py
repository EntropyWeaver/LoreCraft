import json
from types import SimpleNamespace

import pytest

from ficcion.budget import LMStudioCounter, TokenBudget, TokenBudgetError
from ficcion.cli import load_seed
from ficcion.demo import DemoBackend
from ficcion.engine import FictionEngine
from ficcion.llm import RoleRunner
from ficcion.models import TurnRequest


class TestCounter:
    """Contador artificial de unidades para probar límites, no un tokenizer LLM."""
    __test__ = False
    identity = "test-counter-only"
    context_window = 20000
    def count_messages(self, messages):
        return 20 + sum(len(m["content"]) for m in messages)


def test_whole_prompt_reserves_output_and_trims_old_turns_before_memories():
    counter = TestCounter()
    counter.context_window = 420
    budget = TokenBudget(counter, safety_tokens=30)
    payload = {"character_card": {"name": "Iria"}, "user_input": "entrada-actual",
        "character_memories": [{"id": "remember", "text": "dato elegido"}],
        "visible_history": [{"id": "old:user", "content": "x" * 200}, {"id": "old:assistant", "content": "y" * 200}]}
    make = lambda p: [{"role": "system", "content": "sistema" * 5}, {"role": "user", "content": json.dumps(p)}]
    messages, report = budget.fit("actor", payload, make, 40)
    assert report["fits"]
    assert report["prompt_tokens"] + 40 + 30 <= 420
    assert report["omitted_history_message_ids"] == ["old:user", "old:assistant"]
    assert report["included_memory_ids"] == ["remember"]
    assert "entrada-actual" in messages[1]["content"]
    assert len(payload["visible_history"]) == 2  # No modifica el estado que recibió.


def test_mandatory_prompt_cannot_be_truncated_to_fit():
    counter = TestCounter()
    counter.context_window = 100
    budget = TokenBudget(counter, safety_tokens=10)
    with pytest.raises(TokenBudgetError, match="prompt obligatorio"):
        budget.fit("scenario", {"brief": "x" * 150}, lambda p: [{"role": "system", "content": json.dumps(p)}], 20)


def test_context_window_never_exceeds_loaded_window():
    counter = TestCounter()
    counter.context_window = 600
    assert TokenBudget(counter, context_limit=10000).window == 600


def test_token_budget_integrates_with_all_roles_and_context_report(tmp_path):
    counter = TestCounter()
    with FictionEngine(tmp_path, DemoBackend(), token_budget=TokenBudget(counter)) as engine:
        sid = engine.create_session(load_seed())
        result = engine.run_turn(TurnRequest(session_id=sid, turn_id="t", user_input="Hola"))
        assert result.context_report["actor"]["budget_unit"] == "tokens"
        assert [x["role"] for x in engine.roles.audit] == ["scenario", "director", "actor", "archivist"]
        assert all(x["tokens"]["fits"] for x in engine.roles.audit)
        for call in engine.roles.audit:
            assert call["tokens"]["prompt_tokens"] == counter.count_messages(call["messages"])


def test_json_retry_is_counted_before_second_call(tmp_path):
    class InvalidDirector(DemoBackend):
        def complete(self, role, messages, schema, max_tokens):
            raw = super().complete(role, messages, schema, max_tokens)
            return "bad JSON" if role == "director" and len(messages) == 2 else raw
    with FictionEngine(tmp_path, InvalidDirector(), token_budget=TokenBudget(TestCounter())) as engine:
        sid = engine.create_session(load_seed())
        engine.run_turn(TurnRequest(session_id=sid, turn_id="retry", user_input="Hola"))
        calls = [c for c in engine.roles.audit if c["role"] == "director"]
        assert len(calls) == 2 and len(calls[1]["messages"]) == 4
        assert calls[1]["tokens"]["prompt_tokens"] > calls[0]["tokens"]["prompt_tokens"]


def test_lmstudio_uses_selected_loaded_model_template_and_tokens():
    class Model:
        identifier = "the-loaded-model"
        def get_context_length(self): return 4096
        def get_info(self): return SimpleNamespace(to_dict=lambda: {"identifier": self.identifier})
        def apply_prompt_template(self, chat):
            assert chat["messages"][0]["role"] == "system"
            return "[TEMPLATE]" + chat["messages"][0]["content"] + "[ASSISTANT]"
        def tokenize(self, formatted):
            assert formatted.startswith("[TEMPLATE]") and formatted.endswith("[ASSISTANT]")
            return [1, 2, 3, 4]
    client = SimpleNamespace(llm=SimpleNamespace(list_loaded=lambda: [Model()]))
    counter = LMStudioCounter("http://localhost:1234/v1", "the-loaded-model", client=client)
    assert counter.count_messages([{"role": "system", "content": "Hola"}]) == 4
    assert counter.context_window == 4096
    absent = LMStudioCounter("http://localhost:1234/v1", "missing", client=client)
    with pytest.raises(TokenBudgetError, match="no está cargado"):
        absent.count_messages([])
