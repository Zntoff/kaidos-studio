"""Reviewer subagent: the gate before Output. It sees only finished artefacts (clip, EDL,
captions, metadata), never the Editing subagent's reasoning, and can block a clip."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..media import captions as cap
from ..media import ffmpeg
from ..rights import rights_ok
from ..schemas import (EDL, CaptionResult, Check, MetadataSet, RenderResult, ReviewJudgement, ReviewVerdict,
                       SourceRecord, Transcript)
from .base import AgentFailed, StepMeta, Subagent
from .metadata import PLATFORMS, find_terms, load_spoiler_terms

FIXABLE = {"variety", "value_add", "value_add_review"}
HUMAN = "needs_human"


@dataclass
class ReviewInput:
    edl: EDL
    source: SourceRecord
    spoken_text: str
    captions: CaptionResult
    metadata: MetadataSet
    renders: RenderResult
    recent: list[dict]
    spoiler_terms: list[str]
    frames: list[Path] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class ReviewerAgent(Subagent):
    name = "reviewer"
    tier = "superior"
    contract = ReviewJudgement
    max_tokens = 2000

    def run(self, edl: EDL, source: SourceRecord, transcript: Transcript, captions: CaptionResult,
            metadata: MetadataSet, renders: RenderResult, recent: list[dict], work_dir: Path) -> tuple[ReviewVerdict, StepMeta]:
        spoken = " ".join(w.w for w in cap.clip_words(transcript, edl.source.start, edl.source.end))
        inp = ReviewInput(edl=edl, source=source, spoken_text=spoken, captions=captions, metadata=metadata,
                          renders=renders, recent=recent, spoiler_terms=load_spoiler_terms(self.s.spoilers_file))
        checks = self.deterministic_checks(inp)
        human_reasons: list[str] = [c.detail for c in checks if c.name == "spoiler_keywords" and c.status == "warn"]
        meta = StepMeta(attempts=1, model="deterministic")

        hard_fail = any(c.status == "fail" and c.name not in FIXABLE for c in checks)
        if self.ctx.llm.offline:
            checks.append(Check(name="claude_review", status="warn", detail="No ejecutado: modo offline. Spoilers y valor propio sin revisar."))
            human_reasons.append("revisión de Claude no ejecutada (modo offline)")
        elif not hard_fail:  # no point paying for a judgement on a clip that is already blocked
            first = next(iter(renders.renders.values()))
            inp.frames = ffmpeg.extract_frames(first.path, work_dir / "review_frames")
            try:
                judgement, meta = self.decide(inp)
            except AgentFailed as e:
                checks.append(Check(name="claude_review", status="warn", detail=f"El revisor no respondió con un veredicto válido: {e}"))
                human_reasons.append("el revisor no entregó veredicto")
                meta = StepMeta(attempts=e.attempts, model=self.s.model_for(self.tier, self.name))
            else:
                sp, va = judgement.spoiler, judgement.value_add
                checks.append(Check(name="spoiler_review", status={"pass": "pass", "fail": "fail", "unsure": "warn"}[sp.verdict], detail=sp.reason))
                checks.append(Check(name="value_add_review", status={"pass": "pass", "fail": "fail", "unsure": "warn"}[va.verdict], detail=va.reason))
                if judgement.policy_notes:
                    checks.append(Check(name="policy_notes", status="warn", detail=judgement.policy_notes))
                human_reasons += [f"{name}: {j.reason}" for name, j in (("spoiler", sp), ("valor propio", va)) if j.verdict == "unsure"]

        fails = [c for c in checks if c.status == "fail"]
        reviewer = meta.model or ""
        if fails:
            fixable = all(c.name in FIXABLE for c in fails)
            return ReviewVerdict(status="rejected", checks=checks, fixable=fixable, reviewer=reviewer,
                                 feedback="\n".join(f"- {c.name}: {c.detail}" for c in fails)), meta
        if human_reasons:
            return ReviewVerdict(status=HUMAN, checks=checks, feedback="; ".join(human_reasons), reviewer=reviewer), meta
        return ReviewVerdict(status="approved", checks=checks, reviewer=reviewer), meta

    # ---- deterministic guards ----
    def deterministic_checks(self, inp: ReviewInput) -> list[Check]:
        s, edl = self.s, inp.edl
        checks: list[Check] = []

        ok, detail = rights_ok(inp.source)
        checks.append(Check(name="rights", status="pass" if ok else "fail", detail=detail))

        bad_res = [f"{r.lang}: {r.width}x{r.height}" for r in inp.renders.renders.values() if (r.width, r.height) != (s.width, s.height)]
        checks.append(Check(name="resolution", status="fail" if bad_res else "pass", detail="; ".join(bad_res) or f"{s.width}x{s.height}"))

        lo, hi = s.clip_min_s * 0.6 - 0.5, s.clip_max_s + 0.5
        bad_dur = [f"{r.lang}: {r.duration:.1f}s" for r in inp.renders.renders.values()
                   if not (lo <= r.duration <= hi) or abs(r.duration - edl.duration) > 0.35]
        checks.append(Check(name="duration", status="fail" if bad_dur else "pass",
                            detail="; ".join(bad_dur) or f"{edl.duration:.1f}s"))

        loud_fail, loud_warn, loud_ok = [], [], []
        for r in inp.renders.renders.values():
            if not r.normalized or r.lufs is None:
                loud_warn.append(f"{r.lang}: la fuente no tiene audio en este tramo; no se normalizó")
            elif abs(r.lufs - edl.audio.normalize_lufs) > s.lufs_tolerance:
                loud_fail.append(f"{r.lang}: {r.lufs:.1f} LUFS (objetivo {edl.audio.normalize_lufs:.0f} ±{s.lufs_tolerance:.0f})")
            elif r.true_peak is not None and r.true_peak > s.true_peak + 1.0:
                loud_fail.append(f"{r.lang}: pico real {r.true_peak:.1f} dBTP")
            else:
                loud_ok.append(f"{r.lang}: {r.lufs:.1f} LUFS, pico {r.true_peak:.1f} dBTP")
        checks.append(Check(name="loudness", status="fail" if loud_fail else "warn" if loud_warn else "pass",
                            detail="; ".join(loud_fail or loud_warn or loud_ok)))

        checks.append(self._caption_timing(inp))
        checks.append(self._safe_zone(inp))

        # Spoilers: the keyword list is blunt, so a hit sends the clip to a person instead of rejecting it.
        texts = [inp.spoken_text, *edl.hook.text.values(), *(t for n in edl.commentary.notes for t in n.text.values())]
        for lm in inp.metadata.per_language.values():
            for p in PLATFORMS:
                pm = getattr(lm, p)
                texts += [pm.title, pm.description, " ".join(pm.hashtags)]
        hits = sorted(set(find_terms(" \n ".join(texts), inp.spoiler_terms)))
        if hits or edl.risk.spoiler:
            why = f"términos de la lista de spoilers: {', '.join(hits)}" if hits else f"el editor marcó riesgo de spoiler: {edl.risk.notes}"
            checks.append(Check(name="spoiler_keywords", status="warn", detail=why))
        else:
            checks.append(Check(name="spoiler_keywords", status="pass", detail=f"{len(inp.spoiler_terms)} términos comprobados"))

        # Own value: the commentary must exist and must not just repeat what is said in the clip.
        spoken = set(_tokens(inp.spoken_text))
        problems = []
        for lang in edl.languages:
            words = [t for n in edl.commentary.notes for t in _tokens(n.text.get(lang, ""))]
            if len(words) < 8:
                problems.append(f"{lang}: solo {len(words)} palabras de comentario")
            elif lang == edl.source_language and spoken and sum(w in spoken for w in words) / len(words) > 0.9:
                problems.append(f"{lang}: el comentario repite el audio del clip")
        checks.append(Check(name="value_add", status="fail" if problems else "pass",
                            detail="; ".join(problems) or "comentario propio presente"))

        # Variety: no near-duplicate hooks across the channel's recent clips.
        dupes = []
        for lang, hook in edl.hook.text.items():
            for prev in inp.recent:
                other = (prev.get("hook_text") or {}).get(lang, "")
                if other and difflib.SequenceMatcher(None, hook.lower(), other.lower()).ratio() >= 0.85:
                    dupes.append(f"{lang}: «{hook}» se parece a «{other}» ({prev['id']})")
        checks.append(Check(name="variety", status="fail" if dupes else "pass", detail="; ".join(dupes) or "gancho distinto a los recientes"))
        return checks

    def _caption_timing(self, inp: ReviewInput) -> Check:
        problems = []
        dur = inp.edl.duration
        for lang, track in inp.captions.tracks.items():
            prev_end = 0.0
            for cue in track.cues:
                if cue.start < -0.01 or cue.end > dur + 0.05 or cue.end <= cue.start:
                    problems.append(f"{lang}: cue fuera del clip ({cue.start:.2f}-{cue.end:.2f})")
                    break
                if cue.start < prev_end - 0.01:
                    problems.append(f"{lang}: cues solapados en {cue.start:.2f}s")
                    break
                if abs(cue.start - cue.words[0].start) > 0.15:
                    problems.append(f"{lang}: desfase de {abs(cue.start - cue.words[0].start) * 1000:.0f} ms en {cue.start:.2f}s")
                    break
                prev_end = cue.end
        return Check(name="caption_timing", status="fail" if problems else "pass",
                     detail="; ".join(problems) or "cues dentro del clip, sin solapes, desfase < 150 ms")

    def _safe_zone(self, inp: ReviewInput) -> Check:
        s, edl = self.s, inp.edl
        g = cap.geometry(edl, inp.source.width, inp.source.height, s)
        style = edl.captions.style
        family, bold = cap.caption_font(style, s)
        upper = cap.STYLE_SPECS[style]["upper"]
        problems = []
        if not (g["top_safe"] <= g["caption_y"] - 60 and g["caption_y"] + 60 <= g["bottom_safe"]):
            problems.append("la línea de subtítulos queda fuera de la zona segura vertical")
        for lang, track in inp.captions.tracks.items():
            for cue in track.cues:
                size = cap.cue_font_size(cue.text, style, s, g["safe_width"], edl.captions.scale)
                width = cap.text_width(cue.text.upper() if upper else cue.text, family, size, bold) * 1.2
                if width > g["safe_width"] + 2:
                    problems.append(f"{lang}: «{cue.text}» mide {width:.0f}px (máx {g['safe_width']})")
                    break
        for lang in edl.languages:
            blocks = [(edl.hook.text.get(lang, "").upper(), s.caption_font, 86, False)]
            blocks += [(n.text.get(lang, ""), s.text_font, 46, True) for n in edl.commentary.notes]
            for text, fam, size, is_bold in blocks:
                lines = cap.wrap(text, fam, size, g["safe_width"] - 40, is_bold)
                height = len(lines) * size * 1.3
                if g["top_y"] - height / 2 < g["top_safe"] - 60 or len(lines) > 5:
                    problems.append(f"{lang}: bloque de texto demasiado alto ({len(lines)} líneas): «{text[:40]}»")
                if any(cap.text_width(l, fam, size, is_bold) > g["safe_width"] for l in lines):
                    problems.append(f"{lang}: una línea no cabe en la zona segura: «{text[:40]}»")
        return Check(name="safe_zone", status="fail" if problems else "pass",
                     detail="; ".join(problems[:4]) or f"todo el texto dentro de {g['safe_width']}px y de la zona segura vertical")

    # ---- Claude's judgement ----
    def images(self, inp: ReviewInput) -> list[Path]:
        return inp.frames

    def build_user(self, inp: ReviewInput) -> str:
        e = inp.edl
        notes = "\n".join(f"- at {n.t:.1f}s: " + " / ".join(f"[{k}] {v}" for k, v in n.text.items()) for n in e.commentary.notes)
        meta = "\n".join(f"- [{lang}] {lm.youtube.title} | {lm.youtube.description[:200]}" for lang, lm in inp.metadata.per_language.items())
        return (
            f"# Finished clip ({e.duration:.0f}s). {len(inp.frames)} frames of the rendered clip are attached, in order.\n\n"
            f"Rights status of the source: {inp.source.rights_status} ({inp.source.evidence})\n\n"
            f"## What is said in the clip ({e.source_language})\n{inp.spoken_text or '(no speech)'}\n\n"
            "## Hook\n" + " / ".join(f"[{k}] {v}" for k, v in e.hook.text.items()) + "\n\n"
            f"## Commentary added by the channel\n{notes}\n\n"
            f"## Titles and descriptions\n{meta}\n\n"
            f"## Spoiler keyword list (maintained by the channel owner)\n{', '.join(inp.spoiler_terms) or '(empty)'}\n"
        )

    def offline(self, inp: ReviewInput) -> dict:  # never called: run() skips the judgement offline
        return {"spoiler": {"verdict": "unsure", "reason": "offline"}, "value_add": {"verdict": "unsure", "reason": "offline"}}
