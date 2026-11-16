"""Contracts between subagents. Every subagent output is validated against one of these.

Two families:
  * "proposal" models are what Claude writes. They anchor everything to segment or word
    indexes, never to raw timestamps, so a cut can only land on a real word boundary.
  * "final" models (Candidate, EDL, CaptionTrack...) are what code derives from a proposal
    and what the renderer reads.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RightsStatus = Literal["own", "written_permission", "official_press", "cc_licensed"]
Layout = Literal["gameplay_blur_bg", "center_crop"]
CaptionStyle = Literal["bold", "bounce", "clean", "impact", "comic", "neon", "pixel", "soft"]
EffectType = Literal["punch_in", "zoom_slow", "shake", "flash", "glitch", "blur", "bw"]
AnimIn = Literal["none", "fade", "pop", "zoom", "slide_up", "slide_down", "slide_left", "slide_right"]
AnimOut = Literal["none", "fade", "shrink"]
HEX = r"^#[0-9A-Fa-f]{6}$"
Localized = dict[str, str]  # language code -> text


# ---------- source ----------
class SourceRecord(BaseModel):
    project_id: str = "project_default"
    id: str
    path: str
    sha256: str
    rights_status: RightsStatus
    evidence: str
    credit: str | None = None
    language: str | None = None
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


# ---------- transcript and signals ----------
class Word(BaseModel):
    w: str
    start: float
    end: float


class Segment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word]


class Transcript(BaseModel):
    language: str
    duration: float
    segments: list[Segment]

    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]


class Signals(BaseModel):
    hop_s: float
    energy: list[float]  # 0..1 per hop, normalised to the loudest moment of the video
    scene_cuts: list[float]


# ---------- analysis ----------
class CandidateProposal(BaseModel):
    start_segment: int = Field(ge=0)
    end_segment: int = Field(ge=0)
    score: float = Field(ge=0, le=100)
    category: str = Field(max_length=40)
    reason: str = Field(max_length=400)
    hook_idea: str = Field(default="", max_length=160)


class AnalysisProposal(BaseModel):
    candidates: list[CandidateProposal]


class Candidate(BaseModel):
    id: str
    start_segment: int
    end_segment: int
    start: float
    end: float
    score: float
    category: str
    reason: str
    hook_idea: str = ""


class AnalysisResult(BaseModel):
    transcript_path: str
    signals_path: str
    candidates: list[Candidate]


# ---------- editing ----------
LOCALIZED_DOC = 'Object keyed by language code with the text in that language, e.g. {"en": "...", "es": "..."}. Include every requested language.'


class HookProposal(BaseModel):
    text: Localized = Field(description=LOCALIZED_DOC)
    duration: float = Field(ge=1.0, le=3.0)


class NoteProposal(BaseModel):
    at_word: int = Field(ge=0)
    duration: float = Field(ge=1.5, le=6.0)
    text: Localized = Field(description=LOCALIZED_DOC)


class CommentaryProposal(BaseModel):
    mode: Literal["onscreen", "voiceover"] = "onscreen"
    notes: list[NoteProposal]


class CaptionPlan(BaseModel):
    x: float | None = Field(default=None, ge=0, le=1)
    style: CaptionStyle
    highlight_keywords: list[str] = Field(default_factory=list, max_length=12)
    y: float | None = Field(default=None, ge=0.05, le=0.95, description="Leave empty: vertical position, set by the person editing.")
    scale: float = Field(default=1.0, ge=0.5, le=1.6, description="Leave at 1: size multiplier, set by the person editing.")


class SfxProposal(BaseModel):
    at_word: int = Field(ge=0)
    id: str


class AudioProposal(BaseModel):
    sfx: list[SfxProposal] = Field(default_factory=list, max_length=8)
    music_id: str | None = None
    duck_music: bool = True


class EffectProposal(BaseModel):
    at_word: int = Field(ge=0)
    type: EffectType = "punch_in"
    duration: float = Field(ge=0.2, le=4.0)


class RiskSelfReport(BaseModel):
    spoiler: bool = False
    notes: str = ""


class EditDecision(BaseModel):
    """What the Editing subagent writes. Word indexes refer to the numbered word list it was given."""

    start_word: int = Field(ge=0)
    end_word: int = Field(ge=0)
    layout: Layout
    crop_x: float = Field(default=0.5, ge=0.0, le=1.0)
    hook: HookProposal
    commentary: CommentaryProposal
    captions: CaptionPlan
    audio: AudioProposal = Field(default_factory=AudioProposal)
    effects: list[EffectProposal] = Field(default_factory=list, max_length=6)
    risk: RiskSelfReport = Field(default_factory=RiskSelfReport)


class EdlSource(BaseModel):
    id: str
    start: float
    end: float


class EdlHook(BaseModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    text: Localized
    duration: float


class EdlNote(BaseModel):
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    t: float
    duration: float
    text: Localized


class EdlCommentary(BaseModel):
    mode: Literal["onscreen", "voiceover"]
    notes: list[EdlNote]


class EdlSfx(BaseModel):
    t: float
    id: str
    gain: float = Field(default=1.0, ge=0.0, le=3.0)  # multiplies the library gain


class EdlAudio(BaseModel):
    normalize_lufs: float
    music_id: str | None = None
    duck_music: bool = True
    sfx: list[EdlSfx] = Field(default_factory=list)
    voice_gain: float = Field(default=1.0, ge=0.0, le=3.0)
    music_gain: float = Field(default=1.0, ge=0.0, le=3.0)
    voice_enhance: bool = False  # high-pass + gentle compression on the source audio


class EdlEffect(BaseModel):
    t: float
    type: EffectType
    duration: float
    intensity: float = Field(default=1.0, ge=0.2, le=2.0)


class EdlColor(BaseModel):
    """Colour grade of the whole clip: a named look (assets/studio/catalog.json) plus manual
    adjustments on top. Everything is -1..1 (or 0..1) and 0 means untouched."""

    look: str = "none"
    look_amount: float = Field(default=1.0, ge=0.0, le=1.0)
    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=0.0, ge=-1.0, le=1.0)
    saturation: float = Field(default=0.0, ge=-1.0, le=1.0)
    temperature: float = Field(default=0.0, ge=-1.0, le=1.0)
    tint: float = Field(default=0.0, ge=-1.0, le=1.0)
    fade: float = Field(default=0.0, ge=0.0, le=1.0)
    vignette: float = Field(default=0.0, ge=0.0, le=1.0)


class EdlText(BaseModel):
    """A free text layer. x / y are the centre of the block, as a fraction of the frame."""

    t: float
    duration: float
    text: Localized
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.3, ge=0.0, le=1.0)
    font: str = "anton"
    size: int = Field(default=80, ge=16, le=300)  # em size in pixels of the 1080-wide frame
    color: str = Field(default="#FFFFFF", pattern=HEX)
    stroke: str = Field(default="#000000", pattern=HEX)
    stroke_w: float = Field(default=6.0, ge=0.0, le=24.0)
    box: str = Field(default="", pattern=r"^(#[0-9A-Fa-f]{6})?$")  # "" = no box behind the text
    box_opacity: float = Field(default=1.0, ge=0.1, le=1.0)
    opacity: float = Field(default=1.0, ge=0.1, le=1.0)
    glow: float = Field(default=0.0, ge=0.0, le=12.0)
    upper: bool = False
    rotate: float = Field(default=0.0, ge=-45.0, le=45.0)
    anim_in: AnimIn = "fade"
    anim_out: AnimOut = "fade"


class EdlTransitions(BaseModel):
    intro: Literal["none", "fade", "flash"] = "none"
    intro_d: float = Field(default=0.4, ge=0.1, le=2.0)
    outro: Literal["none", "fade"] = "none"
    outro_d: float = Field(default=0.4, ge=0.1, le=2.0)


class EdlProgress(BaseModel):
    """A bar that fills as the clip plays."""

    on: bool = False
    color: str = Field(default="#FFE500", pattern=HEX)
    position: Literal["top", "bottom"] = "top"
    height: int = Field(default=12, ge=4, le=40)


class EdlRisk(BaseModel):
    spoiler: bool
    rights_ok: bool
    notes: str = ""


class EDL(BaseModel):
    """Edit Decision List: the only thing the renderer reads. Times are seconds from clip start,
    except source.start / source.end, which are seconds in the source video."""

    clip_id: str
    source: EdlSource
    source_language: str
    languages: list[str]
    layout: Layout
    crop_x: float = 0.5
    hook: EdlHook
    commentary: EdlCommentary
    captions: CaptionPlan
    audio: EdlAudio
    effects: list[EdlEffect] = Field(default_factory=list)
    color: EdlColor = Field(default_factory=EdlColor)
    texts: list[EdlText] = Field(default_factory=list)
    transitions: EdlTransitions = Field(default_factory=EdlTransitions)
    progress: EdlProgress = Field(default_factory=EdlProgress)
    risk: EdlRisk
    revision: int = 0

    @property
    def duration(self) -> float:
        return self.source.end - self.source.start


# ---------- captions ----------
class PhraseEdit(BaseModel):
    id: int
    text: str
    highlight: list[str] = Field(default_factory=list)
    translations: Localized = Field(default_factory=dict, description='Object keyed by target language code, e.g. {"es": "..."}.')
    translation_highlight: dict[str, list[str]] = Field(
        default_factory=dict, description='Per target language, the words of that translation to highlight, e.g. {"es": ["puente"]}.')


class CaptionEdit(BaseModel):
    phrases: list[PhraseEdit]


class CaptionWord(BaseModel):
    w: str
    start: float
    end: float
    hl: bool = False


class Cue(BaseModel):
    start: float
    end: float
    words: list[CaptionWord]

    @property
    def text(self) -> str:
        return " ".join(w.w for w in self.words)


class CaptionTrack(BaseModel):
    lang: str
    style: CaptionStyle
    word_timed: bool  # False for translated tracks: timing is spread across each phrase
    cues: list[Cue]


class CaptionResult(BaseModel):
    tracks: dict[str, CaptionTrack]


# ---------- metadata ----------
class PlatformMeta(BaseModel):
    title: str = ""
    description: str
    hashtags: list[str] = Field(default_factory=list)


class LanguageMeta(BaseModel):
    youtube: PlatformMeta
    tiktok: PlatformMeta
    instagram: PlatformMeta


class MetadataSet(BaseModel):
    per_language: dict[str, LanguageMeta] = Field(description='Object keyed by language code, e.g. {"en": {...}, "es": {...}}.')


# ---------- review ----------
class Judgement(BaseModel):
    verdict: Literal["pass", "fail", "unsure"]
    reason: str = Field(max_length=500)


class ReviewJudgement(BaseModel):
    """What the Reviewer subagent writes. 'fail' on spoiler means the clip contains a spoiler."""

    spoiler: Judgement
    value_add: Judgement
    policy_notes: str = ""


class Check(BaseModel):
    name: str
    status: Literal["pass", "fail", "warn"]
    detail: str = ""


class ReviewVerdict(BaseModel):
    status: Literal["approved", "rejected", "needs_human"]
    checks: list[Check]
    fixable: bool = False
    feedback: str = ""
    reviewer: str = ""


# ---------- render and output ----------
class RenderReport(BaseModel):
    lang: str
    path: str
    width: int
    height: int
    duration: float
    lufs: float | None
    true_peak: float | None
    normalized: bool = True  # False when the clip had no programme audio to normalise
    ass_path: str
    srt_path: str


class RenderResult(BaseModel):
    renders: dict[str, RenderReport]


class PackageInfo(BaseModel):
    clip_id: str
    status: str
    dir: str
    files: dict[str, dict[str, str]]  # lang -> {video, srt, metadata}
