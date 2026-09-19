"""OpenAI mediante ChatOpenAI; sin llamadas de red durante las pruebas unitarias."""
from dataclasses import asdict
from importlib.metadata import version

import httpx
from langchain_core.messages import convert_to_messages

from .budget import TokenBudgetError
from .llm import LocalConfig, ModelError, strict_json_schema
from .storage import digest


class OpenAIBackend:
    demo = False

    def __init__(self, config: LocalConfig, client=None):
        if not config.api_key:
            raise ModelError("Falta OPENAI_API_KEY. Guárdala en el .env de tu equipo o en una variable de entorno.")
        if config.base_url.rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("El proveedor OpenAI usa https://api.openai.com/v1; para otro servidor elige local.")
        if not config.model.strip():
            raise ValueError("Falta el identificador del modelo de OpenAI.")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ModelError('Instala el extra: pip install -e ".[openai]".') from exc
        self.config = config
        public = asdict(config)
        public.pop("api_key")
        self.identity = "openai-langchain:" + config.model + "#" + digest(public)[:12]
        self.client = client or httpx.Client(timeout=config.timeout)
        self._owns_client = client is None
        self.chat = ChatOpenAI(model=config.model, api_key=config.api_key, base_url=config.base_url,
            temperature=config.temperature, max_retries=0, timeout=config.timeout,
            http_client=self.client, http_socket_options=(), use_responses_api=False)
        self.last_metadata = {}

    def complete(self, role, messages, schema, max_tokens):
        self.last_metadata = {}
        kwargs = {"max_tokens": max_tokens, "temperature": self.config.temperature if role == "actor" else 0.2,
                  "store": False}
        if self.config.extra_body:
            kwargs["extra_body"] = self.config.extra_body
        if schema and self.config.json_mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        elif schema and self.config.json_mode == "json_schema":
            kwargs["response_format"] = {"type": "json_schema", "json_schema":
                {"name": schema.get("title", "result"), "schema": strict_json_schema(schema), "strict": True}}
        try:
            response = self.chat.invoke(convert_to_messages(messages), **kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise ModelError("Falló OpenAI" + suffix + ". Comprueba modelo, clave, saldo y formato JSON.") from exc
        usage = response.usage_metadata or {}
        metadata = response.response_metadata
        self.last_metadata = {"reported_model": metadata.get("model_name"),
            "finish_reason": metadata.get("finish_reason"), "usage": {
                "prompt_tokens": usage.get("input_tokens"), "completion_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens")}}
        self.last_metadata["usage"] = {k: v for k, v in self.last_metadata["usage"].items() if isinstance(v, int)}
        if metadata.get("finish_reason") == "length":
            raise ModelError("La respuesta de OpenAI quedó truncada; aumenta la reserva de salida del rol.")
        if not isinstance(response.content, str) or not response.content.strip():
            raise ModelError("OpenAI no devolvió una respuesta de texto utilizable.")
        return response.content.strip()

    def close(self):
        if self._owns_client:
            self.client.close()


class OpenAITokenCounter:
    """Tiktoken a través de LangChain. El overhead de Chat Completions es estimado."""
    accuracy = "estimated_chat_overhead"

    def __init__(self, backend: OpenAIBackend, context_window: int):
        self.backend, self.context_window = backend, context_window
        if context_window <= 0:
            raise TokenBudgetError("Indica una ventana de contexto compatible con el modelo elegido.")
        self.identity = "langchain-tiktoken:" + digest({"model": backend.config.model,
            "langchain_openai": version("langchain-openai"), "tiktoken": version("tiktoken")})[:24]

    def count_messages(self, messages):
        try:
            return self.backend.chat.get_num_tokens_from_messages(convert_to_messages(messages))
        except Exception as exc:
            raise TokenBudgetError("No se pudo contar este modelo con LangChain/tiktoken. Comprueba su identificador y la instalación del tokenizer.") from exc
