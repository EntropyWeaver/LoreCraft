"""Backend determinista: permite probar infraestructura, NO evalúa un LLM."""
import json


class DemoBackend:
    identity = "demo-determinista-v1"
    demo = True

    def __init__(self):
        self.calls = []

    def complete(self, role, messages, schema, max_tokens):
        self.calls.append({"role": role, "messages": messages})
        payload = json.loads(messages[1]["content"])
        if role == "scenario":
            cards = payload["selected_character_cards"] or [{
                "key": "iria", "name": "Iria", "identity": "Ingeniera de sistemas, 34 años",
                "traits": ["observadora", "independiente"], "voice": "Natural, con humor seco",
                "immediate_goal": "Reparar el transmisor", "relationship_to_player": "Se conocen de vista",
                "known_facts": ["El repetidor necesita revisión"], "private_secrets": []}]
            value = {"title": payload["title"], "setting": "Estación orbital Kepler",
                     "tone": payload["style_preferences"]["tone"], "premise": payload["brief"],
                     "player_role": "Visitante del taller", "characters": cards,
                     "initial_scene": {"location": "Taller", "time": "Turno de noche",
                                       "present_character_keys": [c["key"] for c in cards],
                                       "public_facts": ["Hay un apagón parcial en la estación."]},
                     "open_threads": ["Averiguar qué sucede con el transmisor"]}
        elif role == "director":
            ids = [c["id"] for c in payload["public_context"]["present_characters"]]
            value = {"focus_character_id": payload.get("requested_focus_character_id") or ids[0],
                     "pace": "normal", "response_mode": "mixed", "max_words": payload["max_words_limit"]}
        elif role == "actor":
            name = payload["character_card"]["name"]
            text = (f"{name} deja el destornillador junto al transmisor y levanta la vista.\n\n"
                    "—El repetidor ha decidido tomarse la noche libre. Yo todavía no he recibido ese permiso.\n\n"
                    "Señala una luz ámbar que parpadea en el panel.\n\n"
                    "—Podemos empezar por ahí. La herramienta está sobre la mesa, si quieres echar una mano.")
            memories = payload["character_memories"]
            if memories:
                text += "\n\n[Demo: recuerdo recibido: " + memories[0]["text"] + "]"
            return text
        elif role == "archivist":
            source = payload["turn_messages_with_ids"][-1]
            focal = payload["focus_character_id"]
            value = {
                "scene_event_candidates": [{"kind": "claim", "text": "El personaje propone revisar el repetidor.",
                    "source_message_ids": [source["id"]], "observed_by_character_ids": source["audience"]}],
                "memory_candidates": [{"scope": "character", "character_id": focal,
                    "text": "Propuso al visitante revisar el repetidor.", "source_message_ids": [source["id"]]}],
                "contradictions": []}
        else:
            raise ValueError(role)
        return json.dumps(value, ensure_ascii=False)
