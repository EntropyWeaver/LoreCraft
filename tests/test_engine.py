"""Pruebas de integración: grafo real, SQLite real y generación controlada."""
import json

import pytest

from ficcion.cli import load_seed
from ficcion.context import fit_context
from ficcion.demo import DemoBackend
from ficcion.engine import (FictionEngine, exclusive_run, interaction_constraints,
                            validate_actor_boundaries)
from ficcion.llm import ContextLimitError, ModelError
from ficcion.models import TurnRequest
from ficcion.storage import ConflictError


def request(sid, tid="t1", **kwargs):
    return TurnRequest(session_id=sid, turn_id=tid, user_input=kwargs.pop("user_input", "¿Qué ocurre?"), **kwargs)


def test_withdrawal_constraint_is_specific_and_requires_visible_compliance():
    assert interaction_constraints("Para llegar al transmisor, usa el verde") == []
    constraints = interaction_constraints("Para. Ya no quiero seguir. Aléjate ahora")
    assert constraints and constraints[0].startswith("STOP_AND_DISTANCE:")
    with pytest.raises(ValueError, match="detiene el contacto"):
        validate_actor_boundaries("Iria mantiene la cercanía y te acaricia los hombros.", constraints)
    with pytest.raises(ValueError, match="crea distancia"):
        validate_actor_boundaries("Iria se detiene justo antes de besarte, pero permanece muy cerca.", constraints)
    validate_actor_boundaries("Iria se detiene y da un paso atrás, dejando espacio entre ambos.", constraints)


def payload(backend, role):
    call = next(call for call in reversed(backend.calls) if call["role"] == role)
    return json.loads(call["messages"][1]["content"])


def two_character_seed():
    seed = load_seed().model_dump()
    iria = seed["selected_character_cards"][0]
    iria["private_secrets"] = ["IRIA_SECRETO_827: esconde una pieza de repuesto."]
    iria["known_facts"] = ["IRIA_SABE_635: el relé cambió ayer."]
    seed["selected_character_cards"].append({
        **iria, "key": "leo", "name": "Leo", "identity": "Técnico de comunicaciones, 38 años",
        "voice": "Formal y paciente", "private_secrets": ["LEO_SECRETO_914: tiene una carta oculta."],
        "known_facts": ["LEO_SABE_293: la antena norte está desconectada."]})
    return seed


def test_complete_turn_persists_and_reopens(tmp_path):
    backend = DemoBackend()
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(load_seed())
        result = engine.run_turn(request(sid, private_thoughts="NOTA_PRIVADA_452"))
        assert result.trace == ["load_session", "create_scenario", "prepare_context", "direct_turn",
                                "play_character", "update_memory", "save_turn"]
        assert [c["role"] for c in backend.calls] == ["scenario", "director", "actor", "archivist"]
        assert "si quieres" in result.reply  # La demo ofrece una posibilidad al jugador.
        assert len(engine.repository.history(sid)) == 1
        assert len(result.pending_memory_ids) == 1
        assert not engine.repository.memories(sid)[0]["approved"]
        assert "NOTA_PRIVADA_452" not in json.dumps(backend.calls)
        assert engine.repository.turn(sid, "t1")["request"]["private_thoughts"] == "NOTA_PRIVADA_452"
        checkpoint = engine.checkpointer.get_tuple({"configurable": {"thread_id": sid}})
        assert checkpoint is not None
    assert (tmp_path / "story.sqlite3").is_file()
    assert (tmp_path / "checkpoints.sqlite3").is_file()
    second = DemoBackend()
    with FictionEngine(tmp_path, second) as engine:
        result2 = engine.run_turn(request(sid, "t2"))
        assert "create_scenario" not in result2.trace
        assert result2.focus_character_id == result.focus_character_id
        assert [c["role"] for c in second.calls] == ["director", "actor", "archivist"]
        assert len(engine.repository.history(sid)) == 2
        assert {m["id"] for m in payload(second, "actor")["visible_history"]} == {"t1:user", "t1:assistant"}
        assert "t2:user" not in result2.context_report["actor"]["history_message_ids"]


