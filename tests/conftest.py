import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from clipper.agents.base import Context  # noqa: E402
from clipper.config import Settings  # noqa: E402
from clipper.llm import OfflineLLM, ScriptedLLM  # noqa: E402
from clipper.rights import register_source  # noqa: E402
from clipper.store import Store  # noqa: E402


@pytest.fixture(scope="session")
def demo(tmp_path_factory):
    """A ~55s synthetic video with speech and its word-timed transcript."""
    import make_demo_video

    out = tmp_path_factory.mktemp("demo")
    make_demo_video.main(str(out), max_lines=14, size="640x360")
    return out / "demo.mp4", out / "demo_transcript.json"


@pytest.fixture
def settings(tmp_path):
    s = Settings.from_env(data_dir=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'test.db'}")
    s.llm_provider, s.languages = "offline", ["en"]
    s.clip_min_s, s.clip_max_s, s.max_clips = 10.0, 22.0, 2
    return s


@pytest.fixture
def store(settings):
    return Store(settings.database_url)


@pytest.fixture
def make_ctx(settings, store):
    def _make(llm=None):
        return Context(settings=settings, store=store, llm=llm or OfflineLLM(), log=lambda m: None)
    return _make


@pytest.fixture
def source(store, demo):
    return register_source(store, demo[0], rights_status="own", evidence="video sintético de prueba", language="en")


# ---- scripted "Claude" answers, built from the prompt each subagent sends ----
def analysis_answer(user: str) -> dict:
    segs = [(int(i), float(a), float(b)) for i, a, b in re.findall(r"^\[(\d+)\] ([\d.]+)-([\d.]+)s", user, re.M)]
    lo, hi = map(float, re.search(r"between (\d+) and (\d+) seconds", user).groups())
    for i, a, _ in segs:
        for j, _, b in segs[i:]:
            if lo + 1 <= b - a <= hi - 1:
                return {"candidates": [{"start_segment": i, "end_segment": j, "score": 88, "category": "stunt",
                                        "reason": "Setup and payoff in one window.", "hook_idea": "He tried the hardest jump"}]}
    raise AssertionError("no window fits")


def editing_answer(langs, hook="This jump should not be possible", note_words=12):
    def answer(user: str) -> dict:
        a, b = map(int, re.search(r"covers words (\d+)\.\.(\d+)", user).groups())
        text = lambda en, es: {k: v for k, v in (("en", en), ("es", es)) if k in langs}
        note = " ".join(["insight"] * note_words)
        return {"start_word": a, "end_word": b, "layout": "gameplay_blur_bg",
                "hook": {"text": text(hook, "Este salto no debería ser posible"), "duration": 2.0},
                "commentary": {"mode": "onscreen", "notes": [
                    {"at_word": a + (b - a) // 2, "duration": 3.0, "text": text(note, "La rampa importa más que la velocidad en este salto del mapa entero")}]},
                "captions": {"style": "bounce", "highlight_keywords": ["jump"]},
                "audio": {"sfx": [{"at_word": a, "id": "whoosh_01"}], "music_id": None, "duck_music": True},
                "effects": [{"at_word": a + (b - a) // 2, "type": "punch_in", "duration": 0.6}],
                "risk": {"spoiler": False, "notes": ""}}
    return answer


def captions_answer(langs):
    def answer(user: str) -> dict:
        phrases = re.findall(r"^\[(\d+)\] (.+)$", user, re.M)
        return {"phrases": [{"id": int(i), "text": t, "highlight": [],
                             "translations": {"es": f"frase traducida número {i}"} if "es" in langs else {},
                             "translation_highlight": {"es": ["traducida"]} if "es" in langs else {}} for i, t in phrases]}
    return answer


def metadata_answer(langs):
    one = lambda title: {p: {"title": title if p == "youtube" else "", "description": "A stunt that needed the right ramp angle.",
                             "hashtags": ["gaming", "#stunt", "#Stunt"]} for p in ("youtube", "tiktok", "instagram")}
    return {"per_language": {lang: one({"en": "He cleared the whole bridge", "es": "Cruzó el puente entero"}[lang]) for lang in langs}}


REVIEW_PASS = {"spoiler": {"verdict": "pass", "reason": "Ordinary gameplay."},
               "value_add": {"verdict": "pass", "reason": "The note explains why it worked."}, "policy_notes": ""}


@pytest.fixture
def scripted():
    def _make(langs=("en",), **overrides):
        script = {"analysis": [analysis_answer], "editing": [editing_answer(langs)], "captions": [captions_answer(langs)],
                  "metadata": [metadata_answer(langs)], "reviewer": [REVIEW_PASS]}
        script.update(overrides)
        return ScriptedLLM(script)
    return _make


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
