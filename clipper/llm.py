"""LLM access for the subagents.

Every client asks for a structured answer through a single tool whose input schema is the subagent's
contract: AnthropicLLM uses Anthropic's Messages API; OpenAICompatLLM uses the OpenAI Chat Completions
API, which OpenAI, Gemini, OpenRouter, Mistral, DeepSeek, Groq, Ollama, LM Studio and vLLM all speak.
The caller validates the answer and retries, so models that follow schemas less strictly still work.
OfflineLLM makes no calls: subagents fall back to simple heuristics, which exist to test the plumbing,
not to make editorial decisions."""
from __future__ import annotations

import base64
import json
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    usage: dict = field(default_factory=dict)


class LLMClient:
    offline = False

    def complete(self, *, agent: str, model: str, system: str, user: str, contract: type[BaseModel],
                 images: list[Path] | None = None, max_tokens: int = 8000) -> LLMResult:
        raise NotImplementedError


class AnthropicLLM(LLMClient):
    def __init__(self, api_key: str | None, client: Any = None, on_usage: Callable[[dict], None] | None = None):
        self.on_usage = on_usage
        if client is None:
            if not api_key:
                raise LLMError("Falta la API key de Anthropic. Añádela en Ajustes (o define ANTHROPIC_API_KEY), o ejecuta con --offline para probar sin Claude.")
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=300.0)
        self.client = client

    def complete(self, *, agent, model, system, user, contract, images=None, max_tokens=8000) -> LLMResult:
        tool_name = f"submit_{agent}"
        content: list[dict] = []
        for img in images or []:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(Path(img).read_bytes()).decode("ascii")}})
        content.append({"type": "text", "text": user})
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=f"{system}\n\nDeliver your final answer by calling the tool `{tool_name}` exactly once, "
                   "with the complete answer as its input. Do not answer in plain text.",
            messages=[{"role": "user", "content": content}],
            tools=[{"name": tool_name, "description": "Submit your final answer. Call this exactly once.",
                    "input_schema": contract.model_json_schema()}],
            # Forced tool_choice ("tool"/"any") is rejected (400) by Opus 5.5 / Sonnet 5.5 and later,
            # so the tool is requested in the prompt; the contract is validated by the caller's retries.
            tool_choice={"type": "auto"},
        )
        usage = {"input_tokens": getattr(resp.usage, "input_tokens", None),
                 "output_tokens": getattr(resp.usage, "output_tokens", None)}
        if self.on_usage:   # recorded before any check, because a rejected answer was still billed
            self.on_usage({"agent": agent, "model": resp.model, "input": usage["input_tokens"] or 0, "output": usage["output_tokens"] or 0})
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"{agent}: la respuesta se cortó por max_tokens ({max_tokens}).")
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return LLMResult(data=dict(block.input), model=resp.model, usage=usage)
        raise LLMError(f"{agent}: la respuesta no incluyó la llamada a {tool_name} (stop_reason={resp.stop_reason}).")


_GEMINI_DROP = {"additionalProperties", "default", "examples", "const", "$schema", "title"}


