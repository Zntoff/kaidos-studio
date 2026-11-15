"""Persistent state. Subagents keep no state of their own: everything a job needs to resume
lives here. Works on SQLite (default) and Postgres (set DATABASE_URL)."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa

metadata = sa.MetaData()
DEFAULT_PROJECT = "project_default"
projects = sa.Table("projects", metadata,
    sa.Column("id", sa.String, primary_key=True), sa.Column("name", sa.String, nullable=False),
    sa.Column("description", sa.String, nullable=False, default=""), sa.Column("created_at", sa.DateTime, nullable=False))
resources = sa.Table("project_resources", metadata,
    sa.Column("id", sa.String, primary_key=True), sa.Column("project_id", sa.String, nullable=False, index=True),
    sa.Column("name", sa.String, nullable=False), sa.Column("kind", sa.String, nullable=False),
    sa.Column("extension", sa.String, nullable=False), sa.Column("size", sa.BigInteger, nullable=False),
    sa.Column("description", sa.String, nullable=False, default=""), sa.Column("created_at", sa.DateTime, nullable=False))

sources = sa.Table(
    "sources", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("sha256", sa.String, index=True),
    sa.Column("record", sa.JSON, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

jobs = sa.Table(
    "jobs", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("source_id", sa.String, nullable=False),
    sa.Column("project_id", sa.String, nullable=False, server_default=DEFAULT_PROJECT, index=True),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("options", sa.JSON, nullable=False),
    sa.Column("summary", sa.JSON),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

clips = sa.Table(
    "clips", metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("job_id", sa.String, index=True, nullable=False),
    sa.Column("project_id", sa.String, nullable=False, server_default=DEFAULT_PROJECT, index=True),
    sa.Column("idx", sa.Integer, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("candidate", sa.JSON),
    sa.Column("edl", sa.JSON),
    sa.Column("review", sa.JSON),
    sa.Column("package_dir", sa.String),
    sa.Column("hook_text", sa.JSON),
    sa.Column("schedule", sa.JSON),
    sa.Column("decided_by", sa.String),
    sa.Column("decided_at", sa.DateTime),
    sa.Column("decision_note", sa.String),
    sa.Column("created_at", sa.DateTime, nullable=False),
    # Unrendered manual edit from the web editor: {"edl", "tracks", "saved_at"}. `edl` above always
    # describes the packaged video; the draft replaces it only when it is rendered.
    sa.Column("draft", sa.JSON),
)

# One row per subagent run: which prompt, which model, what it returned, how many attempts.
steps = sa.Table(
    "steps", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String, index=True, nullable=False),
    sa.Column("clip_id", sa.String),
    sa.Column("agent", sa.String, nullable=False),
    sa.Column("key", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, default=0),
    sa.Column("prompt_version", sa.String),
    sa.Column("model", sa.String),
    sa.Column("usage", sa.JSON),
    sa.Column("output", sa.JSON),
    sa.Column("error", sa.Text),
    sa.Column("seconds", sa.Float),
    sa.Column("finished_at", sa.DateTime),
)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Store:
    def __init__(self, url: str):
        self.engine = sa.create_engine(url, future=True)
        metadata.create_all(self.engine)
        for table in (jobs, clips):
            if "project_id" not in {col["name"] for col in sa.inspect(self.engine).get_columns(table.name)}:
                with self.engine.begin() as c:
                    c.execute(sa.text(f"ALTER TABLE {table.name} ADD COLUMN project_id VARCHAR NOT NULL DEFAULT '{DEFAULT_PROJECT}'"))
        with self.engine.begin() as c:
            if not c.execute(sa.select(projects.c.id).where(projects.c.id == DEFAULT_PROJECT)).first():
                c.execute(projects.insert().values(id=DEFAULT_PROJECT, name="General", description="Biblioteca inicial", created_at=now()))
        # create_all does not alter existing tables: add columns introduced after the first release.
        if "draft" not in {c["name"] for c in sa.inspect(self.engine).get_columns("clips")}:
            try:
                with self.engine.begin() as c:
                    c.execute(sa.text("ALTER TABLE clips ADD COLUMN draft JSON"))
            except sa.exc.DBAPIError:  # another process added it first
                pass

    # ---- projects ----
    def list_projects(self) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(row) for row in c.execute(sa.select(projects).order_by(projects.c.created_at)).mappings()]

    def get_project(self, project_id: str) -> dict | None:
        return next((p for p in self.list_projects() if p["id"] == project_id), None)

    def create_project(self, name: str, description: str = "") -> dict:
        record = {"id": new_id("project"), "name": name, "description": description, "created_at": now()}
        with self.engine.begin() as c:
            c.execute(projects.insert().values(**record))
        return record

    def update_project(self, project_id: str, name: str, description: str) -> None:
        with self.engine.begin() as c:
            c.execute(projects.update().where(projects.c.id == project_id).values(name=name, description=description))

    def move_source(self, source_id: str, project_id: str) -> None:
        if not self.get_project(project_id):
            raise ValueError("No existe el proyecto.")
        with self.engine.begin() as c:
            record = c.execute(sa.select(sources.c.record).where(sources.c.id == source_id)).scalar_one()
            record = {**record, "project_id": project_id}
            c.execute(sources.update().where(sources.c.id == source_id).values(record=record))
            job_ids = sa.select(jobs.c.id).where(jobs.c.source_id == source_id)
            c.execute(clips.update().where(clips.c.job_id.in_(job_ids)).values(project_id=project_id))
            c.execute(jobs.update().where(jobs.c.source_id == source_id).values(project_id=project_id))

    # ---- sources ----
    def list_resources(self, project_id: str) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(sa.select(resources).where(resources.c.project_id == project_id).order_by(resources.c.created_at.desc())).mappings()]

    def add_resource(self, record: dict) -> None:
        with self.engine.begin() as c:
            c.execute(resources.insert().values(**record))

    def get_resource(self, project_id: str, resource_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(sa.select(resources).where(resources.c.project_id == project_id, resources.c.id == resource_id)).mappings().first()
            return dict(row) if row else None

    def add_source(self, record: dict) -> None:
        with self.engine.begin() as c:
            c.execute(sources.insert().values(id=record["id"], sha256=record["sha256"], record=record, created_at=now()))

    def get_source(self, source_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(sa.select(sources.c.record).where(sources.c.id == source_id)).first()
        return {"project_id": DEFAULT_PROJECT, **row[0]} if row else None

    def find_source_by_hash(self, sha256: str, project_id: str = DEFAULT_PROJECT) -> dict | None:
        with self.engine.connect() as c:
            rows = c.execute(sa.select(sources.c.record).where(sources.c.sha256 == sha256)).all()
        return next(({"project_id": DEFAULT_PROJECT, **r[0]} for r in rows if r[0].get("project_id", DEFAULT_PROJECT) == project_id), None)

    def list_sources(self, project_id: str | None = None) -> list[dict]:
        with self.engine.connect() as c:
            return [{"project_id": DEFAULT_PROJECT, **r[0]} for r in c.execute(sa.select(sources.c.record).order_by(sources.c.created_at))
                    if project_id is None or r[0].get("project_id", DEFAULT_PROJECT) == project_id]

    # ---- jobs ----
    def create_job(self, source_id: str, options: dict) -> str:
        job_id = new_id("job")
        project_id = (self.get_source(source_id) or {}).get("project_id", DEFAULT_PROJECT)
        with self.engine.begin() as c:
            c.execute(jobs.insert().values(id=job_id, source_id=source_id, project_id=project_id, status="running", options=options,
                                           created_at=now(), updated_at=now()))
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(sa.select(jobs).where(jobs.c.id == job_id)).mappings().first()
        return dict(row) if row else None

    def update_job(self, job_id: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(jobs.update().where(jobs.c.id == job_id).values(updated_at=now(), **values))

    def list_jobs(self, project_id: str | None = None) -> list[dict]:
        with self.engine.connect() as c:
            query = sa.select(jobs).order_by(jobs.c.created_at)
            if project_id is not None:
                query = query.where(jobs.c.project_id == project_id)
            return [dict(r) for r in c.execute(query).mappings()]

    # ---- clips ----
    def upsert_clip(self, job_id: str, idx: int, candidate: dict) -> str:
        clip_id = f"{job_id.removeprefix('job_')}_c{idx:02d}"
        with self.engine.begin() as c:
            if not c.execute(sa.select(clips.c.id).where(clips.c.id == clip_id)).first():
                project_id = c.execute(sa.select(jobs.c.project_id).where(jobs.c.id == job_id)).scalar_one()
                c.execute(clips.insert().values(id=clip_id, job_id=job_id, project_id=project_id, idx=idx, status="candidate",
                                                candidate=candidate, created_at=now()))
        return clip_id

    def get_clip(self, clip_id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(sa.select(clips).where(clips.c.id == clip_id)).mappings().first()
        return dict(row) if row else None

    def update_clip(self, clip_id: str, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(clips.update().where(clips.c.id == clip_id).values(**values))

    def list_clips(self, job_id: str | None = None, status: list[str] | None = None, project_id: str | None = None) -> list[dict]:
        q = sa.select(clips).order_by(clips.c.created_at, clips.c.idx)
        if job_id:
            q = q.where(clips.c.job_id == job_id)
        if status:
            q = q.where(clips.c.status.in_(status))
        if project_id:
            q = q.where(clips.c.project_id == project_id)
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def recent_hooks(self, exclude_clip: str, limit: int = 20) -> list[dict]:
        """Hooks of the latest clips that got as far as a package, for the variety guard."""
        project_id = (self.get_clip(exclude_clip) or {}).get("project_id", DEFAULT_PROJECT)
        q = (sa.select(clips.c.id, clips.c.hook_text, clips.c.edl)
             .where(clips.c.hook_text.is_not(None), clips.c.id != exclude_clip,
                    clips.c.project_id == project_id,
                    clips.c.status.in_(["pending_approval", "needs_human", "approved"]))
             .order_by(clips.c.created_at.desc(), clips.c.idx.desc()).limit(limit))
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(q).mappings()]

    def scheduled_slots(self) -> list[dict]:
        q = sa.select(clips.c.schedule).where(clips.c.schedule.is_not(None))
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(q)]

    # ---- steps ----
    def get_done_step(self, job_id: str, clip_id: str | None, agent: str, key: str) -> dict | None:
        q = (sa.select(steps).where(steps.c.job_id == job_id, steps.c.agent == agent, steps.c.key == key,
                                    steps.c.status == "done").order_by(steps.c.id.desc()))
        q = q.where(steps.c.clip_id == clip_id) if clip_id else q.where(steps.c.clip_id.is_(None))
        with self.engine.connect() as c:
            row = c.execute(q).mappings().first()
        return dict(row) if row else None

    def record_step(self, **values: Any) -> None:
        with self.engine.begin() as c:
            c.execute(steps.insert().values(finished_at=now(), **values))

    def list_steps(self, job_id: str) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(sa.select(steps).where(steps.c.job_id == job_id).order_by(steps.c.id)).mappings()]
