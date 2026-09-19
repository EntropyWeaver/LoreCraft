"""Configuración explícita, .env y diagnóstico que no genera ficción."""
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import os

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .budget import HFLocalCounter, LMStudioCounter, TokenBudget
from .llm import LocalBackend, LocalConfig, ModelError


def read_secrets(env_file: str | Path = ".env") -> dict:
    path = Path(env_file)
    values = {}
    if path.is_file():
        try:
            from dotenv import dotenv_values
        except ImportError as exc:
            raise ModelError("Instala python-dotenv para leer el archivo .env.") from exc
        values = dotenv_values(path, interpolate=False)
    # Nunca se exporta ni se incluye este diccionario en prompts o perfiles.
    return {name: os.getenv(name) or values.get(name) or "" for name in ("OPENAI_API_KEY", "FICTION_API_KEY")}


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["local", "openai"] = "local"
    model: str = ""
    base_url: str = "http://127.0.0.1:1234/v1"
    tokenizer: Literal["lmstudio", "hf", "openai", "characters"] = "lmstudio"
    tokenizer_path: str = ""
    context_window: int | None = Field(default=None, ge=512)
    safety_tokens: int = Field(default=128, ge=0)
    output_caps: dict[str, int] = Field(default_factory=lambda: {
        "scenario": 2048, "director": 512, "actor": 1024, "archivist": 1536})
    temperature: float = Field(default=0.7, ge=0, le=2)
    timeout: float = Field(default=120, gt=0, le=600)
    json_mode: Literal["prompt", "json_object", "json_schema"] = "prompt"
    extra_body: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        url = urlsplit(self.base_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("La URL debe ser HTTP(S), sin credenciales ni parámetros.")
        if self.provider == "openai":
            if self.base_url.rstrip("/") != "https://api.openai.com/v1" or self.tokenizer != "openai":
                raise ValueError("OpenAI requiere su URL oficial y tokenizer=openai.")
        elif self.tokenizer == "openai":
            raise ValueError("El tokenizer OpenAI requiere provider=openai.")
        if self.tokenizer in {"openai", "hf"} and self.context_window is None:
            raise ValueError("Indica context_window para ese tokenizer.")
        allowed = {"scenario", "director", "actor", "archivist"}
        if not set(self.output_caps) <= allowed or any(type(v) is not int or v <= 0 for v in self.output_caps.values()):
            raise ValueError("output_caps contiene roles o valores inválidos.")
        if set(self.extra_body) - {"seed", "top_p", "top_k", "repeat_penalty", "frequency_penalty", "presence_penalty"}:
            raise ValueError("extra_body solo admite parámetros de muestreo; la plantilla y el formato los controla el perfil.")
        return self

    @classmethod
    def read(cls, path):
        profile = cls.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))
        if profile.tokenizer_path:
            folder = Path(profile.tokenizer_path).expanduser()
            if not folder.is_absolute():
                profile.tokenizer_path = str((Path(path).resolve().parent / folder).resolve())
        return profile


def build_runtime(profile: ModelProfile, env_file=".env", client=None):
    secrets = read_secrets(env_file)
    config = LocalConfig(model=profile.model, base_url=profile.base_url,
        api_key=secrets["OPENAI_API_KEY" if profile.provider == "openai" else "FICTION_API_KEY"],
        temperature=profile.temperature, timeout=profile.timeout, json_mode=profile.json_mode, extra_body=profile.extra_body)
    if profile.provider == "openai":
        from .openai_backend import OpenAIBackend, OpenAITokenCounter
        backend = OpenAIBackend(config, client=client)
        counter = OpenAITokenCounter(backend, profile.context_window)
    else:
        backend = LocalBackend(config, client=client)
        if profile.tokenizer == "characters":
            return backend, None
        if profile.tokenizer == "lmstudio":
            counter = LMStudioCounter(profile.base_url, profile.model, config.api_key)
        else:
            try:
                counter = HFLocalCounter(profile.tokenizer_path, profile.context_window)
            except Exception:
                backend.close()
                raise
    return backend, TokenBudget(counter, profile.context_window, profile.safety_tokens, profile.output_caps)


def diagnose(profile: ModelProfile, env_file=".env", client=None) -> dict:
    report = {"profile": profile.model_dump(), "status": "unreachable", "generation_performed": False}
    secrets = read_secrets(env_file)
    key = secrets["OPENAI_API_KEY" if profile.provider == "openai" else "FICTION_API_KEY"]
    if profile.provider == "openai" and not key:
        return {**report, "status": "missing_key", "message": "Falta OPENAI_API_KEY en .env o entorno."}
    owned = client is None
    client = client or httpx.Client(timeout=min(profile.timeout, 15))
    try:
        response = client.get(profile.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {key}"} if key else {})
        response.raise_for_status()
        ids = [x["id"] for x in response.json()["data"] if isinstance(x, dict) and isinstance(x.get("id"), str)]
        report.update(advertised_model_ids=sorted(ids), status="needs_model")
        if not profile.model:
            return report
        if profile.model not in ids:
            return {**report, "status": "model_not_listed", "message": "El identificador no aparece en /models para estas credenciales."}
        backend, budget = build_runtime(profile, env_file, client=client)
        try:
            if budget:
                messages = [{"role": "system", "content": "Responde en español."}, {"role": "user", "content": "Hola, Iria."}]
                report["tokenizer_probe"] = budget.measure(messages, 128)
                report["status"] = "ready_for_generation_test" if report["tokenizer_probe"]["fits"] else "context_too_small"
            else:
                report["status"] = "ready_without_tokenizer"
        finally:
            if budget:
                budget.close()
            backend.close()
        return report
    except httpx.HTTPStatusError as exc:
        return {**report, "status": "http_error", "http_status": exc.response.status_code}
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "No se pudo conectar al servidor."
        return {**report, "status": "error", "message": message}
    finally:
        if owned:
            client.close()
