"""Rights registry. A video can only enter the pipeline with a declared rights status and
evidence for it. This module registers a local file; downloading from a URL lives in
media/download.py and ends here too, so a downloaded video needs rights like any other."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import VALID_RIGHTS
from .media import ffmpeg
from .schemas import SourceRecord
from .store import Store, new_id


class RightsError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_source(store: Store, path: str | Path, *, rights_status: str, evidence: str,
                    credit: str | None = None, language: str | None = None, project_id: str = "project_default") -> SourceRecord:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise RightsError(f"No existe el archivo: {path}")
    if rights_status not in VALID_RIGHTS:
        raise RightsError(f"rights_status inválido: {rights_status!r}. Valores permitidos: {', '.join(VALID_RIGHTS)}")
    if not evidence or len(evidence.strip()) < 8:
        raise RightsError("Falta la evidencia de derechos (enlace, archivo o descripción de al menos 8 caracteres).")
    sha = file_sha256(path)
    if not store.get_project(project_id):
        raise RightsError("No existe el proyecto.")
    existing = store.find_source_by_hash(sha, project_id)
    if existing:
        return SourceRecord(**existing)
    info = ffmpeg.probe(path)
    rec = SourceRecord(id=new_id("src"), path=str(path), sha256=sha, rights_status=rights_status,  # type: ignore[arg-type]
                       evidence=evidence.strip(), credit=credit, language=language, project_id=project_id,
                       duration=info["duration"], width=info["width"], height=info["height"],
                       fps=info["fps"], has_audio=info["has_audio"])
    store.add_source(rec.model_dump())
    return rec


def rights_ok(source: dict | SourceRecord) -> tuple[bool, str]:
    rec = source if isinstance(source, dict) else source.model_dump()
    if rec.get("rights_status") not in VALID_RIGHTS:
        return False, f"rights_status no válido: {rec.get('rights_status')!r}"
    if not (rec.get("evidence") or "").strip():
        return False, "sin evidencia de derechos"
    return True, f"{rec['rights_status']}: {rec['evidence']}"
