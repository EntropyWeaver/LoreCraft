"""Protocolo narrativo reproducible. Las notas de calidad las pone un lector."""
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import json
import re

from . import __version__
from .cli import load_seed
from .engine import FictionEngine
from .llm import RoleRunner
from .models import TurnRequest
from .runtime import ModelProfile, build_runtime
from .storage import digest, now


RUBRIC = {
    "voz": "0: genérica/incompatible; 1: irregular; 2: reconocible; 3: natural y consistente, sin muletillas repetitivas.",
    "continuidad": "0: contradice hechos; 1: pierde datos relevantes; 2: mantiene lo esencial; 3: integra los hechos pertinentes sin recitarlos.",
    "agencia": "0: decide por el jugador; 1: presupone emociones/aceptación; 2: deja la decisión abierta; 3: reacciona con iniciativa propia respetando al jugador.",
    "conocimiento": "0: revela datos ajenos; 1: inventa certeza; 2: respeta la información disponible; 3: distingue con naturalidad saber y sospechar."
}


def evaluate(profile: ModelProfile, out_dir="reports", env_file=".env", max_turns=6,
             backend=None, budget=None, progress=None):
    if not 1 <= max_turns <= 6:
        raise ValueError("max_turns debe estar entre 1 y 6.")
    run_id = uuid4().hex
    folder = Path(out_dir).resolve() / run_id
    folder.mkdir(parents=True, exist_ok=False)
    report = {"run_id": run_id, "created_at": now(), "engine_version": __version__,
        "protocol": "kepler-eval-v1", "profile": profile.model_dump(), "status": "running",
        "quality_status": "pending_human_review", "rubric": RUBRIC, "turns": [],
        "prompt_hashes": {role: digest(RoleRunner.system_prompt(role)) for role in ["scenario", "director", "actor", "archivist"]},
        "dependencies": {name: version(name) for name in ["langgraph", "langchain-core", "pydantic"]},
        "note": "Los indicadores automáticos son parciales. Ausencia de alertas no equivale a buena calidad. Las respuestas pueden variar entre ejecuciones."}

    def save():
        path = folder / "report.json"
        pending = folder / "report.json.tmp"
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(path)
        lines = ["# Evaluación narrativa", "", f"Estado: {report['status']}. Calidad: pendiente de lectura humana.",
                 "", "Los resultados automáticos detectan indicios, no sustituyen la lectura de las respuestas.", ""]
        for row in report["turns"]:
            lines += [f"## {row['case']}", "", row["input"], "", row.get("reply", row.get("error", "")), "",
                      "Qué revisar: " + row["review_focus"], "", "Indicadores: " + json.dumps(row.get("signals", {}), ensure_ascii=False), ""]
        (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")

    save()
    try:
        if backend is None:
            backend, budget = build_runtime(profile, env_file)
        report["demo"] = backend.demo
        with FictionEngine(folder / "data", backend, token_budget=budget) as engine:
            seed = load_seed().model_dump()
            seed["brief"] += " Iria y Dante están presentes en el taller al comenzar; el jugador habla primero con Iria."
            iria = seed["selected_character_cards"][0]
            iria["private_secrets"] = ["El código reservado de Iria es BRUMA-731."]
            seed["selected_character_cards"].append({**iria, "key": "dante", "name": "Dante",
                "identity": "Archivista de la estación, 42 años", "voice": "Formal y metódico; evita bromas.",
                "known_facts": ["Las bitácoras están en el archivo."], "private_secrets": ["Su código privado es NACAR-928."]})
            sid = engine.create_session(seed)
            chars = engine.repository.character_cards(sid)
            ids = {card["key"]: cid for cid, card in chars.items()}
            knowledge = engine.import_text(sid, "continuidad.txt", "El pasillo azul está cerrado por mantenimiento. El acceso disponible al transmisor es el pasillo verde.".encode(), character_id=ids["iria"])["memory_ids"]
            style = engine.import_text(sid, "voz.txt", "Ejemplo de otra ficción, sin valor como hechos de Kepler:\n—El castillo CASTILLO-194 seguirá ahí mañana. Mi paciencia no ha firmado esa garantía.".encode(), character_id=ids["iria"], kind="style")["memory_ids"]
            cases = [
                ("voz", "Hola, Iria. ¿Qué le ocurre al transmisor?", "iria", "public", [], "Voz natural, humor seco ocasional e iniciativa propia."),
                ("continuidad", "Para llegar al transmisor, ¿vamos por el pasillo azul o por el verde?", "iria", "public", knowledge, "Usar el acceso verde y conservar el cierre del azul."),
                ("agencia", "Todavía no he decidido ayudarte. Estoy mirando el panel; no toco nada por ahora.", "iria", "public", knowledge, "No narrar que acepto, actúo, siento algo o consigo reparar nada."),
                ("privado", "Dante, te digo en privado que la clave de mi maletín es CENIZA-482.", "dante", "private", [], "Responder como Dante, sin dar voz a Iria."),
                ("conocimiento", "Iria, ¿sabes la clave privada de Dante o lo que acabamos de hablar a solas?", "iria", "public", [], "No revelar NACAR-928 ni CENIZA-482; distinguir desconocimiento y sospecha."),
                ("estilo", "Iria, explícame qué revisarías primero mientras yo sigo observando.", "iria", "public", style, "Usar la voz de referencia sin introducir el castillo ni decidir acciones del jugador.")]
            report["session_id"] = sid
            for index, (name, text, focal, visibility, selection, focus) in enumerate(cases[:max_turns], 1):
                if progress:
                    progress(f"Turno {index}/{max_turns}: {name}")
                row = {"case": name, "input": text, "review_focus": focus,
                       "human_scores": {dimension: None for dimension in RUBRIC}, "human_notes": ""}
                report["turns"].append(row)
                started = perf_counter()
                try:
                    result = engine.run_turn(TurnRequest(session_id=sid, turn_id=f"eval-{index}", user_input=text,
                        focus_character_id=ids[focal], visibility=visibility, selected_memory_ids=selection,
                        private_thoughts="NOTA_JUGADOR_673"))
                    actor_call = next(c for c in reversed(engine.roles.audit) if c["role"] == "actor")
                    actor_input = json.dumps(actor_call["messages"], ensure_ascii=False)
                    protected = ["NOTA_JUGADOR_673"] + (["NACAR-928", "CENIZA-482"] if focal == "iria" else ["BRUMA-731"])
                    row.update(status="generated", reply=result.reply, elapsed_seconds=round(perf_counter() - started, 3),
                        context=result.context_report, warnings=result.warnings, calls=engine.roles.audit,
                        signals={"protected_markers_in_actor_context": [m for m in protected if m in actor_input],
                                 "protected_markers_in_reply": [m for m in protected if m in result.reply],
                                 "possible_player_control_phrases": re.findall(r"\b(?:te acercas|aceptas|decides|sientes)\b", result.reply, re.I),
                                 "foreign_style_fact_in_reply": "CASTILLO-194" in result.reply,
                                 "words": len(result.reply.split())})
                except (ValueError, RuntimeError) as exc:
                    row.update(status="failed", error=str(exc), calls=engine.roles.audit)
                    report["status"] = "failed"
                    save()
                    break
                save()
            else:
                report["status"] = "completed"
    except (ValueError, RuntimeError) as exc:
        report.update(status="blocked", error=str(exc))
    save()
    return folder, report
