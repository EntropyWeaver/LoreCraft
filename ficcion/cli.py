"""Interfaz de terminal. `python -m ficcion demo` no llama a ningún modelo."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from .demo import DemoBackend
from .engine import FictionEngine
from .llm import LocalBackend, LocalConfig, ModelError
from .models import ScenarioSeed, TurnRequest


def load_seed(path=None):
    if path:
        return ScenarioSeed.model_validate_json(Path(path).read_text(encoding="utf-8"))
    from importlib.resources import files
    return ScenarioSeed.model_validate_json(files("ficcion").joinpath("kepler.json").read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="LoreCraft: ficción interactiva con memoria selectiva")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["demo", "new", "turn", "memories", "remember", "approve", "export", "characters", "import-txt", "doctor", "eval"]:
        sub = commands.add_parser(name)
        sub.add_argument("--data-dir", default="demo_data" if name == "demo" else "data")
        if name not in {"demo", "new", "doctor", "eval"}:
            sub.add_argument("--session", required=True)
        if name in {"demo", "new"}:
            sub.add_argument("--seed")
        if name in {"demo", "turn"}:
            sub.add_argument("--json", action="store_true")
        if name in {"turn", "doctor", "eval"}:
            sub.add_argument("--profile", required=name in {"doctor", "eval"})
            sub.add_argument("--env-file", default=".env")
        if name == "doctor":
            sub.add_argument("--output")
        if name == "eval":
            sub.add_argument("--out-dir", default="reports")
            sub.add_argument("--max-turns", type=int, default=6)
        if name == "import-txt":
            sub.add_argument("--file", required=True)
            sub.add_argument("--scope", choices=["scenario", "character"], default="character")
            sub.add_argument("--character-id")
            sub.add_argument("--kind", choices=["knowledge", "style"], default="knowledge")
        if name == "turn":
            sub.add_argument("--text", required=True)
            sub.add_argument("--private-thoughts", default="")
            sub.add_argument("--visibility", choices=["public", "private"], default="public")
            sub.add_argument("--focus")
            sub.add_argument("--turn-id")
            sub.add_argument("--backend", choices=["demo", "local"], default="local")
            sub.add_argument("--model", default=os.getenv("FICTION_MODEL", ""))
            sub.add_argument("--base-url", default=os.getenv("FICTION_BASE_URL", "http://127.0.0.1:1234/v1"))
            sub.add_argument("--json-mode", choices=["prompt", "json_object", "json_schema"], default="prompt")
            sub.add_argument("--context-chars", type=int, default=16000)
            group = sub.add_mutually_exclusive_group()
            group.add_argument("--memory", action="append")
            group.add_argument("--no-memories", action="store_true")
        if name == "remember":
            sub.add_argument("--text", required=True)
            sub.add_argument("--scope", choices=["scenario", "character"], default="scenario")
            sub.add_argument("--character-id")
        if name == "approve":
            sub.add_argument("--memory-id", required=True)
        if name == "export":
            sub.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        from .runtime import ModelProfile, build_runtime, diagnose
        if args.command in {"doctor", "eval"}:
            profile = ModelProfile.read(args.profile)
            if args.command == "doctor":
                report = diagnose(profile, args.env_file)
                output = json.dumps(report, ensure_ascii=False, indent=2)
                if args.output:
                    path = Path(args.output)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(output, encoding="utf-8")
                print(output)
                if not report["status"].startswith("ready"):
                    parser.exit(2)
            else:
                from .evaluation import evaluate
                folder, report = evaluate(profile, args.out_dir, args.env_file, args.max_turns, progress=lambda x: print(x, flush=True))
                print(f"Informe: {folder / 'report.md'}\nEstado: {report['status']}")
                if report["status"] != "completed":
                    parser.exit(2)
            return
        backend = DemoBackend()
        budget = None
        if args.command == "turn" and args.profile:
            backend, budget = build_runtime(ModelProfile.read(args.profile), args.env_file)
        elif args.command == "turn" and args.backend == "local":
            backend = LocalBackend(LocalConfig(model=args.model, base_url=args.base_url,
                api_key=os.getenv("FICTION_API_KEY", ""), json_mode=args.json_mode,
                extra_body=json.loads(os.getenv("FICTION_EXTRA_BODY", "{}"))))
        with FictionEngine(args.data_dir, backend, context_chars=getattr(args, "context_chars", 16000), token_budget=budget) as engine:
            if args.command == "new":
                print(engine.create_session(load_seed(args.seed)))
            elif args.command in {"demo", "turn"}:
                if args.command == "demo":
                    sid = engine.create_session(load_seed(args.seed))
                    request = TurnRequest(session_id=sid, turn_id=uuid4().hex,
                                          user_input="Hola, Iria. ¿Qué le pasa al transmisor?")
                else:
                    request = TurnRequest(session_id=args.session, turn_id=args.turn_id or uuid4().hex,
                        user_input=args.text, private_thoughts=args.private_thoughts, visibility=args.visibility,
                        focus_character_id=args.focus, selected_memory_ids=[] if args.no_memories else args.memory)
                if not args.json:
                    print(f"Sesión: {request.session_id}\nTurno: {request.turn_id}")
                    if backend.demo:
                        print("DEMO DETERMINISTA: respuestas de prueba, sin modelo de lenguaje.\n")
                result = engine.run_turn(request)
                print(result.model_dump_json(indent=2) if args.json else result.reply)
            elif args.command == "memories":
                print(json.dumps(engine.repository.memories(args.session), ensure_ascii=False, indent=2))
            elif args.command == "characters":
                print(json.dumps(engine.repository.character_cards(args.session), ensure_ascii=False, indent=2))
            elif args.command == "import-txt":
                path = Path(args.file)
                print(json.dumps(engine.import_text(args.session, path.name, path.read_bytes(), args.scope, args.character_id, args.kind), ensure_ascii=False))
            elif args.command == "remember":
                print(engine.add_memory(args.session, args.text, args.scope, args.character_id))
            elif args.command == "approve":
                engine.approve_memory(args.session, args.memory_id)
                print("Recuerdo aprobado.")
            elif args.command == "export":
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(engine.repository.export_session(args.session), ensure_ascii=False, indent=2), encoding="utf-8")
                print(str(path.resolve()))
    except (ValueError, RuntimeError, ModelError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
