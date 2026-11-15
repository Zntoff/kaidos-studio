"""Output stage: builds the export package, keeps the human approval queue and proposes
publishing slots. Deterministic on purpose: nothing here needs a model's judgement.

Publishing through the platforms' APIs is not wired yet (it needs each platform's app audit);
the package is what you upload by hand in the meantime."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from ..config import Settings
from ..schemas import EDL, CaptionResult, MetadataSet, PackageInfo, RenderResult, ReviewVerdict, SourceRecord
from ..store import Store, now

QUEUE_STATES = ["pending_approval", "needs_human"]


def build_package(s: Settings, store: Store, job_id: str, clip_id: str, edl: EDL, source: SourceRecord,
                  captions: CaptionResult, metadata: MetadataSet, renders: RenderResult, review: ReviewVerdict,
                  offline: bool) -> PackageInfo:
    if review.status == "rejected":
        raise ValueError("Un clip rechazado por el Revisor no pasa a Output.")
    status = "pending_approval" if review.status == "approved" else "needs_human"
    out = s.data_dir / "out" / job_id / clip_id
    if out.exists():
        shutil.rmtree(out)
    files: dict[str, dict[str, str]] = {}
    for lang, rep in renders.renders.items():
        d = out / lang
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rep.path, d / "clip.mp4")
        shutil.copy2(rep.srt_path, d / "captions.srt")
        meta = metadata.per_language[lang].model_dump()
        (d / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        files[lang] = {"video": str(d / "clip.mp4"), "srt": str(d / "captions.srt"), "metadata": str(d / "metadata.json")}
    (out / "edl.json").write_text(edl.model_dump_json(indent=2), encoding="utf-8")
    (out / "review.json").write_text(review.model_dump_json(indent=2), encoding="utf-8")
    manifest = {
        "clip_id": clip_id, "job_id": job_id, "status": status, "generated_offline": offline,
        "source": {"id": source.id, "rights_status": source.rights_status, "evidence": source.evidence, "credit": source.credit},
        "duration": round(edl.duration, 2), "languages": list(renders.renders), "files": files,
        "review_status": review.status, "review_feedback": review.feedback,
    }
    (out / "package.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    store.update_clip(clip_id, status=status, package_dir=str(out), hook_text=edl.hook.text)
    return PackageInfo(clip_id=clip_id, status=status, dir=str(out), files=files)


def next_slots(s: Settings, store: Store, languages: list[str], after: dt.datetime | None = None) -> dict[str, str]:
    """Next free publishing slot per language channel (local time), one clip per slot."""
    after = after or dt.datetime.now()
    taken: dict[str, set[str]] = {}
    for sched in store.scheduled_slots():
        for lang, iso in (sched or {}).items():
            taken.setdefault(lang, set()).add(iso)
    hours = sorted(dt.time.fromisoformat(h) for h in s.publish_slots)
    out = {}
    for lang in languages:
        day = after.date()
        while lang not in out:
            for h in hours:
                slot = dt.datetime.combine(day, h)
                if slot > after + dt.timedelta(hours=1) and slot.isoformat() not in taken.get(lang, set()):
                    out[lang] = slot.isoformat()
                    break
            day += dt.timedelta(days=1)
    return out


def decide(s: Settings, store: Store, clip_id: str, *, approve: bool, by: str, note: str = "") -> dict:
    """A person approves or rejects a packaged clip. Approval records who and proposes a slot."""
    clip = store.get_clip(clip_id)
    if clip is None:
        raise ValueError(f"No existe el clip {clip_id}")
    if clip["status"] not in QUEUE_STATES:
        raise ValueError(f"El clip {clip_id} está en estado '{clip['status']}', no en la cola de aprobación.")
    if not by.strip():
        raise ValueError("Indica quién decide (--by).")
    values = {"decided_by": by.strip(), "decided_at": now(), "decision_note": note}
    if approve:
        values |= {"status": "approved", "schedule": next_slots(s, store, clip["edl"]["languages"])}
    else:
        values |= {"status": "rejected_by_human"}
    store.update_clip(clip_id, **values)
    pkg = Path(clip["package_dir"]) / "package.json"
    if pkg.exists():
        manifest = json.loads(pkg.read_text(encoding="utf-8"))
        manifest |= {"status": values["status"], "decided_by": values["decided_by"],
                     "decided_at": values["decided_at"].isoformat(), "decision_note": note,
                     "schedule": values.get("schedule")}
        pkg.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return store.get_clip(clip_id)