def test_memory_selection_persists_and_empty_list_replaces_it(tmp_path):
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(load_seed())
        engine.run_turn(request(sid))
        mid = engine.add_memory(sid, "RECUERDO_ELEGIDO_631: la luz verde funciona.")
        ignored = engine.add_memory(sid, "RECUERDO_OMITIDO_962: la luz roja funciona.")
        result = engine.run_turn(request(sid, "t2", selected_memory_ids=[mid]))
        assert result.context_report["actor"]["included_memory_ids"] == [mid]
        assert "RECUERDO_OMITIDO_962" not in json.dumps(engine.roles.audit)
        assert ignored not in engine.repository.session(sid)["selection"]
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        continued = engine.run_turn(request(sid, "t3"))
        assert continued.context_report["actor"]["included_memory_ids"] == [mid]
        cleared = engine.run_turn(request(sid, "t4", selected_memory_ids=[]))
        assert cleared.context_report["actor"]["included_memory_ids"] == []
        assert engine.repository.session(sid)["selection"] == []
        assert payload(engine.backend, "actor")["character_memories"] == []
        # Deseleccionar no borra una mención ya escrita en el historial.
        assert "RECUERDO_ELEGIDO_631" in json.dumps(payload(engine.backend, "actor")["visible_history"])


def test_characters_receive_only_their_knowledge_and_visible_history(tmp_path):
    backend = DemoBackend()
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(two_character_seed())
        initial = engine.run_turn(request(sid))
        chars = engine.repository.session(sid)["scenario"]["characters"]
        iria = initial.focus_character_id
        leo = next(cid for cid in chars if cid != iria)
        actor = json.dumps(payload(backend, "actor"))
        assert "IRIA_SECRETO_827" in actor and "IRIA_SABE_635" in actor
        assert "LEO_SECRETO_914" not in actor and "LEO_SABE_293" not in actor
        director = json.dumps(payload(backend, "director"))
        assert "SECRETO_" not in director and "SABE_" not in director
        mid = engine.add_memory(sid, "RECUERDO_DE_LEO_345", "character", leo)
        backend.calls.clear()
        engine.run_turn(request(sid, "private", user_input="SUSURRO_SOLO_IRIA_571",
            private_thoughts="PENSAMIENTO_JUGADOR_318", visibility="private", focus_character_id=iria,
            selected_memory_ids=[mid]))
        assert "SUSURRO_SOLO_IRIA_571" in json.dumps(payload(backend, "actor"))
        assert "RECUERDO_DE_LEO_345" not in json.dumps(payload(backend, "actor"))
        assert "SUSURRO_SOLO_IRIA_571" not in json.dumps(payload(backend, "director"))
        assert "PENSAMIENTO_JUGADOR_318" not in json.dumps(backend.calls)
        backend.calls.clear()
        engine.run_turn(request(sid, "leo", focus_character_id=leo))
        actor = json.dumps(payload(backend, "actor"))
        assert "LEO_SECRETO_914" in actor and "RECUERDO_DE_LEO_345" in actor
        assert "IRIA_SECRETO_827" not in actor
        assert "SUSURRO_SOLO_IRIA_571" not in actor
        assert "private:user" not in {m["id"] for m in payload(backend, "actor")["visible_history"]}
        engine.run_turn(request(sid, "iria-again", focus_character_id=iria))
        assert "SUSURRO_SOLO_IRIA_571" in json.dumps(payload(backend, "actor")["visible_history"])


def test_pending_and_foreign_memories_are_rejected_before_generation(tmp_path):
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(load_seed())
        result = engine.run_turn(request(sid))
        pending = result.pending_memory_ids[0]
        other_sid = engine.create_session(load_seed())
        engine.run_turn(request(other_sid))
        foreign = engine.add_memory(other_sid, "Dato de otra historia")
        engine.backend.calls.clear()
        for index, mid in enumerate([pending, foreign]):
            with pytest.raises(ValueError, match="ajeno, inexistente o sin aprobar"):
                engine.run_turn(request(sid, f"invalid-{index}", selected_memory_ids=[mid]))
        assert engine.backend.calls == []
        engine.approve_memory(sid, pending)
        result = engine.run_turn(request(sid, "approved", selected_memory_ids=[pending]))
        assert pending in result.context_report["actor"]["included_memory_ids"]


def test_turn_id_replay_and_conflict(tmp_path):
    backend = DemoBackend()
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(load_seed())
        first = engine.run_turn(request(sid))
        backend.calls.clear()
        assert engine.run_turn(request(sid)) == first
        assert backend.calls == []
        assert len(engine.repository.history(sid)) == 1
        with pytest.raises(ConflictError):
            engine.run_turn(request(sid, user_input="Una entrada distinta"))
        with pytest.raises(ConflictError):
            with FictionEngine(tmp_path, DemoBackend(), context_chars=17000) as changed:
                changed.run_turn(request(sid))


