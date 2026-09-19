import json
import sqlite3

import pytest

from ficcion.cli import load_seed
from ficcion.demo import DemoBackend
from ficcion.engine import FictionEngine
from ficcion.models import TurnRequest
from ficcion.storage import Repository


def test_import_before_first_turn_deduplicates_and_keeps_ownership(tmp_path):
    seed = load_seed().model_dump()
    seed["selected_character_cards"].append({**seed["selected_character_cards"][0], "key": "dante", "name": "Dante"})
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(seed)
        chars = engine.repository.character_cards(sid)
        iria, dante = list(chars)
        a = engine.import_text(sid, "iria.txt", b"DOCUMENTO_PRIVADO_IRIA_836", character_id=iria)
        b = engine.import_text(sid, "dante.txt", b"DOCUMENTO_PRIVADO_DANTE_994", character_id=dante)
        again = engine.import_text(sid, "iria.txt", b"DOCUMENTO_PRIVADO_IRIA_836", character_id=iria)
        assert again["reused"] and again["memory_ids"] == a["memory_ids"]
        engine.run_turn(TurnRequest(session_id=sid, turn_id="first", user_input="Hola", focus_character_id=iria,
            selected_memory_ids=a["memory_ids"] + b["memory_ids"]))
        actor = next(c for c in engine.roles.audit if c["role"] == "actor")
        assert "DOCUMENTO_PRIVADO_IRIA_836" in json.dumps(actor)
        assert "DOCUMENTO_PRIVADO_DANTE_994" not in json.dumps(actor)
        director = next(c for c in engine.roles.audit if c["role"] == "director")
        assert "DOCUMENTO_PRIVADO_" not in json.dumps(director)
        exported = engine.repository.export_session(sid)
        assert len(exported["documents"]) == 2
        assert exported["documents"][0]["sha256"]


def test_large_utf8_document_keeps_all_text_and_style_stays_out_of_archivist(tmp_path):
    content = ("Voz de referencia: alegría, café y galaxias.\n" * 110) + "FINAL_DEL_DOCUMENTO"
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(load_seed())
        cid = next(iter(engine.repository.character_cards(sid)))
        imported = engine.import_text(sid, "voz.txt", content.encode("utf-8-sig"), character_id=cid, kind="style")
        memories = engine.repository.select_memories(sid, imported["memory_ids"])
        assert len(memories) > 1
        assert "".join(m["text"].split("\n", 1)[1] for m in memories) == content
        assert all(m["kind"] == "style" and len(m["text"]) <= 2000 and m["sources"] for m in memories)
        engine.run_turn(TurnRequest(session_id=sid, turn_id="first", user_input="Hola", selected_memory_ids=imported["memory_ids"]))
        calls = {c["role"]: c for c in engine.roles.audit}
        actor_payload = json.loads(calls["actor"]["messages"][1]["content"])
        assert actor_payload["character_memories"][0]["kind"] == "style"
        assert "no establecen hechos" in calls["actor"]["messages"][0]["content"]
        archivist = json.loads(calls["archivist"]["messages"][1]["content"])
        assert archivist["existing_memory_summaries"] == []


@pytest.mark.parametrize("filename,data", [("binary.txt", b"\xff\xfe"), ("empty.txt", b"  "), ("file.py", b"print(1)"), ("large.txt", b"x" * (512*1024+1))])
def test_invalid_upload_creates_no_partial_memories(tmp_path, filename, data):
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(load_seed())
        cid = next(iter(engine.repository.character_cards(sid)))
        with pytest.raises(ValueError):
            engine.import_text(sid, filename, data, character_id=cid)
        assert engine.repository.memories(sid) == []


def test_v010_memory_table_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "story.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memories(id TEXT PRIMARY KEY,session_id TEXT,scope TEXT,character_id TEXT,text TEXT,approved INTEGER,sources TEXT,created_at TEXT)")
        db.execute("INSERT INTO memories VALUES('old','session','character','iria','Recuerdo previo',1,'[]','2026-09-10')")
    repo = Repository(path)
    row = repo.connection.execute("SELECT text,kind FROM memories WHERE id='old'").fetchone()
    assert tuple(row) == ("Recuerdo previo", "knowledge")
    repo.close()
