"""Flujo de usuario del panel local, sin abrir un navegador ni conectar un LLM."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from ficcion.storage import Repository


def test_create_chat_approve_select_clear_and_local_mode(tmp_path, monkeypatch):
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FICTION_MODEL", raising=False)
    at = AppTest.from_file(str(app_path), default_timeout=20).run()
    assert not at.exception
    at.button[0].click().run()
    at.chat_input[0].set_value("Hola, Iria.").run()
    assert not at.exception
    assert len(at.chat_message) == 2
    next(button for button in at.button if button.label == "Aprobar").click().run()
    repo = Repository(tmp_path / "data" / "story.sqlite3")
    try:
        sid = repo.list_sessions()[0]["id"]
        mid = repo.memories(sid)[0]["id"]
        at.multiselect[0].set_value([mid]).run()
        at.chat_input[0].set_value("¿Qué recuerdas?").run()
        assert not at.exception
        assert repo.session(sid)["selection"] == [mid]
        assert repo.history(sid)[-1]["result"]["context_report"]["actor"]["included_memory_ids"] == [mid]
        at.multiselect[0].set_value([]).run()
        at.chat_input[0].set_value("Seguimos.").run()
        assert not at.exception
        assert repo.session(sid)["selection"] == []
        at.radio[0].set_value("Modelo local").run()
        assert at.chat_input[0].disabled
        assert not at.exception
    finally:
        repo.close()
