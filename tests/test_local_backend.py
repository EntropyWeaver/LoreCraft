"""Contrato HTTP real con un transporte simulado: no mide la calidad de un LLM."""
import json

import httpx
import pytest

from ficcion.cli import load_seed
from ficcion.demo import DemoBackend
from ficcion.engine import FictionEngine
from ficcion.llm import LocalBackend, LocalConfig, ModelError, RoleRunner
from ficcion.models import TurnRequest


@pytest.mark.parametrize("json_mode", ["prompt", "json_object", "json_schema"])
def test_four_roles_over_chat_completions(tmp_path, json_mode):
    demo, requests = DemoBackend(), []

    def respond(req):
        body = json.loads(req.content)
        requests.append(body)
        assert str(req.url) == "http://localhost:1234/v1/chat/completions"
        assert req.headers["authorization"] == "Bearer secret-test-key"
        assert body["model"] == "local-test-model"
        role = next(role for role in ["scenario", "director", "actor", "archivist"]
                    if body["messages"][0]["content"].startswith(RoleRunner.system_prompt(role)))
        if role == "actor" or json_mode == "prompt":
            assert "response_format" not in body
        else:
            assert body["response_format"]["type"] == json_mode
        content = demo.complete(role, body["messages"], None, body["max_tokens"])
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        backend = LocalBackend(LocalConfig(model="local-test-model", base_url="http://localhost:1234/v1",
            api_key="secret-test-key", json_mode=json_mode), client=client)
        with FictionEngine(tmp_path, backend) as engine:
            sid = engine.create_session(load_seed())
            result = engine.run_turn(TurnRequest(session_id=sid, turn_id="http", user_input="Hola"))
            assert result.reply and not result.demo
            assert len(requests) == 4
            assert "secret-test-key" not in json.dumps(engine.repository.export_session(sid))


def test_invalid_json_is_retried_once_with_same_context(tmp_path):
    class FirstInvalid(DemoBackend):
        def complete(self, role, messages, schema, max_tokens):
            raw = super().complete(role, messages, schema, max_tokens)
            if role == "director" and len([c for c in self.calls if c["role"] == role]) == 1:
                return "Esto no es JSON."
            return raw
    backend = FirstInvalid()
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(load_seed())
        result = engine.run_turn(TurnRequest(session_id=sid, turn_id="retry", user_input="Hola"))
        assert result.reply
        calls = [c for c in backend.calls if c["role"] == "director"]
        assert len(calls) == 2
        assert calls[0]["messages"] == calls[1]["messages"][:2]
        assert calls[1]["messages"][2]["content"] == "Esto no es JSON."


@pytest.mark.parametrize("case", ["length", "server_error", "empty", "unclosed_think", "malformed"])
def test_transport_failure_never_substitutes_demo_or_commits_turn(tmp_path, case):
    def respond(req):
        if case == "server_error":
            return httpx.Response(503, json={"error": "unavailable"})
        if case == "malformed":
            return httpx.Response(200, json={"choices": [None]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "length" if case == "length" else "stop",
            "message": {"content": "<think>incompleto" if case == "unclosed_think" else ""}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        backend = LocalBackend(LocalConfig(model="test"), client=client)
        with FictionEngine(tmp_path, backend) as engine:
            sid = engine.create_session(load_seed())
            with pytest.raises(ModelError):
                engine.run_turn(TurnRequest(session_id=sid, turn_id="failed", user_input="Hola"))
            assert engine.repository.history(sid) == []
            assert engine.repository.session(sid)["scenario"] is None
