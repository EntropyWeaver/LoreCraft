"""Los siete nodos de la especificación, con un intérprete focal por turno."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .context import prepare_views, scene_view
from .budget import TokenBudget
from .llm import Backend, RoleRunner
from .models import ArchiveProposal, ScenarioDraft, ScenarioSeed, TurnPlan, TurnRequest, TurnResult
from .storage import Repository, character_id_for, digest


WITHDRAWAL_RE = re.compile(
    r"(?:\b(?:detente|al[eé]jate|no sigas|no quiero seguir)\b|(?:^|[«“\".!?]\s*)para[.!?,:;»”\"])", re.I)
STOP_ACTION_RE = re.compile(
    r"\b(?:se aparta|se aleja|retrocede|se detiene|se queda quiet[oa]|te suelta|"
    r"retira (?:las manos|el contacto)|deja de tocar|rompe el contacto)\b", re.I)
DISTANCE_RE = re.compile(
    r"\b(?:se aparta|se aleja|retrocede|da un paso atr[aá]s|crea distancia|"
    r"deja (?:espacio|distancia)|mantiene la distancia)\b", re.I)


def interaction_constraints(user_input: str) -> list[str]:
    constraints = []
    if WITHDRAWAL_RE.search(user_input):
        constraints.append(
            "STOP_AND_DISTANCE: el jugador retiró el consentimiento. Detén inmediatamente todo contacto, "
            "crea distancia y no insistas, negocies, seduzcas ni inicies otro contacto en este turno."
        )
    if re.search(r"\bm[aá]s despacio\b", user_input, re.I):
        constraints.append("SLOW_DOWN: reduce el ritmo de inmediato y permanece dentro de cada límite expresado.")
    return constraints


def validate_actor_boundaries(reply: str, constraints: list[str]) -> None:
    withdrawal = any(item.startswith("STOP_AND_DISTANCE:") for item in constraints)
    if withdrawal and (not STOP_ACTION_RE.search(reply) or not DISTANCE_RE.search(reply)):
        raise ValueError(
            "El jugador pidió parar y alejarse, pero la respuesta no muestra de forma inequívoca que "
            "el personaje detiene el contacto y crea distancia."
        )


@contextmanager
def exclusive_run(path: Path):
    """Bloqueo entre procesos. El SO lo libera incluso si el proceso termina."""
    handle = path.open("a+b")
    try:
        try:
            import fcntl
        except ImportError:  # Windows
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Hay otra operación en curso. Espera a que termine.") from exc
        else:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Hay otra operación en curso. Espera a que termine.") from exc
        yield
    finally:
        handle.close()


class NarrativeState(TypedDict, total=False):
    request: dict
    session: dict
    scenario: dict | None
    selected_memories: list[dict]
    public_context: dict
    character_contexts: dict
    context_report: dict
    plan: dict
    reply: str
    messages: list[dict]
    proposal: dict
    trace: list[str]
    result: dict


class PublicOutput(TypedDict):
    result: dict


class FictionEngine:
    def __init__(self, data_dir: str | Path, backend: Backend, context_chars: int = 16000,
                 max_prompt_chars: int = 60000, token_budget: TokenBudget | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.data_dir / "engine.lock"
        self.backend, self.context_chars = backend, context_chars
        self.repository = Repository(self.data_dir / "story.sqlite3")
        self.checkpoint_connection = sqlite3.connect(self.data_dir / "checkpoints.sqlite3", check_same_thread=False)
        self.checkpointer = SqliteSaver(self.checkpoint_connection)
        self.roles = RoleRunner(backend, self.repository, max_prompt_chars, token_budget)
        self.graph = self._build_graph()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.repository.close()
        self.checkpoint_connection.close()
        if self.roles.token_budget:
            self.roles.token_budget.close()
        if hasattr(self.backend, "close"):
            self.backend.close()

    def create_session(self, seed: ScenarioSeed | dict) -> str:
        seed = ScenarioSeed.model_validate(seed)
        with exclusive_run(self.lock_path):
            return self.repository.create_session(seed.model_dump())

    def approve_memory(self, session_id: str, memory_id: str):
        with exclusive_run(self.lock_path):
            self.repository.approve(session_id, memory_id)

    def add_memory(self, session_id: str, text: str, scope: str = "scenario",
                   character_id: str | None = None) -> str:
        with exclusive_run(self.lock_path):
            return self.repository.add_memory(session_id, text, scope, character_id)

    def import_text(self, session_id: str, filename: str, data: bytes, scope="character",
                    character_id: str | None = None, kind="knowledge"):
        with exclusive_run(self.lock_path):
            return self.repository.import_text(session_id, filename, data, scope, character_id, kind)

    def run_turn(self, request: TurnRequest | dict) -> TurnResult:
        request = TurnRequest.model_validate(request)
        with exclusive_run(self.lock_path):
            session = self.repository.session(request.session_id)
            # Hash antes de resolver selection=None: un reintento mantiene la misma identidad.
            fingerprint = {"request": request.model_dump(), "model": self.backend.identity,
                           "context_chars": self.context_chars, "max_prompt_chars": self.roles.max_prompt_chars}
            if self.roles.token_budget:
                fingerprint["token_budget"] = self.roles.token_budget.fingerprint()
            request_hash = digest(fingerprint)
            self.repository.begin_request(request.session_id, request.turn_id, request_hash)
            saved = self.repository.turn(request.session_id, request.turn_id)
            if saved:
                return TurnResult.model_validate(saved["result"])
            selection = session["selection"] if request.selected_memory_ids is None else request.selected_memory_ids
            self.repository.select_memories(request.session_id, selection)
            request = request.model_copy(update={"selected_memory_ids": selection})
            self.roles.audit = []
            state = self.graph.invoke({"request": request.model_dump()},
                config={"configurable": {"thread_id": request.session_id}, "recursion_limit": 20})
            return TurnResult.model_validate(state["result"])

    def _build_graph(self):
        builder = StateGraph(NarrativeState, output_schema=PublicOutput)
        names = ["load_session", "create_scenario", "prepare_context", "direct_turn",
                 "play_character", "update_memory", "save_turn"]
        for name in names:
            builder.add_node(name, getattr(self, name))
        builder.add_edge(START, "load_session")
        builder.add_conditional_edges("load_session",
            lambda state: "create_scenario" if state["scenario"] is None else "prepare_context",
            {"create_scenario": "create_scenario", "prepare_context": "prepare_context"})
        for before, after in zip(names[1:], names[2:]):
            builder.add_edge(before, after)
        builder.add_edge("save_turn", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _llm(self, state, role, payload, output_type=None, validate=None, max_tokens=2048):
        request = state["request"]
        return self.roles.generate(request["session_id"], request["turn_id"], role, payload,
                                   output_type, validate, max_tokens)

    @staticmethod
    def _step(state, name, **updates):
        return {"trace": state["trace"] + [name], **updates}

    def load_session(self, state):
        request = state["request"]
        session = self.repository.session(request["session_id"])
        return {"session": session, "scenario": session["scenario"],
                "selected_memories": self.repository.select_memories(session["id"], request["selected_memory_ids"]),
                "trace": ["load_session"], "public_context": {}, "character_contexts": {},
                "context_report": {}, "plan": {}, "reply": "", "messages": [], "proposal": {}, "result": {}}

    def create_scenario(self, state):
        seed = state["session"]["seed"]

        def validate(draft):
            prescribed = {c["key"]: c for c in seed["selected_character_cards"]}
            actual = {c.key: c.model_dump() for c in draft.characters}
            if prescribed and prescribed != actual:
                raise ValueError("Conserva exactamente las fichas seleccionadas y su reparto.")

        draft = self._llm(state, "scenario", seed, ScenarioDraft, validate, max_tokens=4096)
        scenario = draft.model_dump()
        mapping = {c.key: character_id_for(state["session"]["id"], c.key)
                   for c in draft.characters}
        scenario["id"] = "s_" + state["session"]["id"]
        scenario["characters"] = {mapping[c.key]: c.model_dump() for c in draft.characters}
        scene = scenario["initial_scene"]
        scene["present_character_ids"] = [mapping[key] for key in scene.pop("present_character_keys")]
        return self._step(state, "create_scenario", scenario=scenario)

    def prepare_context(self, state):
        request, scenario = state["request"], state["scenario"]
        present = scenario["initial_scene"]["present_character_ids"]
        focus = request["focus_character_id"]
        if focus is not None and focus not in present:
            raise ValueError("El personaje solicitado no está presente en esta escena.")
        if request["visibility"] == "private" and focus is None:
            if len(present) != 1:
                raise ValueError("Para hablar en privado elige un personaje presente.")
            request = dict(request, focus_character_id=present[0])
        public, characters, reports = prepare_views(scenario, state["session"]["events"],
            state["selected_memories"], self.repository.history(request["session_id"]),
            None if self.roles.token_budget else self.context_chars)
        return self._step(state, "prepare_context", request=request, public_context=public,
                          character_contexts=characters, context_report=reports)

    def direct_turn(self, state):
        request = state["request"]
        limit = state["session"]["seed"]["style_preferences"]["default_max_words"]
        present = state["scenario"]["initial_scene"]["present_character_ids"]

        def validate(plan):
            if plan.focus_character_id not in present:
                raise ValueError("focus_character_id debe pertenecer al reparto presente.")
            if request["focus_character_id"] and plan.focus_character_id != request["focus_character_id"]:
                raise ValueError("Respeta el personaje solicitado explícitamente.")
            if plan.max_words > limit:
                raise ValueError("max_words supera el límite de estilo.")

        public_input = request["user_input"] if request["visibility"] == "public" else "[Intervención privada dirigida al personaje solicitado]"
        plan = self._llm(state, "director", {"public_context": state["public_context"],
            "user_input": public_input, "requested_focus_character_id": request["focus_character_id"],
            "max_words_limit": limit}, TurnPlan, validate, max_tokens=512)
        reports = dict(state["context_report"])
        if self.roles.last_budget_report:
            reports["director"] = self.roles.last_budget_report
        return self._step(state, "direct_turn", plan=plan.model_dump(), context_report=reports)

    def play_character(self, state):
        request, plan = state["request"], state["plan"]
        focal = plan["focus_character_id"]
        view = state["character_contexts"][focal]
        constraints = interaction_constraints(request["user_input"])
        payload = {"character_card": view["character_card"], "character_memories": view["memories"],
                   "visible_scene": {**view["scene"], "present_characters": view["present_characters"]},
                   "visible_history": view["history"], "turn_plan": plan,
                   "style_preferences": state["session"]["seed"]["style_preferences"],
                   "user_input": request["user_input"], "interaction_constraints": constraints}
        reply = self._llm(state, "actor", payload,
                          validate=lambda text: validate_actor_boundaries(text, constraints),
                          max_tokens=max(512, plan["max_words"] * 4))
        if not reply.strip():
            raise ValueError("El intérprete no devolvió texto.")
        public = request["visibility"] == "public"
        audience = state["scenario"]["initial_scene"]["present_character_ids"] if public else [focal]
        messages = [
            {"id": request["turn_id"] + ":user", "role": "user", "content": request["user_input"],
             "public": public, "audience": audience, "speaker_id": "player"},
            {"id": request["turn_id"] + ":assistant", "role": "assistant", "content": reply,
             "public": public, "audience": audience, "speaker_id": focal}]
        reports = dict(state["context_report"])
        if self.roles.last_budget_report:
            reports[focal] = self.roles.last_budget_report
        return self._step(state, "play_character", reply=reply, messages=messages, context_report=reports)

    def update_memory(self, state):
        focal = state["plan"]["focus_character_id"]
        sources = {m["id"]: m for m in state["messages"]}
        character_ids = set(state["scenario"]["characters"])

        def sources_for(ids):
            if not ids or not set(ids) <= sources.keys():
                raise ValueError("Cada propuesta necesita fuentes existentes en este turno.")
            return [sources[mid] for mid in ids]

        def validate(proposal):
            for item in proposal.scene_event_candidates:
                related = sources_for(item.source_message_ids)
                allowed = set.intersection(*(set(m["audience"]) for m in related))
                if not set(item.observed_by_character_ids) <= allowed:
                    raise ValueError("Un evento no puede atribuirse a personajes que no pudieron percibir sus fuentes.")
            for item in proposal.memory_candidates:
                related = sources_for(item.source_message_ids)
                if item.scope == "scenario" and not all(m["public"] for m in related):
                    raise ValueError("Una fuente privada no puede producir memoria pública del escenario.")
                if item.scope == "character" and (item.character_id not in character_ids or
                    not all(item.character_id in m["audience"] for m in related)):
                    raise ValueError("El recuerdo pertenece a un personaje que no pudo conocer sus fuentes.")
            for item in proposal.contradictions:
                sources_for(item.source_message_ids)

        proposal = self._llm(state, "archivist", {
            "previous_scene_state": scene_view(state["scenario"], state["session"]["events"], focal),
            "turn_messages_with_ids": state["messages"], "focus_character_id": focal,
            "visibility_metadata": {m["id"]: {"public": m["public"], "audience": m["audience"]} for m in state["messages"]},
            "existing_memory_summaries": [m for m in state["character_contexts"][focal]["memories"] if m.get("kind") != "style"]},
            ArchiveProposal, validate, max_tokens=2048)
        return self._step(state, "update_memory", proposal=proposal.model_dump())

    def save_turn(self, state):
        request, proposal = state["request"], state["proposal"]
        events = list(state["session"]["events"])
        warnings = []
        new_memories = []
        present = set(state["scenario"]["initial_scene"]["present_character_ids"])
        existing = self.repository.memories(request["session_id"])
        memory_keys = {(m["scope"], m["character_id"], m["text"].strip().casefold()) for m in existing}
        event_keys = {(e["kind"], e["text"].strip().casefold(), tuple(sorted(e["audience"]))) for e in events}
        if proposal["contradictions"]:
            warnings.append("El archivista detectó contradicciones: se guardó el diálogo, sin aplicar las propuestas del turno.")
        else:
            for item in proposal["scene_event_candidates"]:
                key = (item["kind"], item["text"].strip().casefold(), tuple(sorted(item["observed_by_character_ids"])))
                if key not in event_keys:
                    events.append({**item, "audience": item["observed_by_character_ids"],
                        "public": request["visibility"] == "public" and set(item["observed_by_character_ids"]) == present})
                    event_keys.add(key)
            for item in proposal["memory_candidates"]:
                key = (item["scope"], item["character_id"], item["text"].strip().casefold())
                if key not in memory_keys:
                    new_memories.append({"id": uuid4().hex, **item})
                    memory_keys.add(key)
        focal = state["plan"]["focus_character_id"]
        report = {"director": state["context_report"]["director"], "actor": state["context_report"][focal]}
        if any(x["omitted_memory_ids"] for x in report.values()):
            warnings.append("Algunos recuerdos seleccionados no cabían en el contexto. Consulta el inspector.")
        if len(state["reply"].split()) > state["plan"]["max_words"]:
            warnings.append("La respuesta supera la extensión orientativa solicitada.")
        if any(call.get("tokens") and call["tokens"].get("count_matches_usage") is False for call in self.roles.audit):
            warnings.append("El conteo local no coincide con usage.prompt_tokens del servidor. Consulta los deltas en el inspector y revisa la plantilla.")
        trace = state["trace"] + ["save_turn"]
        result = TurnResult(session_id=request["session_id"], turn_id=request["turn_id"], reply=state["reply"],
            focus_character_id=focal, model=self.backend.identity, demo=self.backend.demo,
            pending_memory_ids=[m["id"] for m in new_memories], trace=trace, context_report=report, warnings=warnings)
        audit = [{"calls": self.roles.audit, "proposal": proposal}]
        self.repository.commit_turn(state["session"], request, result.model_dump(), state["scenario"],
                                    events, new_memories, state["messages"], audit)
        return {"trace": trace, "result": result.model_dump()}
