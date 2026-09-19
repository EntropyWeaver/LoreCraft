"""SQLite es el archivo de la aplicación; LangGraph usa otro archivo de checkpoints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def character_id_for(session_id: str, key: str) -> str:
    return "c_" + uuid5(NAMESPACE_URL, session_id + ":" + key).hex[:16]


class ConflictError(ValueError):
    pass


class Repository:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY, seed TEXT NOT NULL, scenario TEXT,
            events TEXT NOT NULL DEFAULT '[]', selection TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS requests(
            session_id TEXT NOT NULL REFERENCES sessions(id), turn_id TEXT NOT NULL,
            request_hash TEXT NOT NULL, PRIMARY KEY(session_id, turn_id)
        );
        CREATE TABLE IF NOT EXISTS turns(
            session_id TEXT NOT NULL REFERENCES sessions(id), turn_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL,
            messages TEXT NOT NULL, audit TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(session_id, turn_id), UNIQUE(session_id, ordinal)
        );
        CREATE TABLE IF NOT EXISTS memories(
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            scope TEXT NOT NULL, character_id TEXT, text TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0, sources TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS call_cache(
            session_id TEXT NOT NULL, turn_id TEXT NOT NULL, role TEXT NOT NULL,
            request_hash TEXT NOT NULL, response TEXT NOT NULL,
            PRIMARY KEY(session_id, turn_id, role, request_hash)
        );
        CREATE TABLE IF NOT EXISTS documents(
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
            character_id TEXT, scope TEXT NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
            sha256 TEXT NOT NULL, content TEXT NOT NULL, memory_ids TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(memories)")}
        if "kind" not in columns:
            with self.connection:
                self.connection.execute("ALTER TABLE memories ADD COLUMN kind TEXT NOT NULL DEFAULT 'knowledge'")

    def close(self):
        self.connection.close()

    def create_session(self, seed: dict) -> str:
        session_id = uuid4().hex
        with self.connection:
            self.connection.execute(
                "INSERT INTO sessions(id,seed,created_at) VALUES(?,?,?)",
                (session_id, dumps(seed), now()),
            )
        return session_id

    def session(self, session_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("No existe esa sesión.")
        result = dict(row)
        for key in ("seed", "scenario", "events", "selection"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        return result

    def list_sessions(self) -> list[dict]:
        rows = self.connection.execute("SELECT id,seed,created_at FROM sessions ORDER BY created_at DESC")
        return [{"id": r["id"], "title": json.loads(r["seed"])["title"], "created_at": r["created_at"]} for r in rows]

    def begin_request(self, session_id: str, turn_id: str, request_hash: str):
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO requests VALUES(?,?,?)", (session_id, turn_id, request_hash)
            )
            row = self.connection.execute(
                "SELECT request_hash FROM requests WHERE session_id=? AND turn_id=?", (session_id, turn_id)
            ).fetchone()
            if row[0] != request_hash:
                raise ConflictError("Ese turn_id ya identifica otra entrada o configuración. Usa uno nuevo.")

    def turn(self, session_id: str, turn_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM turns WHERE session_id=? AND turn_id=?", (session_id, turn_id)
        ).fetchone()
        return self._decode_turn(row) if row else None

    @staticmethod
    def _decode_turn(row) -> dict:
        result = dict(row)
        for key in ("request", "result", "messages", "audit"):
            result[key] = json.loads(result[key])
        return result

    def history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM turns WHERE session_id=? ORDER BY ordinal DESC LIMIT ?", (session_id, limit)
        ).fetchall()
        return [self._decode_turn(r) for r in reversed(rows)]

    def memories(self, session_id: str) -> list[dict]:
        self.session(session_id)
        result = []
        for row in self.connection.execute("SELECT * FROM memories WHERE session_id=? ORDER BY created_at,id", (session_id,)):
            item = dict(row)
            item["approved"] = bool(item["approved"])
            item["sources"] = json.loads(item["sources"])
            result.append(item)
        return result

    def select_memories(self, session_id: str, ids: list[str]) -> list[dict]:
        available = {m["id"]: m for m in self.memories(session_id)}
        if len(ids) != len(set(ids)):
            raise ValueError("La selección contiene recuerdos repetidos.")
        for memory_id in ids:
            if memory_id not in available or not available[memory_id]["approved"]:
                raise ValueError("La selección contiene un recuerdo ajeno, inexistente o sin aprobar.")
        return [available[memory_id] for memory_id in ids]

    def approve(self, session_id: str, memory_id: str):
        with self.connection:
            result = self.connection.execute(
                "UPDATE memories SET approved=1 WHERE session_id=? AND id=?", (session_id, memory_id)
            )
            if result.rowcount != 1:
                raise ValueError("No existe ese recuerdo en esta sesión.")

    def add_memory(self, session_id: str, text: str, scope: str, character_id: str | None, approved: bool = True) -> str:
        session = self.session(session_id)
        if not session["scenario"]:
            raise ValueError("Primero hay que crear el escenario con un turno.")
        if scope == "character":
            if character_id not in session["scenario"]["characters"]:
                raise ValueError("Personaje ajeno o inexistente.")
        elif scope != "scenario" or character_id is not None:
            raise ValueError("Ámbito de recuerdo incorrecto.")
        if not text.strip() or len(text) > 2000:
            raise ValueError("El recuerdo debe contener entre 1 y 2000 caracteres.")
        memory_id = uuid4().hex
        with self.connection:
            self.connection.execute("INSERT INTO memories(id,session_id,scope,character_id,text,approved,sources,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (memory_id, session_id, scope, character_id, text, int(approved), "[]", now()))
        return memory_id

    def cached_call(self, session_id: str, turn_id: str, role: str, request_hash: str) -> str | None:
        row = self.connection.execute("SELECT response FROM call_cache WHERE session_id=? AND turn_id=? AND role=? AND request_hash=?",
            (session_id, turn_id, role, request_hash)).fetchone()
        return row[0] if row else None

    def cache_call(self, session_id: str, turn_id: str, role: str, request_hash: str, response: str):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO call_cache VALUES(?,?,?,?,?)",
                (session_id, turn_id, role, request_hash, response))

    def commit_turn(self, session: dict, request: dict, result: dict, scenario: dict,
                    events: list[dict], memories: list[dict], messages: list[dict], audit: list[dict]):
        with self.connection:
            if self.turn(session["id"], request["turn_id"]):
                return
            changed = self.connection.execute(
                "UPDATE sessions SET scenario=?,events=?,selection=?,version=version+1 WHERE id=? AND version=?",
                (dumps(scenario), dumps(events), dumps(request["selected_memory_ids"]), session["id"], session["version"])
            )
            if changed.rowcount != 1:
                raise ConflictError("La sesión ha cambiado durante la generación. Recárgala y usa un nuevo turno.")
            self.connection.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)",
                (session["id"], request["turn_id"], session["version"] + 1, dumps(request),
                 dumps(result), dumps(messages), dumps(audit), now()))
            for memory in memories:
                self.connection.execute("INSERT INTO memories(id,session_id,scope,character_id,text,approved,sources,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (memory["id"], session["id"], memory["scope"], memory["character_id"], memory["text"],
                     0, dumps(memory["source_message_ids"]), now()))

    def export_session(self, session_id: str) -> dict:
        return {"session": self.session(session_id), "memories": self.memories(session_id),
                "documents": [dict(row, memory_ids=json.loads(row["memory_ids"])) for row in
                    self.connection.execute("SELECT * FROM documents WHERE session_id=?", (session_id,))],
                "turns": self.history(session_id, limit=1000000)}

    def character_cards(self, session_id: str) -> dict:
        session = self.session(session_id)
        if session["scenario"]:
            return session["scenario"]["characters"]
        return {character_id_for(session_id, c["key"]): c for c in session["seed"]["selected_character_cards"]}

    def import_text(self, session_id: str, filename: str, data: bytes, scope: str, character_id: str | None, kind: str) -> dict:
        """Importación atómica e idempotente; el fichero completo queda archivado."""
        self.session(session_id)
        if scope == "character":
            if character_id not in self.character_cards(session_id):
                raise ValueError("El personaje no pertenece a esta historia.")
        elif scope != "scenario" or character_id is not None:
            raise ValueError("Ámbito de documento incorrecto.")
        if kind not in {"knowledge", "style"} or (kind == "style" and scope != "character"):
            raise ValueError("Los ejemplos de estilo deben pertenecer a un personaje.")
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not filename.lower().endswith(".txt") or len(filename) > 200:
            raise ValueError("Elige un archivo .txt con un nombre de hasta 200 caracteres.")
        if len(data) > 512 * 1024:
            raise ValueError("Este prototipo admite archivos de hasta 512 KiB.")
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Guarda el TXT con codificación UTF-8.") from exc
        if not content.strip() or "\x00" in content:
            raise ValueError("El archivo está vacío o contiene datos binarios.")
        sha = hashlib.sha256(data).hexdigest()
        existing = self.connection.execute("SELECT id,memory_ids FROM documents WHERE session_id=? AND character_id IS ? AND scope=? AND kind=? AND sha256=?",
            (session_id, character_id, scope, kind, sha)).fetchone()
        if existing:
            return {"document_id": existing["id"], "memory_ids": json.loads(existing["memory_ids"]), "reused": True}
        doc_id, parts = uuid4().hex, []
        # Respeta saltos de línea cuando es posible y conserva todos los caracteres.
        remaining = content
        while remaining:
            end = min(1600, len(remaining))
            if end < len(remaining):
                boundary = remaining.rfind("\n", 0, end)
                if boundary > 800:
                    end = boundary + 1
            parts.append(remaining[:end])
            remaining = remaining[end:]
        ids = [uuid4().hex for _ in parts]
        with self.connection:
            self.connection.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)",
                (doc_id, session_id, character_id, scope, kind, filename, sha, content, dumps(ids), now()))
            for index, (mid, part) in enumerate(zip(ids, parts), 1):
                text = f"[{filename} · fragmento {index}/{len(parts)}]\n{part}"
                self.connection.execute("INSERT INTO memories(id,session_id,scope,character_id,text,approved,sources,created_at,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                    (mid, session_id, scope, character_id, text, 1, dumps([f"document:{doc_id}:{index}"]), now(), kind))
        return {"document_id": doc_id, "memory_ids": ids, "reused": False}
