"""Remove library records atomically; quarantine only files owned by Kairos, never arbitrary originals."""
import json
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException
from clipper import store as db


def mount(app, settings, store, runs):
    @app.delete("/api/library/{kind}/{item_id}")
    def remove(kind: str, item_id: str):
        if kind not in ("projects", "sources", "clips", "resources"):
            raise HTTPException(404, "Unknown library item")
        project = store.get_project(item_id) if kind == "projects" else None
        sources = store.list_sources()
        jobs = store.list_jobs()
        clips = store.list_clips()
        resources = [r for p in store.list_projects() for r in store.list_resources(p["id"])]
        items = {"projects": store.list_projects(), "sources": sources, "clips": clips, "resources": resources}
        item = next((x for x in items[kind] if x["id"] == item_id), None)
        if not item:
            raise HTTPException(404, "Item not found")
        if kind == "projects" and item_id == db.DEFAULT_PROJECT:
            raise HTTPException(400, "The default project cannot be deleted. You can delete its content.")
        pid = item_id if project else item.get("project_id", db.DEFAULT_PROJECT)
        if any(r["status"] in ("queued", "running") and (r.get("project_id") is None or r["project_id"] == pid) for r in runs.items.values()):
            raise HTTPException(409, "Wait for the project's active jobs to finish before deleting.")
        selected_sources = [s for s in sources if s["project_id"] == pid] if project else [item] if kind == "sources" else []
        source_ids = {s["id"] for s in selected_sources}
        selected_jobs = [j for j in jobs if j["source_id"] in source_ids or project and j["project_id"] == pid]
        job_ids = {j["id"] for j in selected_jobs}
        selected_clips = [c for c in clips if c["job_id"] in job_ids or project and c["project_id"] == pid or kind == "clips" and c["id"] == item_id]
        selected_resources = [r for r in resources if project and r["project_id"] == pid or kind == "resources" and r["id"] == item_id]
        clip_ids = {c["id"] for c in selected_clips}
        # The manifest preserves the deleted records and the old file locations for manual recovery.
        trash = settings.data_dir / "trash" / uuid.uuid4().hex
        trash.mkdir(parents=True, mode=0o700)
        paths = [Path(c["package_dir"]) for c in selected_clips if c.get("package_dir")]
        paths += [settings.job_dir(j["id"]) for j in selected_jobs]
        paths += [Path(s["path"]) for s in selected_sources]
        paths += [settings.data_dir / "projects" / r["project_id"] / "resources" / (r["id"] + r["extension"]) for r in selected_resources]
        roots = [settings.data_dir / name for name in ("out", "jobs", "uploads", "downloads", "projects", "cache")]
        moved = []
        manifest = {"project": project, "sources": selected_sources, "jobs": selected_jobs, "clips": selected_clips, "resources": selected_resources}
        try:
            for path in dict.fromkeys(paths):
                # Resolve symlinks before checking ownership, and never remove a managed root itself.
                resolved = path.resolve()
                if not path.exists() or path.is_symlink() or not any(resolved != root.resolve() and resolved.is_relative_to(root.resolve()) for root in roots):
                    continue
                # Keep files referenced by surviving records.
                if any(Path(s["path"]).resolve() == resolved for s in sources if s["id"] not in source_ids):
                    continue
                if any(c.get("package_dir") and Path(c["package_dir"]).resolve() == resolved for c in clips if c["id"] not in clip_ids):
                    continue
                target = trash / str(len(moved))
                shutil.move(str(path), str(target)); moved.append((str(path), str(target)))
            manifest["files"] = moved
            (trash / "manifest.json").write_text(json.dumps(manifest, default=str), encoding="utf-8")
            (trash / "manifest.json").chmod(0o600)
            with store.engine.begin() as connection:
                saved_steps = [dict(r) for r in connection.execute(db.sa.select(db.steps).where(db.sa.or_(db.steps.c.job_id.in_(job_ids), db.steps.c.clip_id.in_(clip_ids)))).mappings()]
                manifest["steps"] = saved_steps
                (trash / "manifest.json").write_text(json.dumps(manifest, default=str), encoding="utf-8")
                connection.execute(db.steps.delete().where(db.sa.or_(db.steps.c.job_id.in_(job_ids), db.steps.c.clip_id.in_(clip_ids))))
                connection.execute(db.clips.delete().where(db.clips.c.id.in_(clip_ids)))
                connection.execute(db.jobs.delete().where(db.jobs.c.id.in_(job_ids)))
                connection.execute(db.sources.delete().where(db.sources.c.id.in_(source_ids)))
                connection.execute(db.resources.delete().where(db.resources.c.id.in_({r["id"] for r in selected_resources})))
                if project:
                    connection.execute(db.projects.delete().where(db.projects.c.id == item_id))
        except Exception:
            for original, target in reversed(moved):
                if Path(target).exists():
                    Path(original).parent.mkdir(parents=True, exist_ok=True); shutil.move(target, original)
            raise
        return {"ok": True, "removed": {"sources": len(source_ids), "jobs": len(job_ids), "clips": len(clip_ids), "resources": len(selected_resources)}, "recoverable": True}
