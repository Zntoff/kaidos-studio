"""Runtime settings, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_RIGHTS = ("own", "written_permission", "official_press", "cc_licensed")
TIERS = ("fast", "standard", "superior")                 # Haiku, Sonnet, Opus by default
LAYOUT_CHOICES = ("auto", "gameplay_blur_bg", "center_crop")
CAPTION_CHOICES = ("auto", "bold", "bounce", "clean", "impact", "comic", "neon", "pixel", "soft")
GENERATION_AGENTS = ("editing", "captions", "metadata", "reviewer")  # everything after the analysis


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class SafeZone:
    """Pixels of a 1080x1920 frame kept free of text, because each platform draws its
    own interface there. These are working values, not official figures: adjust them
    after checking a real upload on each platform."""

    top: int = 220
    bottom: int = 420
    side: int = 120


@dataclass(frozen=True)
class PlatformLimits:
    """Conservative limits that fit YouTube, TikTok and Instagram at once."""

    title_max: int = 100
    description_max: int = 2200
    hashtags_max: int = 5


@dataclass
class Settings:
    data_dir: Path
    database_url: str
    llm_provider: str  # "anthropic" (= online, with the provider chosen in Ajustes) | "offline" | "replay"
    api_key: str | None   # key of the active AI provider (see ai_settings)
    model_fast: str
    model_standard: str
    model_superior: str
    languages: list[str]
    whisper_model: str
    whisper_device: str
    whisper_compute: str
    scene_mode: str = "full"  # full | keyframes | off
    encoder: str = "libx264"  # libx264 | h264_nvenc (NVIDIA GPU)
    render_quality: int = 19
    target_lufs: float = -14.0
    true_peak: float = -1.0
    lufs_tolerance: float = 1.0
    clip_min_s: float = 20.0
    clip_max_s: float = 90.0
    max_clips: int = 12
    width: int = 1080
    height: int = 1920
    fps: int = 30
    caption_font: str = "Inter Black"
    text_font: str = "Inter"
    publish_slots: list[str] = field(default_factory=lambda: ["12:00", "19:00"])
    safe: SafeZone = field(default_factory=SafeZone)
    limits: PlatformLimits = field(default_factory=PlatformLimits)
    sfx_dir: Path = REPO_ROOT / "assets" / "sfx"
    fonts_dir: Path = REPO_ROOT / "assets" / "fonts"
    studio_dir: Path = REPO_ROOT / "assets" / "studio"
    spoilers_file: Path = REPO_ROOT / "config" / "spoilers.txt"
    prompts_dir: Path = REPO_ROOT / "clipper" / "prompts"
    max_retries: int = 2  # contract retries per subagent, after the first attempt
    # The AI provider chosen in Ajustes (config/providers.json); filled by ai_settings.apply.
    ai_provider: str = "anthropic"
    ai_kind: str = "anthropic"            # anthropic | openai (OpenAI-compatible Chat Completions)
    ai_name: str = "Anthropic · Claude"
    ai_base_url: str = ""
    ai_dialect: str = ""                  # "gemini": strip schema keywords Gemini rejects
    ai_max_tokens_field: str = "max_tokens"
    ai_missing: str | None = None         # why the provider cannot run yet, for the person
    # Per-job choices made by the person in the panel (see apply_options).
    layout_choice: str = "auto"       # "auto": the Editing subagent decides
    caption_choice: str = "auto"
    agent_models: dict = field(default_factory=dict)   # agent name -> model id, beats the agent's default tier
    options: dict = field(default_factory=dict)        # the raw choices, stored with the job

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        data_dir = Path(_env("CLIPPER_DATA_DIR", str(REPO_ROOT / "data"))).resolve()
        s = cls(
            data_dir=data_dir,
            database_url=_env("DATABASE_URL", f"sqlite:///{data_dir / 'clipper.db'}"),
            llm_provider=_env("CLIPPER_LLM", "anthropic"),
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            model_fast=_env("CLIPPER_MODEL_FAST", "claude-haiku-5-5"),
            model_standard=_env("CLIPPER_MODEL_STANDARD", "claude-sonnet-5-5"),
            model_superior=_env("CLIPPER_MODEL_SUPERIOR", "claude-opus-5-5"),
            languages=_env_list("CLIPPER_LANGUAGES", "en,es"),
            whisper_model=_env("CLIPPER_WHISPER_MODEL", "small"),
            whisper_device=_env("CLIPPER_WHISPER_DEVICE", "cpu"),
            whisper_compute=_env("CLIPPER_WHISPER_COMPUTE", "int8"),
            scene_mode=_env("CLIPPER_SCENE_MODE", "full"),
            encoder=_env("CLIPPER_ENCODER", "libx264"),
            target_lufs=float(_env("CLIPPER_TARGET_LUFS", "-14")),
            true_peak=float(_env("CLIPPER_TRUE_PEAK", "-1")),
            clip_min_s=float(_env("CLIPPER_CLIP_MIN_S", "20")),
            clip_max_s=float(_env("CLIPPER_CLIP_MAX_S", "90")),
            max_clips=int(_env("CLIPPER_MAX_CLIPS", "12")),
            caption_font=_env("CLIPPER_CAPTION_FONT", "Inter Black"),
            text_font=_env("CLIPPER_TEXT_FONT", "Inter"),
            publish_slots=_env_list("CLIPPER_PUBLISH_SLOTS", "12:00,19:00"),
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        s.data_dir.mkdir(parents=True, exist_ok=True)
        from . import ai_settings

        ai_settings.apply(s)   # provider, key (panel beats environment) and models chosen in Ajustes
        return s

    def model_for(self, tier: str, agent: str | None = None) -> str:
        if agent and self.agent_models.get(agent):
            return self.agent_models[agent]
        return {"fast": self.model_fast, "standard": self.model_standard, "superior": self.model_superior}[tier]

    def apply_options(self, o: dict) -> "Settings":
        """Apply the choices stored with a job: models per stage, picture layout, caption style,
        languages, offline mode. Unknown or empty values leave the default (Claude decides)."""
        o = o or {}
        if o.get("llm") == "offline":
            self.llm_provider = "offline"
        if o.get("languages"):
            self.languages = [x for x in o["languages"] if x]
        layout, caption = o.get("layout") or "auto", o.get("caption_style") or "auto"
        if layout not in LAYOUT_CHOICES or caption not in CAPTION_CHOICES:
            raise ValueError("Estilo no válido.")
        self.layout_choice, self.caption_choice = layout, caption
        models: dict[str, str] = {}
        for key in ("analysis_model", "model"):
            if o.get(key) and o[key] not in TIERS:
                raise ValueError(f"Modelo no válido: {o[key]!r}. Valores: {', '.join(TIERS)}")
        if o.get("analysis_model"):
            models["analysis"] = self.model_for(o["analysis_model"])
        if o.get("model"):
            models.update({a: self.model_for(o["model"]) for a in GENERATION_AGENTS})
        self.agent_models = models
        self.options = {k: o[k] for k in ("analysis_model", "model", "layout", "caption_style") if o.get(k)}
        return self

    def job_dir(self, job_id: str) -> Path:
        d = self.data_dir / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d
