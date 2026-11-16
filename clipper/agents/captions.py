"""Captions subagent: cleans up the spoken text, picks words to highlight and translates,
then code turns that into word-by-word cues for every output language."""
from __future__ import annotations

from dataclasses import dataclass

from ..media import captions as cap
from ..schemas import EDL, CaptionEdit, CaptionResult, CaptionTrack, Transcript, Word
from .base import ContractError, StepMeta, Subagent


@dataclass
class CaptionsInput:
    edl: EDL
    phrases: list[list[Word]]
    source_language: str
    languages: list[str]

    @property
    def targets(self) -> list[str]:
        return [lang for lang in self.languages if lang != self.source_language]


class CaptionsAgent(Subagent):
    name = "captions"
    tier = "standard"
    contract = CaptionEdit
    max_tokens = 8000

    def run(self, edl: EDL, transcript: Transcript) -> tuple[CaptionResult, StepMeta]:
        words = cap.clip_words(transcript, edl.source.start, edl.source.end)
        inp = CaptionsInput(edl=edl, phrases=cap.build_phrases(words), source_language=transcript.language, languages=edl.languages)
        if not inp.phrases:  # no speech: the clip carries only the hook and the commentary notes
            empty = {lang: CaptionTrack(lang=lang, style=edl.captions.style, word_timed=False, cues=[]) for lang in edl.languages}
            return CaptionResult(tracks=empty), StepMeta(attempts=1, model="none")
        edit, meta = self.decide(inp)
        by_id = {p.id: p for p in edit.phrases}
        keywords = {cap.norm(k) for k in edl.captions.highlight_keywords}
        tracks: dict[str, CaptionTrack] = {}
        for lang in edl.languages:
            cues, word_timed = [], lang == inp.source_language
            for i, phrase in enumerate(inp.phrases):
                p = by_id[i]
                hl = keywords | {cap.norm(h) for h in p.highlight}
                translated = (p.translations.get(lang) or "").strip()
                if word_timed or not translated:
                    cues += cap.timed_cues(phrase, p.text.split(), hl)
                else:
                    # Highlights are words of the spoken language; a translation carries its own.
                    hl_t = {cap.norm(h) for h in p.translation_highlight.get(lang, [])}
                    cues += cap.spread_cues(translated, phrase[0].start, phrase[-1].end, hl_t)
            tracks[lang] = CaptionTrack(lang=lang, style=edl.captions.style, word_timed=word_timed,
                                        cues=cap.close_gaps(cues, edl.duration))
        return CaptionResult(tracks=tracks), meta

    def build_user(self, inp: CaptionsInput) -> str:
        lines = [f"[{i}] {' '.join(w.w for w in phrase)}" for i, phrase in enumerate(inp.phrases)]
        return (
            f"# Clip\nSpoken language: {inp.source_language}. Hook: {inp.edl.hook.text.get(inp.source_language) or next(iter(inp.edl.hook.text.values()))}\n"
            f"Keywords the editor wants highlighted: {', '.join(inp.edl.captions.highlight_keywords) or '(none)'}\n\n"
            f"# Translate into\n{', '.join(inp.targets) or '(no translation needed: leave translations empty)'}\n\n"
            "# Phrases (automatic transcript; may contain recognition errors)\n" + "\n".join(lines)
        )

    def check(self, inp: CaptionsInput, out: CaptionEdit) -> None:
        ids = [p.id for p in out.phrases]
        if sorted(ids) != list(range(len(inp.phrases))):
            raise ContractError(f"phrases must contain each id from 0 to {len(inp.phrases) - 1} exactly once; got {ids}.")
        if self.ctx.llm.offline:
            return
        for p in out.phrases:
            if not p.text.strip():
                raise ContractError(f"phrases[{p.id}].text is empty.")
            for lang in inp.targets:
                if not (p.translations.get(lang) or "").strip():
                    raise ContractError(f"phrases[{p.id}].translations is missing language '{lang}'.")

    def offline(self, inp: CaptionsInput) -> dict:
        return {"phrases": [{"id": i, "text": " ".join(w.w for w in phrase),
                             "highlight": [max((w.w for w in phrase), key=len)], "translations": {}}
                            for i, phrase in enumerate(inp.phrases)]}