def portable_schema(schema: dict, dialect: str = "") -> dict:
    """The contract as a self-contained JSON Schema: $ref inlined (many OpenAI-compatible servers do not
    resolve them) and titles removed. Gemini also rejects some keywords and the anyOf-with-null that
    Optional fields produce, so those become `nullable`."""
    schema = deepcopy(schema)
    defs = schema.pop("$defs", {}) | schema.pop("definitions", {})

    def walk(node, depth=0):
        if depth > 40:
            return node
        if isinstance(node, list):
            return [walk(x, depth + 1) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = defs.get(node["$ref"].split("/")[-1], {})
            node = {**deepcopy(target), **{k: v for k, v in node.items() if k != "$ref"}}
        out = {k: walk(v, depth + 1) for k, v in node.items() if k != "title"}
        if dialect == "gemini":
            for k in _GEMINI_DROP:
                out.pop(k, None)
            options = out.get("anyOf")
            if isinstance(options, list):
                rest = [o for o in options if o.get("type") != "null"]
                if len(rest) == 1 and len(rest) < len(options):
                    out.pop("anyOf")
                    out.update(rest[0])
                    out["nullable"] = True
        return out

    return walk(schema)


def parse_json_answer(text: str | None) -> dict | None:
    """A JSON object written as plain text (models that ignore the tool): fenced or bare."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""
    try:
        data = json.loads(candidate)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class OpenAICompatLLM(LLMClient):
    """Chat Completions with a forced function call. Works with every OpenAI-compatible server.

    Fallbacks, because servers differ: when a forced tool_choice is refused it asks with "auto"; when a
    model does not accept images it continues without the frames (and says so); when the answer comes as
    text instead of a tool call, the JSON in the text is used."""

    def __init__(self, *, base_url: str, api_key: str | None, name: str = "El proveedor", dialect: str = "",
                 max_tokens_field: str = "max_tokens", on_usage: Callable[[dict], None] | None = None,
                 transport: Any = None, log: Callable[[str], None] | None = None):
        import httpx

        if not base_url:
            raise LLMError(f"Falta la dirección del servidor de {name}. Complétala en Ajustes.")
        from .ai_settings import credential_transport_error
        if error := credential_transport_error(base_url, api_key):
            raise LLMError(error)
        self.base_url, self.name, self.dialect = base_url.rstrip("/"), name, dialect
        self.max_tokens_field, self.on_usage, self.log = max_tokens_field, on_usage, log or (lambda m: None)
        headers = {"Content-Type": "application/json", "X-Title": "Kairos Studio"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.http = httpx.Client(headers=headers, timeout=httpx.Timeout(300.0, connect=20.0), transport=transport)
        self._no_images: set[str] = set()     # models that refused images once
        self._no_forced: set[str] = set()     # models that refused a forced tool_choice
        self._no_tools: set[str] = set()

    def _post(self, body: dict) -> dict:
        import httpx

        for attempt in range(5):
            try:
                r = self.http.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.HTTPError:
                if attempt < 3:
                    time.sleep(2 << attempt)
                    continue
                raise LLMError(f"No se pudo conectar con {self.name}. Revisa tu conexión o la dirección del servidor.")
            if r.status_code in (429, 500, 502, 503, 504, 529) and attempt < 4:
                wait = r.headers.get("retry-after")
                time.sleep(min(30.0, float(wait)) if wait and wait.replace(".", "", 1).isdigit() else min(30, 3 << attempt))
                continue
            if r.status_code >= 400:
                raise _HTTPError(r.status_code, r.text)
            return r.json()
        raise LLMError(f"{self.name} no respondió tras varios intentos.")

    def _friendly(self, e: "_HTTPError", model: str) -> LLMError:
        text = e.text.lower()
        if e.status in (401, 403):
            return LLMError(f"{self.name} rechazó la API key o no da acceso a {model}. Revísala en Ajustes.")
        if e.status == 402 or "insufficient" in text or "quota" in text or "credit" in text:
            return LLMError(f"La cuenta de {self.name} no tiene saldo o cuota suficiente. Recárgala y retoma el trabajo.")
        if e.status == 404 or "model" in text and ("not found" in text or "does not exist" in text):
            return LLMError(f"{self.name} no encuentra el modelo «{model}». Elige otro en Ajustes.")
        if e.status == 429:
            return LLMError(f"{self.name} limitó las peticiones de tu cuenta. Espera un minuto y retoma el trabajo.")
        return LLMError(f"{self.name} respondió {e.status}: provider request failed")

    def complete(self, *, agent, model, system, user, contract, images=None, max_tokens=8000) -> LLMResult:
        tool_name = f"submit_{agent}"
        images = [] if model in self._no_images else list(images or [])
        tool = {"type": "function", "function": {"name": tool_name, "description": "Submit your final answer. Call this exactly once.",
                                                 "parameters": portable_schema(contract.model_json_schema(), self.dialect)}}

        def body(with_images: bool, forced: bool) -> dict:
            if with_images and images:
                content: Any = [{"type": "text", "text": user}] + [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.standard_b64encode(Path(i).read_bytes()).decode("ascii")}}
                    for i in images]
            else:
                content = user
            payload = {"model": model, self.max_tokens_field: max_tokens,
                    "messages": [{"role": "system", "content": f"{system}\n\nDeliver your final answer by calling the function `{tool_name}` exactly once, "
                                                               "with the complete answer as its arguments. Do not answer in plain text."},
                                 {"role": "user", "content": content}],
                    "tools": [tool],
                    "tool_choice": {"type": "function", "function": {"name": tool_name}} if forced else "auto"}
            if not use_tools:
                payload.pop("tools")
                payload.pop("tool_choice")
                payload["messages"][0]["content"] = system + "\nReturn exactly one JSON object matching this schema. No markdown or commentary.\n" + json.dumps(tool["function"]["parameters"])
            return payload

        with_images, forced = bool(images) and model not in self._no_images, model not in self._no_forced
        use_tools = model not in self._no_tools
        for _ in range(6):
            try:
                resp = self._post(body(with_images, forced))
                break
            except _HTTPError as e:
                text = e.text.lower()
                if e.status == 400 and with_images and any(w in text for w in ("image", "vision", "multimodal", "content type", "image_url")):
                    self._no_images.add(model); with_images = False
                    self.log(f"    {model} no acepta imágenes: se continúa sin los fotogramas.")
                    continue
                if e.status == 400 and forced and "tool_choice" in text:
                    self._no_forced.add(model); forced = False
                    continue
                if e.status in (400, 422) and use_tools and any(w in text for w in ("tools", "function calling")) and any(w in text for w in ("not support", "unsupported", "not allowed", "unknown")):
                    self._no_tools.add(model); use_tools = False
                    self.log(f"    {model} no admite herramientas: se solicita JSON y se valida el contrato.")
                    continue
                if e.status == 400 and "max_tokens" in text and self.max_tokens_field == "max_tokens" and "max_completion_tokens" in text:
                    self.max_tokens_field = "max_completion_tokens"
                    continue
                raise self._friendly(e, model)
        else:
            raise LLMError(f"{self.name} rechazó la petición de {agent}.")

        used = resp.get("model") or model
        u = resp.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens") or 0, "output_tokens": u.get("completion_tokens") or 0}
        if self.on_usage:   # recorded before any check, because a rejected answer was still billed
            self.on_usage({"agent": agent, "model": used, "input": usage["input_tokens"], "output": usage["output_tokens"]})
        choice = (resp.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{agent}: la respuesta se cortó por max_tokens ({max_tokens}).")
        msg = choice.get("message") or {}
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name") in (tool_name, None, ""):
                args = fn.get("arguments")
                data = args if isinstance(args, dict) else parse_json_answer(args)
                if isinstance(data, dict):
                    return LLMResult(data=data, model=used, usage=usage)
        if choice.get("finish_reason") == "length":
            raise LLMError(f"{agent}: la respuesta se cortó por max_tokens ({max_tokens}).")
        if (data := parse_json_answer(msg.get("content"))) is not None:
            return LLMResult(data=data, model=used, usage=usage)
        raise LLMError(f"{agent}: la respuesta no incluyó la llamada a {tool_name} (finish_reason={choice.get('finish_reason')}).")


class _HTTPError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"{status}: {text[:200]}")
        self.status, self.text = status, text


class OfflineLLM(LLMClient):
    """Marker client. Subagents see `offline` and use their heuristic instead of calling a model."""

    offline = True


class ScriptedLLM(LLMClient):
    """Test double: returns canned answers per agent. Each answer is a dict, or a callable that
    receives the user prompt and returns a dict. Answers are consumed in order; the last repeats."""

    def __init__(self, script: dict[str, list[dict | Callable[[str], dict]]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[dict] = []

    def complete(self, *, agent, model, system, user, contract, images=None, max_tokens=8000) -> LLMResult:
        self.calls.append({"agent": agent, "model": model, "user": user, "images": len(images or [])})
        answers = self.script.get(agent)
        if not answers:
            raise LLMError(f"ScriptedLLM: sin respuesta para {agent}")
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        data = answer(user) if callable(answer) else answer
        return LLMResult(data=data, model=f"scripted:{model}", usage={"input_tokens": 0, "output_tokens": 0})


class PendingAnswer(RuntimeError):
    """Replay mode: the prompt was written to disk and no answer file exists yet."""


class ReplayLLM(LLMClient):
    """Development aid. Writes every prompt a subagent would send to `<dir>/<agent>_<key>.prompt.md`
    and reads the answer from `<agent>_<key>.answer.json`. Lets you see exactly what each subagent
    receives, and replay hand-written or previously captured answers without calling the API."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def complete(self, *, agent, model, system, user, contract, images=None, max_tokens=8000) -> LLMResult:
        import hashlib
        import json

        key = hashlib.sha1(user.encode()).hexdigest()[:8]
        answer = self.dir / f"{agent}_{key}.answer.json"
        if not answer.exists():
            listing = "\n".join(f"- {p}" for p in images or []) or "(none)"
            (self.dir / f"{agent}_{key}.prompt.md").write_text(
                f"# SYSTEM\n\n{system}\n\n# USER\n\n{user}\n\n# IMAGES\n\n{listing}\n\n# ANSWER SCHEMA\n\n"
                f"```json\n{json.dumps(contract.model_json_schema(), indent=1)}\n```\n", encoding="utf-8")
            raise PendingAnswer(f"Falta la respuesta {answer.name}. El prompt está en {self.dir}.")
        return LLMResult(data=json.loads(answer.read_text(encoding="utf-8")), model=f"replay:{model}", usage={})


def make_llm(provider: str, api_key: str | None, replay_dir: str | Path | None = None,
             on_usage: Callable[[dict], None] | None = None, settings: Any = None,
             log: Callable[[str], None] | None = None) -> LLMClient:
    """provider is the mode: "offline", "replay", or online ("anthropic", kept as the historic name).
    Online, `settings` (when given) says which AI provider was chosen in Ajustes."""
    if provider == "offline":
        return OfflineLLM()
    if provider == "replay":
        return ReplayLLM(replay_dir or "replay")
    if provider not in ("anthropic", "online"):
        raise LLMError(f"Proveedor LLM desconocido: {provider}")
    if settings is not None and settings.ai_kind == "openai":
        if settings.ai_missing:
            raise LLMError(settings.ai_missing)
        return OpenAICompatLLM(base_url=settings.ai_base_url, api_key=api_key, name=settings.ai_name, dialect=settings.ai_dialect,
                               max_tokens_field=settings.ai_max_tokens_field, on_usage=on_usage, log=log)
    if settings is not None and not api_key and settings.ai_missing:
        raise LLMError(settings.ai_missing)
    return AnthropicLLM(api_key, on_usage=on_usage)
