"""End-to-end runs on a synthetic video. 'Claude' is a scripted stand-in here: these tests
prove the plumbing (contracts, retries, parallel steps, rendering, guards, packaging,
resume), not the quality of real editorial decisions."""
import json
import subprocess
from pathlib import Path

import pytest

from clipper.agents import output
from clipper.agents.orchestrator import Orchestrator
from clipper.media import audio, ffmpeg, render
from clipper.rights import register_source
from clipper.schemas import (EDL, CaptionPlan, EdlAudio, EdlCommentary, EdlHook, EdlNote, EdlRisk, EdlSource)
from conftest import REVIEW_PASS, editing_answer, read_json


def run(make_ctx, llm, source, demo, **kw):
    orch = Orchestrator(make_ctx(llm))
    return orch, orch.run(source.id, transcript=str(demo[1]), **kw)


def test_full_run_two_languages(make_ctx, scripted, settings, store, source, demo):
    settings.languages = ["en", "es"]
    llm = scripted(("en", "es"))
    _, summary = run(make_ctx, llm, source, demo, max_clips=1)
    assert summary["clips"] == {"pending_approval": 1}
    pkg = Path(summary["packages"][0]["dir"])
    manifest = read_json(pkg / "package.json")
    assert manifest["languages"] == ["en", "es"] and manifest["generated_offline"] is False

    for lang in ("en", "es"):
        info = ffmpeg.probe(pkg / lang / "clip.mp4")
        assert (info["width"], info["height"]) == (1080, 1920) and info["has_audio"]
        lufs = audio.measure(pkg / lang / "clip.mp4")["input_i"]
        assert abs(lufs - settings.target_lufs) <= 1.0
    assert "frase traducida" in (pkg / "es" / "captions.srt").read_text(encoding="utf-8")
    assert "frase traducida" not in (pkg / "en" / "captions.srt").read_text(encoding="utf-8")
    es_track = store.list_steps(summary["job_id"])
    es_cues = next(s["output"] for s in es_track if s["agent"] == "captions")["tracks"]["es"]["cues"]
    assert {w["w"] for c in es_cues for w in c["words"] if w["hl"]} == {"traducida"}  # highlights follow the translation
    meta = read_json(pkg / "es" / "metadata.json")
    assert meta["youtube"]["title"] == "Cruzó el puente entero" and meta["youtube"]["hashtags"] == ["#gaming", "#stunt"]

    review = read_json(pkg / "review.json")
    assert review["status"] == "approved" and all(c["status"] == "pass" for c in review["checks"])

    # Audit trail: every subagent run records prompt version, model and attempts.
    steps = {s["agent"]: s for s in store.list_steps(summary["job_id"])}
    assert set(steps) == {"analysis", "editing", "captions", "metadata", "render", "reviewer", "output"}
    for agent in ("analysis", "editing", "captions", "metadata", "reviewer"):
        assert steps[agent]["prompt_version"].startswith(f"{agent}@v") and steps[agent]["attempts"] == 1
    assert steps["reviewer"]["model"].endswith(settings.model_superior)
    # The reviewer is shown rendered frames; the editor is shown source frames.
    by_agent = {c["agent"]: c for c in llm.calls}
    assert by_agent["reviewer"]["images"] == 4 and by_agent["editing"]["images"] == 6
    assert "Setup and payoff" not in by_agent["reviewer"]["user"]  # no access to upstream reasoning

    # Human approval: recorded with a name and a proposed slot per language.
    clip_id = summary["packages"][0]["clip_id"]
    clip = output.decide(settings, store, clip_id, approve=True, by="reviewer")
    assert clip["status"] == "approved" and clip["decided_by"] == "reviewer" and set(clip["schedule"]) == {"en", "es"}
    assert read_json(pkg / "package.json")["decided_by"] == "reviewer"
    with pytest.raises(ValueError):
        output.decide(settings, store, clip_id, approve=True, by="reviewer")


