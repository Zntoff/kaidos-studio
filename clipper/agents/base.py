"""Common behaviour of every subagent: a versioned system prompt, a JSON contract, and a
bounded retry loop that feeds validation errors back to the model."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..llm import LLMClient, LLMError
from ..store import Store


class ContractError(ValueError):
    """The output parsed, but breaks a rule the schema cannot express."""


class AgentFailed(RuntimeError):
    def __init__(self, agent: str, message: str, attempts: int):
        super().__init__(f"{agent}: {message}")
        self.agent, self.attempts = agent, attempts


@dataclass
class Context:
    settings: Settings
    store: Store
    llm: LLMClient
    log: Callable[[str], None] = print


@dataclass
class StepMeta:
    attempts: int = 1
    prompt_version: str | None = None
    model: str | None = None
    usage: dict = field(default_factory=dict)

    def merge(self, other: "StepMeta") -> None:
        self.attempts = max(self.attempts, other.attempts)
        self.prompt_version = other.prompt_version or self.prompt_version
        self.model = other.model or self.model
        for k, v in (other.usage or {}).items():
            if isinstance(v, (int, float)):
                self.usage[k] = self.usage.get(k, 0) + v


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


class Subagent:
    name: str = ""
    tier: str = "standard"  # fast | standard | superior
    contract: type[BaseModel]
    max_tokens: int = 8000

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.s = ctx.settings

    # ---- prompt ----
    def system_prompt(self) -> tuple[str, str]:
        path: Path = self.s.prompts_dir / f"{self.name}.md"
        text = path.read_text(encoding="utf-8")
        m = re.match(r"<!--\s*version:\s*([\w.]+)\s*-->\s*", text)
        version = m.group(1) if m else "0"
        body = text[m.end():] if m else text
        digest = hashlib.sha256(body.encode()).hexdigest()[:8]
        return f"{self.name}@v{version}#{digest}", body

    # ---- to implement per subagent ----
    def build_user(self, inp: Any) -> str:
        raise NotImplementedError

    def images(self, inp: Any) -> list[Path]:
        return []

    def offline(self, inp: Any) -> dict:
        raise NotImplementedError

    def check(self, inp: Any, out: BaseModel) -> None:
        """Raise ContractError when the output breaks a semantic rule."""

    # ---- decision loop ----
    def decide(self, inp: Any) -> tuple[BaseModel, StepMeta]:
        if self.ctx.llm.offline:
            out = self.contract.model_validate(self.offline(inp))
            self.check(inp, out)
            return out, StepMeta(attempts=1, prompt_version=None, model="offline-heuristic")

        version, system = self.system_prompt()
        model = self.s.model_for(self.tier, self.name)
        user = self.build_user(inp)
        images = self.images(inp)
        meta = StepMeta(attempts=0, prompt_version=version, model=model)
        feedback = ""
        last_error = ""
        for attempt in range(1, self.s.max_retries + 2):
            meta.attempts = attempt
            try:
                res = self.ctx.llm.complete(agent=self.name, model=model, system=system, user=user + feedback,
                                            contract=self.contract, images=images, max_tokens=self.max_tokens)
            except LLMError as e:
                last_error = str(e)
                feedback = f"\n\n# Your previous attempt failed\n{last_error}\nAnswer again, shorter if needed."
                continue
            meta.model = res.model or model
            for k, v in (res.usage or {}).items():
                if isinstance(v, (int, float)):
                    meta.usage[k] = meta.usage.get(k, 0) + v
            try:
                out = self.contract.model_validate(res.data)
                self.check(inp, out)
                return out, meta
            except (ValidationError, ContractError) as e:
                last_error = str(e)
                self.ctx.log(f"    {self.name}: intento {attempt} no pasó el contrato: {last_error[:200]}")
                feedback = ("\n\n# Your previous answer was rejected by validation\n"
                            f"Previous answer:\n{dumps(res.data)[:6000]}\n\nValidation error:\n{last_error[:2000]}\n\n"
                            "Fix exactly what the error names and submit the full answer again.")
        raise AgentFailed(self.name, f"no pasó el contrato tras {meta.attempts} intentos: {last_error[:500]}", meta.attempts)
