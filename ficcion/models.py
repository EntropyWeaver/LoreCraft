"""Contratos de datos: el texto del modelo no escribe directamente en SQLite."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterCard(Record):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    identity: str
    traits: list[str]
    voice: str
    immediate_goal: str
    relationship_to_player: str
    known_facts: list[str] = Field(default_factory=list)
    private_secrets: list[str] = Field(default_factory=list)


class Style(Record):
    language: str = "es"
    tone: str = "cercano, atmosférico, humor sutil"
    default_max_words: int = Field(default=220, ge=40, le=1000)


class ScenarioSeed(Record):
    title: str = "Nueva historia"
    brief: str = Field(min_length=1, max_length=12000)
    style_preferences: Style = Field(default_factory=Style)
    selected_character_cards: list[CharacterCard] = Field(default_factory=list)
    imported_fiction_memories: list[str] = Field(default_factory=list)


class InitialScene(Record):
    location: str
    time: str
    present_character_keys: list[str] = Field(min_length=1)
    public_facts: list[str]


class ScenarioDraft(Record):
    title: str
    setting: str
    tone: str
    premise: str
    player_role: str
    characters: list[CharacterCard] = Field(min_length=1, max_length=12)
    initial_scene: InitialScene
    open_threads: list[str]

    @model_validator(mode="after")
    def valid_keys(self):
        keys = [c.key for c in self.characters]
        if len(set(keys)) != len(keys):
            raise ValueError("Las claves de personajes deben ser únicas.")
        if not set(self.initial_scene.present_character_keys) <= set(keys):
            raise ValueError("La escena referencia personajes inexistentes.")
        return self


class TurnPlan(Record):
    focus_character_id: str
    pace: Literal["slow", "normal", "brisk"]
    response_mode: Literal["dialogue", "action", "mixed"]
    max_words: int = Field(ge=1, le=1000)


class SceneEvent(Record):
    kind: Literal["established", "attempt", "claim", "belief"]
    text: str = Field(min_length=1, max_length=2000)
    source_message_ids: list[str] = Field(min_length=1)
    observed_by_character_ids: list[str]


class MemoryCandidate(Record):
    scope: Literal["scenario", "character"]
    character_id: str | None
    text: str = Field(min_length=1, max_length=2000)
    source_message_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_scope(self):
        if (self.scope == "character") != (self.character_id is not None):
            raise ValueError("El ámbito character necesita character_id; scenario usa null.")
        return self


class Contradiction(Record):
    description: str
    source_message_ids: list[str] = Field(min_length=1)


class ArchiveProposal(Record):
    scene_event_candidates: list[SceneEvent] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)


class TurnRequest(Record):
    session_id: str
    turn_id: str = Field(min_length=1, max_length=128)
    user_input: str = Field(min_length=1, max_length=12000)
    private_thoughts: str = Field(default="", max_length=12000)
    visibility: Literal["public", "private"] = "public"
    focus_character_id: str | None = None
    selected_memory_ids: list[str] | None = None


class TurnResult(Record):
    session_id: str
    turn_id: str
    reply: str
    focus_character_id: str
    model: str
    demo: bool
    pending_memory_ids: list[str]
    trace: list[str]
    context_report: dict
    warnings: list[str]