def test_changing_backend_keeps_scenario_and_selected_memories(tmp_path):
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        sid = engine.create_session(load_seed())
        original = engine.run_turn(request(sid))
        mid = engine.add_memory(sid, "La reparación sigue pendiente.")
        engine.run_turn(request(sid, "t2", selected_memory_ids=[mid]))
    changed = DemoBackend()
    changed.identity = "otro-backend-de-prueba"
    with FictionEngine(tmp_path, changed) as engine:
        result = engine.run_turn(request(sid, "t3"))
        assert result.model == changed.identity
        assert result.focus_character_id == original.focus_character_id
        assert result.context_report["actor"]["included_memory_ids"] == [mid]
        assert "scenario" not in [c["role"] for c in changed.calls]


class MutatingBackend(DemoBackend):
    def __init__(self, role, mutate):
        super().__init__()
        self.target, self.mutate = role, mutate
        self.enabled = True

    def complete(self, role, messages, schema, max_tokens):
        raw = super().complete(role, messages, schema, max_tokens)
        if self.enabled and role == self.target:
            return json.dumps(self.mutate(json.loads(raw)))
        return raw


@pytest.mark.parametrize("violation", ["source", "audience", "public_memory"])
def test_archivist_rejects_invalid_provenance_without_partial_commit(tmp_path, violation):
    def corrupt(value):
        if violation == "source":
            value["scene_event_candidates"][0]["source_message_ids"] = ["invented:assistant"]
        elif violation == "audience":
            value["scene_event_candidates"][0]["observed_by_character_ids"] = ["absent_character"]
        else:
            value["memory_candidates"][0].update(scope="scenario", character_id=None)
        return value

    backend = MutatingBackend("archivist", corrupt)
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(load_seed())
        with pytest.raises(ModelError, match="archivist.*reintento"):
            engine.run_turn(request(sid, visibility="private"))
        assert engine.repository.history(sid) == []
        assert engine.repository.session(sid)["scenario"] is None
        assert engine.repository.session(sid)["events"] == []
        assert engine.repository.memories(sid) == []
        assert len([c for c in backend.calls if c["role"] == "archivist"]) == 2
        backend.enabled = False
        backend.calls.clear()
        engine.run_turn(request(sid, visibility="private"))
        assert [c["role"] for c in backend.calls] == ["archivist"]
        audit = engine.repository.turn(sid, "t1")["audit"][0]["calls"]
        assert [c["cached"] for c in audit] == [True, True, True, False]
        assert len(engine.repository.history(sid)) == 1


def test_invalid_director_never_reaches_actor(tmp_path):
    backend = MutatingBackend("director", lambda value: {**value, "focus_character_id": "unknown"})
    with FictionEngine(tmp_path, backend) as engine:
        sid = engine.create_session(load_seed())
        with pytest.raises(ModelError, match="director"):
            engine.run_turn(request(sid))
        assert "actor" not in [c["role"] for c in backend.calls]
        assert engine.repository.history(sid) == []


def test_contradictions_keep_dialogue_without_applying_proposals(tmp_path):
    def contradiction(value):
        value["contradictions"] = [{"description": "No está claro si el relé funciona.",
                                    "source_message_ids": ["t1:assistant"]}]
        return value
    with FictionEngine(tmp_path, MutatingBackend("archivist", contradiction)) as engine:
        sid = engine.create_session(load_seed())
        result = engine.run_turn(request(sid))
        assert result.reply and result.warnings
        assert result.pending_memory_ids == []
        assert engine.repository.session(sid)["events"] == []
        assert len(engine.repository.history(sid)) == 1


def test_scenario_cannot_rewrite_selected_character(tmp_path):
    def rewrite(value):
        value["characters"][0]["voice"] = "Una voz no elegida"
        return value
    with FictionEngine(tmp_path, MutatingBackend("scenario", rewrite)) as engine:
        sid = engine.create_session(load_seed())
        with pytest.raises(ModelError, match="fichas seleccionadas"):
            engine.run_turn(request(sid))
        assert engine.repository.session(sid)["scenario"] is None


def test_context_omissions_are_visible_and_core_is_never_silently_cut():
    memories = [{"id": "large", "text": "x" * 2000, "scope": "scenario"},
                {"id": "small", "text": "y", "scope": "scenario"}]
    view, report = fit_context({"scene": "taller"}, memories, [], 200)
    assert report["omitted_memory_ids"] == ["large"]
    assert report["included_memory_ids"] == ["small"]
    assert view["memories"][0]["text"] == "y"
    with pytest.raises(ContextLimitError):
        fit_context({"mandatory": "x" * 201}, [], [], 200)


def test_lock_prevents_concurrent_mutation(tmp_path):
    with FictionEngine(tmp_path, DemoBackend()) as engine:
        with exclusive_run(engine.lock_path):
            with pytest.raises(RuntimeError, match="otra operación"):
                engine.create_session(load_seed())
        assert engine.create_session(load_seed())
