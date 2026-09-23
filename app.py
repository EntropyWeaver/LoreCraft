"""Panel local para escribir, seleccionar recuerdos e inspeccionar el contexto."""
import json
import os
from uuid import uuid4

import streamlit as st

from ficcion.cli import load_seed
from ficcion.demo import DemoBackend
from ficcion.engine import FictionEngine
from ficcion.llm import LocalBackend, LocalConfig
from ficcion.models import ScenarioSeed, TurnRequest
from ficcion.runtime import ModelProfile, build_runtime, diagnose, read_secrets

st.set_page_config(page_title="LoreCraft", page_icon="📖", layout="wide")
st.title("LoreCraft")
st.caption("Escenarios, personajes y recuerdos que tú eliges.")

with st.sidebar:
    mode = st.radio("Motor", ["Demo de funcionamiento", "Modelo local", "OpenAI (LangChain)"])
    data_dir = st.text_input("Carpeta de sesiones", value="data")
    base_url = "https://api.openai.com/v1" if mode == "OpenAI (LangChain)" else st.text_input("Servidor", value=os.getenv("FICTION_BASE_URL", "http://127.0.0.1:1234/v1"))
    model_id = st.text_input("Identificador del modelo", value="gpt-4o-2024-08-06" if mode == "OpenAI (LangChain)" else os.getenv("FICTION_MODEL", ""), key="model_" + mode)
    json_mode = st.selectbox("Salida estructurada", ["prompt", "json_object", "json_schema"])
    st.caption("El modo prompt funciona sin exigir salida estructurada al servidor; el código valida el JSON.")
    tokenizer = "characters"
    context_window, env_file, tokenizer_path = 0, ".env", ""
    if mode != "Demo de funcionamiento":
        tokenizer = st.selectbox("Contador de contexto", ["openai"] if mode == "OpenAI (LangChain)" else ["lmstudio", "hf", "characters"])
        context_window = st.number_input("Límite de contexto en tokens · 0 usa el cargado en LM Studio", min_value=0,
            value=128000 if mode == "OpenAI (LangChain)" else 0, step=512, key="window_" + mode)
        if tokenizer == "hf":
            tokenizer_path = st.text_input("Carpeta local del tokenizer")
        env_file = st.text_input("Archivo de credenciales", value=".env")

if mode == "Demo de funcionamiento":
    st.info("Demo determinista: el grafo y SQLite funcionan, pero las respuestas son de prueba. No hay un LLM conectado.")

try:
    profile, budget = None, None
    ready = mode == "Demo de funcionamiento" or bool(model_id.strip())
    if mode == "OpenAI (LangChain)":
        ready = ready and bool(read_secrets(env_file)["OPENAI_API_KEY"])
    if mode != "Demo de funcionamiento":
        profile = ModelProfile(provider="openai" if mode == "OpenAI (LangChain)" else "local",
            model=model_id, base_url=base_url, json_mode=json_mode, tokenizer=tokenizer,
            tokenizer_path=tokenizer_path, context_window=int(context_window) or None,
            safety_tokens=1024 if mode == "OpenAI (LangChain)" else 128)
        if st.sidebar.button("Comprobar conexión"):
            st.sidebar.json(diagnose(profile, env_file))
    backend = DemoBackend()
    if mode != "Demo de funcionamiento" and ready:
        backend, budget = build_runtime(profile, env_file)
    engine = FictionEngine(data_dir, backend, token_budget=budget)
except Exception as exc:
    st.error(str(exc))
    st.stop()