def test_reviewer_rejection_triggers_one_re_edit(make_ctx, scripted, source, demo, store):
    weak = {"spoiler": {"verdict": "pass", "reason": "ok"},
            "value_add": {"verdict": "fail", "reason": "The note is filler; explain why the jump worked."}, "policy_notes": ""}
    llm = scripted(editing=[editing_answer(("en",)), editing_answer(("en",), hook="Why this ramp sends cars flying")],
                   reviewer=[weak, REVIEW_PASS])
    _, summary = run(make_ctx, llm, source, demo, max_clips=1)
    assert summary["clips"] == {"pending_approval": 1}
    keys = [s["key"] for s in store.list_steps(summary["job_id"]) if s["agent"] == "editing"]
    assert keys == ["edit:r0", "edit:r1"]
    second_edit = [c for c in llm.calls if c["agent"] == "editing"][1]["user"]
    assert "explain why the jump worked" in second_edit
    assert read_json(Path(summary["packages"][0]["dir"]) / "edl.json")["revision"] == 1


def test_spoiler_verdict_blocks_output(make_ctx, scripted, source, demo):
    spoiler = {"spoiler": {"verdict": "fail", "reason": "Shows the final cutscene."},
               "value_add": {"verdict": "pass", "reason": "ok"}, "policy_notes": ""}
    _, summary = run(make_ctx, scripted(reviewer=[spoiler]), source, demo, max_clips=1)
    assert summary["clips"] == {"rejected": 1} and summary["packages"][0]["dir"] is None


def test_spoiler_keyword_and_unsure_go_to_a_person(make_ctx, scripted, source, demo):
    llm = scripted(editing=[editing_answer(("en",), hook="The ending nobody expected")])
    _, summary = run(make_ctx, llm, source, demo, max_clips=1)
    assert summary["clips"] == {"needs_human": 1}
    review = read_json(Path(summary["packages"][0]["dir"]) / "review.json")
    assert "ending" in review["feedback"]


def test_invalid_edit_is_retried_then_escalated(make_ctx, scripted, source, demo, store):
    def no_commentary(user):
        d = editing_answer(("en",))(user)
        d["commentary"]["notes"] = []
        return d

    _, summary = run(make_ctx, scripted(editing=[no_commentary]), source, demo, max_clips=1)
    assert summary["clips"] == {"agent_failed": 1}
    failed = [s for s in store.list_steps(summary["job_id"]) if s["agent"] == "editing"][0]
    assert failed["status"] == "failed" and failed["attempts"] == 3


def test_variety_guard_blocks_a_repeated_hook(make_ctx, scripted, settings, source, demo):
    settings.max_clips = 1
    _, first = run(make_ctx, scripted(), source, demo)
    assert first["clips"] == {"pending_approval": 1}
    # A second job proposes the same hook: the Editing contract refuses it three times and escalates.
    _, second = run(make_ctx, scripted(), source, demo)
    assert second["clips"] == {"agent_failed": 1} and "repeats a recent hook" in second["packages"][0]["note"]


def test_resume_does_not_repeat_finished_steps(make_ctx, scripted, source, demo, store):
    orch, summary = run(make_ctx, scripted(), source, demo, max_clips=1)
    before = len(store.list_steps(summary["job_id"]))
    llm = scripted()
    again = Orchestrator(make_ctx(llm)).run(job_id=summary["job_id"])
    assert len(store.list_steps(summary["job_id"])) == before and llm.calls == []
    assert again["clips"] == summary["clips"]


def test_review_stops_after_analysis_then_generates_only_the_picked_moments(make_ctx, scripted, settings, store, source, demo):
    settings.apply_options({"analysis_model": "fast"})
    llm = scripted()
    summary = Orchestrator(make_ctx(llm)).run(source.id, transcript=str(demo[1]), review=True)
    job_id = summary["job_id"]
    assert store.get_job(job_id)["status"] == "awaiting_selection" and store.list_clips(job_id) == []
    assert [c["agent"] for c in llm.calls] == ["analysis"] and llm.calls[0]["model"] == settings.model_fast
    cands = store.get_done_step(job_id, None, "analysis", "analysis")["output"]["candidates"]
    assert cands

    # The person picks one moment, a model, a layout and a caption style: nothing else is generated.
    store.update_job(job_id, options={**store.get_job(job_id)["options"], "selection": [cands[0]["id"]], "model": "fast"})
    settings.apply_options({"model": "fast", "layout": "center_crop", "caption_style": "clean"})
    llm2 = scripted()
    done = Orchestrator(make_ctx(llm2)).run(job_id=job_id)
    assert store.get_job(job_id)["status"] == "done" and len(store.list_clips(job_id)) == 1
    assert {c["agent"] for c in llm2.calls} == {"editing", "captions", "metadata", "reviewer"}
    assert all(c["model"] == settings.model_fast for c in llm2.calls)          # nothing went to Opus
    edl = store.list_clips(job_id)[0]["edl"]
    assert edl["layout"] == "center_crop" and edl["captions"]["style"] == "clean"  # the owner's choice beats the model's
    assert "owner fixed layout" in next(c for c in llm2.calls if c["agent"] == "editing")["user"]
    assert done["clips"] and settings.model_for("superior", "reviewer") == settings.model_fast


