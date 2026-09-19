import json

import httpx
import pytest
from langchain_core.messages import convert_to_messages

pytest.importorskip("langchain_openai")

from ficcion.budget import TokenBudget
from ficcion.cli import load_seed
from ficcion.demo import DemoBackend
from ficcion.engine import FictionEngine
from ficcion.llm import LocalConfig, RoleRunner, strict_json_schema
from ficcion.models import ArchiveProposal, TurnRequest
from ficcion.openai_backend import OpenAIBackend, OpenAITokenCounter
from ficcion.runtime import ModelProfile, build_runtime, diagnose, read_secrets


@pytest.mark.parametrize("json_mode", ["prompt", "json_object", "json_schema"])
def test_langchain_openai_full_turn_with_real_tokenizer_and_mock_http(tmp_path, monkeypatch, json_mode):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=fixture-key-not-real\n", encoding="utf-8")
    fake, requests = DemoBackend(), []
    backend = None
    def respond(req):
        assert str(req.url) == "https://api.openai.com/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer fixture-key-not-real"
        body = json.loads(req.content)
        requests.append(body)
        role = next(r for r in ["scenario", "director", "actor", "archivist"]
            if body["messages"][0]["content"].startswith(RoleRunner.system_prompt(r)))
        maximum = body.get("max_completion_tokens", body.get("max_tokens"))
        assert maximum > 0 and body["store"] is False
        if role != "actor" and json_mode != "prompt":
            assert body["response_format"]["type"] == json_mode
        content = fake.complete(role, body["messages"], None, maximum)
        count = backend.chat.get_num_tokens_from_messages(convert_to_messages(body["messages"]))
        return httpx.Response(200, json={"id": "mock-completion", "object": "chat.completion", "created": 0,
            "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": count, "completion_tokens": 80, "total_tokens": count + 80}})
    profile = ModelProfile(provider="openai", model="gpt-4o-2024-08-06", base_url="https://api.openai.com/v1",
                           tokenizer="openai", context_window=8192, json_mode=json_mode)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        backend, budget = build_runtime(profile, env, client)
        with FictionEngine(tmp_path / "data", backend, token_budget=budget) as engine:
            sid = engine.create_session(load_seed())
            result = engine.run_turn(TurnRequest(session_id=sid, turn_id="openai", user_input="Hola, Iria."))
            assert not result.demo and len(requests) == 4
            assert result.context_report["actor"]["count_accuracy"] == "estimated_chat_overhead"
            assert all(c["tokens"]["count_matches_usage"] for c in engine.roles.audit)
            assert "fixture-key-not-real" not in json.dumps(engine.repository.export_session(sid))


def test_env_preserves_environment_priority_without_interpolation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=from-file\nFICTION_API_KEY=${NOT_EXPANDED}\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from-environment")
    monkeypatch.delenv("FICTION_API_KEY", raising=False)
    assert read_secrets(path) == {"OPENAI_API_KEY": "from-environment", "FICTION_API_KEY": "${NOT_EXPANDED}"}


def test_diagnosis_lists_models_without_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    seen = []
    def respond(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={"data": [{"id": "gpt-4o-2024-08-06"}]})
    profile = ModelProfile(provider="openai", model="", base_url="https://api.openai.com/v1", tokenizer="openai", context_window=8192)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = diagnose(profile, tmp_path / "absent.env", client)
    assert result["status"] == "needs_model" and not result["generation_performed"]
    assert seen == [("GET", "/v1/models")]


def test_missing_key_never_calls_network(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    profile = ModelProfile(provider="openai", base_url="https://api.openai.com/v1", tokenizer="openai", context_window=8192)
    def forbidden(req):
        pytest.fail("No debe llamar a la red sin clave.")
    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        assert diagnose(profile, tmp_path / "absent.env", client)["status"] == "missing_key"


def test_strict_schema_requires_all_properties_including_nested_objects():
    schema = strict_json_schema(ArchiveProposal.model_json_schema())
    def check(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            assert "default" not in node
            for child in node.values(): check(child)
        elif isinstance(node, list):
            for child in node: check(child)
    check(schema)
