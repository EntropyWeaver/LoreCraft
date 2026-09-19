"""Construye proyecciones por audiencia antes de que ningún LLM lea el contexto."""
from __future__ import annotations

import json
from .llm import ContextLimitError


def fit_context(core: dict, memories: list[dict], history: list[dict], limit: int | None) -> tuple[dict, dict]:
    result = dict(core, memories=[], history=[])
    size = lambda: len(json.dumps(result, ensure_ascii=False))
    if limit is not None and size() > limit:
        raise ContextLimitError("El contexto obligatorio excede el presupuesto; reduce la ficha o amplía context_chars.")
    included, omitted = [], []
    # Primero respeta la prioridad manual de los recuerdos; después conserva mensajes recientes.
    for memory in memories:
        view = {"id": memory["id"], "text": memory["text"], "scope": memory["scope"], "kind": memory.get("kind", "knowledge")}
        result["memories"].append(view)
        if limit is not None and size() > limit:
            result["memories"].pop()
            omitted.append(memory["id"])
        else:
            included.append(memory["id"])
    for message in reversed(history):
        result["history"].insert(0, message)
        if limit is not None and size() > limit:
            result["history"].pop(0)
            break
    return result, {"included_memory_ids": included, "omitted_memory_ids": omitted,
                    "history_message_ids": [m["id"] for m in result["history"]],
                    "context_chars": size(), "budget_unit": "characters"}


def scene_view(scenario: dict, events: list[dict], character_id: str | None) -> dict:
    visible = [e for e in events if e["public"] or (character_id and character_id in e["audience"])]
    return {"location": scenario["initial_scene"]["location"],
            "time": scenario["initial_scene"]["time"],
            "public_facts": scenario["initial_scene"]["public_facts"],
            "recent_events": [{"kind": e["kind"], "text": e["text"]} for e in visible[-12:]]}


def visible_history(turns: list[dict], character_id: str | None) -> list[dict]:
    messages = []
    for turn in turns:
        for message in turn["messages"]:
            if message["public"] or (character_id and character_id in message["audience"]):
                messages.append({"id": message["id"], "role": message["role"],
                                 "content": message["content"], "speaker_id": message.get("speaker_id")})
    return messages


def prepare_views(scenario: dict, events: list[dict], memories: list[dict],
                  turns: list[dict], context_chars: int | None) -> tuple[dict, dict, dict]:
    roster = [{"id": cid, "name": scenario["characters"][cid]["name"]}
              for cid in scenario["initial_scene"]["present_character_ids"]]
    public_memories = [m for m in memories if m["scope"] == "scenario"]
    public, public_report = fit_context(
        {"scene": scene_view(scenario, events, None), "present_characters": roster},
        public_memories, visible_history(turns, None), context_chars)
    contexts, reports = {}, {"director": public_report}
    for cid in scenario["initial_scene"]["present_character_ids"]:
        eligible = [m for m in memories if m["scope"] == "scenario" or m["character_id"] == cid]
        contexts[cid], reports[cid] = fit_context(
            {"character_card": {"id": cid, **scenario["characters"][cid]},
             "scene": scene_view(scenario, events, cid), "present_characters": roster},
            eligible, visible_history(turns, cid), context_chars)
    return public, contexts, reports