def test_options_are_validated_and_default_to_claude_deciding(settings):
    assert settings.model_for("superior", "reviewer") == settings.model_superior and settings.layout_choice == "auto"
    for bad in ({"model": "gpt"}, {"analysis_model": "huge"}, {"layout": "wide"}, {"caption_style": "sparkle"}):
        with pytest.raises(ValueError):
            settings.apply_options(bad)


def test_unregistered_or_missing_source_is_refused(make_ctx, scripted):
    with pytest.raises(ValueError, match="registro de derechos"):
        Orchestrator(make_ctx(scripted())).run("src_does_not_exist")


def test_offline_run_never_comes_out_approved(make_ctx, source, demo):
    _, summary = run(make_ctx, None, source, demo, max_clips=1)
    assert summary["clips"] == {"needs_human": 1}
    assert read_json(Path(summary["packages"][0]["dir"]) / "package.json")["generated_offline"] is True


def test_video_without_audio_track(make_ctx, settings, store, tmp_path):
    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-t", "30", "-i", "testsrc2=s=640x360:r=30",
                    "-c:v", "libx264", "-preset", "ultrafast", str(silent)], check=True)
    src = register_source(store, silent, rights_status="own", evidence="patrón de prueba sin audio")
    summary = Orchestrator(make_ctx()).run(src.id, max_clips=1)
    assert summary["clips"] == {"needs_human": 1}
    pkg = Path(summary["packages"][0]["dir"])
    assert ffmpeg.probe(pkg / "en" / "clip.mp4")["has_audio"] and (pkg / "en" / "captions.srt").read_text() == ""


def test_music_is_ducked_under_voice_and_center_crop_renders(settings, source, tmp_path):
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-t", "4", "-i", "sine=f=220:r=48000",
                    str(lib_dir / "bed.wav")], check=True)
    (lib_dir / "library.json").write_text(json.dumps([
        {"id": "bed_01", "file": "bed.wav", "kind": "music", "description": "tone", "duration": 4, "gain": 0.3, "license": "generado para la prueba"},
        {"id": "no_license", "file": "bed.wav", "kind": "music", "description": "tone", "duration": 4}]))
    settings.sfx_dir = lib_dir
    library = audio.load_library(lib_dir)
    assert set(library) == {"bed_01"}  # entries without a licence are ignored

    edl = EDL(clip_id="t", source=EdlSource(id=source.id, start=5.0, end=17.0), source_language="en", languages=["en"],
              layout="center_crop", crop_x=0.5, hook=EdlHook(text={"en": "Center crop test"}, duration=1.5),
              commentary=EdlCommentary(mode="onscreen", notes=[EdlNote(t=3.0, duration=3.0, text={"en": "A note"})]),
              captions=CaptionPlan(style="clean"), audio=EdlAudio(normalize_lufs=-14, music_id="bed_01", duck_music=True),
              risk=EdlRisk(spoiler=False, rights_ok=True))
    _, graph, _ = audio.mix_graph(edl, library, lib_dir, has_audio=True)
    assert "sidechaincompress=threshold=0.02:ratio=8:attack=100:release=800" in graph
    rep = render.render_clip(edl, source, None, "en", tmp_path / "out", settings)
    assert (rep.width, rep.height) == (1080, 1920) and abs(rep.duration - 12.0) < 0.2 and abs(rep.lufs + 14) <= 1.0
