"""Presupuesto sobre el prompt completo, con tokenizer y plantilla del modelo."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import inspect
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from .storage import digest


class TokenBudgetError(RuntimeError):
    pass


class TokenCounter(Protocol):
    context_window: int
    identity: str

    def count_messages(self, messages: list[dict]) -> int: ...


class LMStudioCounter:
    """Usa solo una instancia ya cargada; nunca llama a model() ni load()."""

    def __init__(self, base_url: str, model: str, api_key: str = "", client=None):
        self.base_url, self.model_id, self._api_key = base_url, model, api_key
        self._client, self._owns_client = client, client is None
        self._model = None

    def _connect(self):
        if self._model is not None:
            return
        try:
            if self._client is None:
                import lmstudio as lms
                url = urlsplit(self.base_url)
                if url.scheme != "http" or url.path.rstrip("/") != "/v1":
                    raise TokenBudgetError("El contador LM Studio requiere su URL HTTP directa con /v1. Para otros servidores usa un tokenizer HF local.")
                kwargs = {}
                if self._api_key:
                    if "api_token" not in inspect.signature(lms.Client).parameters:
                        raise TokenBudgetError("Este SDK de LM Studio no admite api_token. Usa un SDK que lo admita o el contador HF local.")
                    kwargs["api_token"] = self._api_key
                lms.set_sync_api_timeout(15.0)
                self._client = lms.Client(url.netloc, **kwargs)
            loaded = self._client.llm.list_loaded()
            self._model = next((m for m in loaded if m.identifier == self.model_id), None)
            if self._model is None:
                raise TokenBudgetError("El modelo elegido no está cargado en LM Studio. Cárgalo y usa su identificador exacto.")
        except ImportError as exc:
            raise TokenBudgetError('Instala el extra del proyecto: pip install -e ".[lmstudio]".') from exc
        except TokenBudgetError:
            raise
        except Exception as exc:
            raise TokenBudgetError("No se pudo acceder al tokenizer de LM Studio. Comprueba servidor, modelo y SDK.") from exc

    @property
    def context_window(self):
        self._connect()
        try:
            return int(self._model.get_context_length())
        except Exception as exc:
            raise TokenBudgetError("No se pudo consultar el contexto cargado en LM Studio.") from exc

    @property
    def identity(self):
        self._connect()
        try:
            info = self._model.get_info().to_dict()
        except Exception as exc:
            raise TokenBudgetError("No se pudo identificar la instancia cargada en LM Studio.") from exc
        return "lmstudio:" + digest({"server": self.base_url, "model": info})[:24]

    def count_messages(self, messages):
        self._connect()
        try:
            formatted = self._model.apply_prompt_template({"messages": messages})
            return len(self._model.tokenize(formatted))
        except Exception as exc:
            raise TokenBudgetError("Falló la aplicación de plantilla o tokenización en LM Studio.") from exc

    def close(self):
        if self._owns_client and self._client is not None:
            self._client.close()


class HFLocalCounter:
    """Tokenizador local, sin pesos, descargas ni ejecución de código remoto."""

    def __init__(self, path: str, context_window: int):
        if context_window <= 0:
            raise TokenBudgetError("Con HF debes indicar la ventana realmente configurada en el servidor.")
        folder = Path(path).expanduser().resolve()
        if not folder.is_dir():
            raise TokenBudgetError("tokenizer_path debe ser una carpeta local con el tokenizer del modelo.")
        try:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
        except ImportError as exc:
            raise TokenBudgetError('Instala el extra del proyecto: pip install -e ".[hf]".') from exc
        except Exception as exc:
            raise TokenBudgetError("No se pudo abrir el tokenizer local.") from exc
        if not self.tokenizer.chat_template:
            raise TokenBudgetError("El tokenizer necesita la misma chat_template que usa el servidor.")
        self.context_window = context_window
        self.identity = "hf-local:" + digest({"files": [(p.name, digest(p.read_bytes().hex()))
            for p in sorted(folder.iterdir()) if p.is_file() and p.suffix in {".json", ".jinja", ".model", ".txt"}]})[:24]

    def count_messages(self, messages):
        try:
            tokens = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=False)
            return len(tokens)
        except Exception as exc:
            raise TokenBudgetError("La plantilla local no puede representar estos mensajes.") from exc


@dataclass
class TokenBudget:
    counter: TokenCounter
    context_limit: int | None = None
    safety_tokens: int = 128
    output_caps: dict[str, int] = field(default_factory=lambda: {
        "scenario": 2048, "director": 512, "actor": 1024, "archivist": 1536})

    def __post_init__(self):
        if self.safety_tokens < 0 or (self.context_limit is not None and self.context_limit <= 0):
            raise TokenBudgetError("Ventana y margen de tokens inválidos.")
        if any(not isinstance(v, int) or v <= 0 for v in self.output_caps.values()):
            raise TokenBudgetError("Las reservas de salida deben ser enteros positivos.")

    @property
    def window(self):
        loaded = self.counter.context_window
        if loaded <= 0:
            raise TokenBudgetError("El tokenizer no informa una ventana válida.")
        return min(loaded, self.context_limit) if self.context_limit else loaded

    def fingerprint(self):
        return {"counter": self.counter.identity, "window": self.window,
                "safety_tokens": self.safety_tokens, "output_caps": self.output_caps}

    def output_limit(self, role, requested):
        return min(requested, self.output_caps.get(role, requested))

    def measure(self, messages, output_tokens):
        count = self.counter.count_messages(messages)
        if not isinstance(count, int) or count < 0:
            raise TokenBudgetError("El contador no devolvió un número de tokens válido.")
        window = self.window
        return {"budget_unit": "tokens", "tokenizer": self.counter.identity,
                "count_accuracy": getattr(self.counter, "accuracy", "model_template"),
                "prompt_tokens": count, "reserved_output_tokens": output_tokens,
                "safety_tokens": self.safety_tokens, "context_window": window,
                "fits": count + output_tokens + self.safety_tokens <= window}

    def fit(self, role, payload, make_messages, output_tokens, extra_messages=None):
        """Recorta historial antiguo y después recuerdos de menor prioridad.

        Nunca recorta sistema, esquema, ficha, escena obligatoria ni entrada actual.
        Cuenta también los mensajes de reparación de JSON cuando los hay.
        """
        value = deepcopy(payload)
        extra_messages = extra_messages or []
        if role == "director":
            target, memory_key, history_key = value["public_context"], "memories", "history"
        elif role == "actor":
            target, memory_key, history_key = value, "character_memories", "visible_history"
        elif role == "archivist":
            target, memory_key, history_key = value, "existing_memory_summaries", None
        else:
            target, memory_key, history_key = value, None, None
        original_ids = [m["id"] for m in target.get(memory_key, [])] if memory_key else []
        removed_history = []
        while True:
            messages = make_messages(value) + extra_messages
            report = self.measure(messages, output_tokens)
            if report["fits"]:
                break
            history = target.get(history_key, []) if history_key else []
            if history:
                first_turn = history[0]["id"].rsplit(":", 1)[0]
                while history and history[0]["id"].rsplit(":", 1)[0] == first_turn:
                    removed_history.append(history.pop(0)["id"])
            elif memory_key and target.get(memory_key):
                target[memory_key].pop()
            else:
                raise TokenBudgetError(f"{role}: el prompt obligatorio usa {report['prompt_tokens']} tokens; "
                    f"reserva {output_tokens} de salida y {self.safety_tokens} de margen, "
                    f"pero la ventana es {report['context_window']}. Reduce entrada/ficha o ajusta la ventana y reservas.")
        included = [m["id"] for m in target.get(memory_key, [])] if memory_key else []
        report.update(included_memory_ids=included, omitted_memory_ids=[m for m in original_ids if m not in included],
            history_message_ids=[m["id"] for m in target.get(history_key, [])] if history_key else [],
            omitted_history_message_ids=removed_history)
        return messages, report

    def close(self):
        if hasattr(self.counter, "close"):
            self.counter.close()