try:
    with st.sidebar.expander("Crear una historia", expanded=not engine.repository.list_sessions()):
        with st.form("new_story"):
            seed = load_seed().model_dump()
            title = st.text_input("Título", value=seed["title"])
            brief = st.text_area("Situación inicial", value=seed["brief"])
            character_json = st.text_area("Ficha del personaje (JSON)", value=json.dumps(seed["selected_character_cards"][0], ensure_ascii=False, indent=2), height=200)
            if st.form_submit_button("Crear historia"):
                try:
                    seed.update(title=title, brief=brief, selected_character_cards=[json.loads(character_json)])
                    sid = engine.create_session(ScenarioSeed.model_validate(seed))
                    st.session_state["selected_session"] = sid
                    st.session_state.pop("pending_request", None)
                    st.rerun()
                except (ValueError, RuntimeError) as exc:
                    st.error(str(exc))

    sessions = engine.repository.list_sessions()
    if not sessions:
        st.write("Crea la historia de Kepler desde la barra lateral para comenzar.")
        st.stop()
    ids = [s["id"] for s in sessions]
    names = {s["id"]: s["title"] for s in sessions}
    selected = st.session_state.get("selected_session", ids[0])
    sid = st.sidebar.selectbox("Historia", ids, index=ids.index(selected) if selected in ids else 0,
                              format_func=lambda value: f"{names[value]} · {value[:6]}")
    st.session_state["selected_session"] = sid
    session = engine.repository.session(sid)
    scenario = session["scenario"]
    chars = engine.repository.character_cards(sid)
    present = scenario["initial_scene"]["present_character_ids"] if scenario else []
    focus = st.sidebar.selectbox("Personaje focal", [None] + present,
        format_func=lambda value: "Automático" if value is None else chars[value]["name"])
    visibility = st.sidebar.selectbox("Audiencia", ["public", "private"],
                                     format_func=lambda value: "Pública" if value == "public" else "Privada con el personaje focal")

    memories = engine.repository.memories(sid)
    approved = {m["id"]: m for m in memories if m["approved"]}
    imported_selection = st.session_state.pop("import_selection_" + sid, None)
    if imported_selection:
        previous = st.session_state.get("memories_" + sid, session["selection"])
        st.session_state["memories_" + sid] = list(dict.fromkeys(previous + imported_selection))
    selected_ids = st.sidebar.multiselect("Recuerdos para el próximo turno", list(approved),
        default=[mid for mid in session["selection"] if mid in approved], key="memories_" + sid,
        format_func=lambda value: approved[value]["text"][:85])
    st.sidebar.caption("Desactivar evita recuperar el recuerdo. Lo ya mencionado en el historial puede seguir presente; una historia nueva empieza con contexto limpio.")

    if chars:
        with st.sidebar.expander("Importar un TXT"):
            uploaded = st.file_uploader("Archivo de referencia", type=["txt"], key="txt_" + sid)
            kind = st.selectbox("Usar como", ["knowledge", "style"],
                format_func=lambda x: "Conocimientos de ficción" if x == "knowledge" else "Ejemplos de voz, sin añadir hechos")
            owners = list(chars) if kind == "style" else list(chars) + [None]
            owner = st.selectbox("Personaje que recibe el archivo", owners,
                format_func=lambda x: chars[x]["name"] if x else "Todo el escenario")
            activate = st.checkbox("Activar sus fragmentos para el próximo turno", value=True)
            if uploaded:
                st.caption("Vista previa · primeros 1 200 caracteres")
                st.code(uploaded.getvalue().decode("utf-8-sig", errors="replace")[:1200], language=None)
                if st.button("Importar TXT"):
                    try:
                        imported = engine.import_text(sid, uploaded.name, uploaded.getvalue(),
                            "character" if owner else "scenario", owner, kind)
                        if activate:
                            st.session_state["import_selection_" + sid] = imported["memory_ids"]
                        st.rerun()
                    except (ValueError, RuntimeError) as exc:
                        st.error(str(exc))

    with st.sidebar.expander("Recuerdos propuestos"):
        pending = [m for m in memories if not m["approved"]]
        if not pending:
            st.caption("Todavía no hay propuestas pendientes.")
        for memory in pending:
            st.write(memory["text"])
            if st.button("Aprobar", key="approve_" + memory["id"]):
                engine.approve_memory(sid, memory["id"])
                st.rerun()
    if scenario:
        with st.sidebar.expander("Añadir un recuerdo"):
            with st.form("add_memory_" + sid):
                memory_text = st.text_area("Contenido del recuerdo")
                owner = st.selectbox("Quién lo conoce", [None] + list(chars),
                    format_func=lambda value: "Todo el escenario" if value is None else chars[value]["name"])
                if st.form_submit_button("Guardar recuerdo"):
                    try:
                        engine.add_memory(sid, memory_text, "scenario" if owner is None else "character", owner)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    st.subheader(names[sid])
    if scenario:
        st.caption(f"{scenario['initial_scene']['location']} · {scenario['initial_scene']['time']}")
    turns = engine.repository.history(sid, 100)
    for turn in turns:
        for message in turn["messages"]:
            with st.chat_message(message["role"]):
                if not message["public"]:
                    st.caption("Intervención privada")
                st.markdown(message["content"])
        for warning in turn["result"]["warnings"]:
            st.caption(warning)
    private_thoughts = st.text_input("Nota privada del jugador (se guarda; no se envía al modelo)", key="notes_" + sid)
    text = st.chat_input("Tu intervención", disabled=not ready)
    if not ready:
        st.caption("Indica el modelo y, si elegiste OpenAI, guarda OPENAI_API_KEY en tu .env para generar.")
    if text:
        st.session_state["pending_request"] = TurnRequest(session_id=sid, turn_id=uuid4().hex,
            user_input=text, private_thoughts=private_thoughts, visibility=visibility,
            focus_character_id=focus, selected_memory_ids=selected_ids).model_dump()
    pending_request = st.session_state.get("pending_request")
    retry = False
    if pending_request and pending_request["session_id"] == sid and not text:
        retry = st.button("Reintentar turno pendiente")
        if st.button("Descartar reintento"):
            st.session_state.pop("pending_request", None)
            st.rerun()
    if text or retry:
        if not ready:
            st.error("Falta la configuración del proveedor elegido.")
        else:
            try:
                with st.spinner("Preparando contexto y generando el turno…"):
                    engine.run_turn(pending_request)
                st.session_state.pop("pending_request", None)
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    if turns:
        with st.expander("Inspector del último turno · vista de autor"):
            st.write("Recuerdos incluidos, omisiones y recorrido:")
            st.json({"trace": turns[-1]["result"]["trace"], "context": turns[-1]["result"]["context_report"]})
            st.write("Mensajes exactos enviados a cada rol. Esta vista puede contener la ficha privada del personaje.")
            st.json(turns[-1]["audit"])
        st.download_button("Exportar esta historia", json.dumps(engine.repository.export_session(sid), ensure_ascii=False, indent=2),
                           file_name=f"historia_{sid[:8]}.json", mime="application/json")
finally:
    engine.close()
