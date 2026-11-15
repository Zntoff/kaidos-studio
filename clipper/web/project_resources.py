"""Project-owned supporting files. Files are stored, previewed or downloaded, never executed."""
from pathlib import Path
import re
import uuid
import mimetypes

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from clipper.store import now

LIMIT = 100 * 1024 * 1024
KINDS = {**dict.fromkeys((".png", ".jpg", ".jpeg", ".webp", ".gif"), "image"),
         **dict.fromkeys((".wav", ".mp3", ".m4a", ".ogg", ".flac"), "audio"),
         **dict.fromkeys((".pdf", ".txt", ".md", ".json"), "document")}


def mount(app, settings, store, require_project):
    def directory(project_id):
        require_project(project_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise HTTPException(400, "Identificador de proyecto no válido.")
        return settings.data_dir / "projects" / project_id / "resources"

    @app.get("/api/projects/{project_id}/resources")
    def list_resources(project_id: str):
        directory(project_id)
        return store.list_resources(project_id)

    @app.post("/api/projects/{project_id}/resources")
    def upload_resource(project_id: str, file: UploadFile = File(...), description: str = Form("")):
        root = directory(project_id)
        name = re.sub(r"[\x00-\x1f\x7f]", "", (file.filename or "archivo").replace("\\", "/").split("/")[-1])[:180]
        extension = Path(name).suffix.lower()
        if extension not in KINDS:
            raise HTTPException(400, "Usa una imagen, audio, PDF, TXT, Markdown o JSON.")
        if len(description) > 600:
            raise HTTPException(400, "La descripción admite hasta 600 caracteres.")
        if file.size is not None and file.size > LIMIT:
            raise HTTPException(400, "El archivo supera 100 MB.")
        record = dict(id="res_" + uuid.uuid4().hex, project_id=project_id, name=name, extension=extension,
                      kind=KINDS[extension], size=0, description=description.strip(), created_at=now())
        root.mkdir(parents=True, exist_ok=True)
        path = root / (record["id"] + extension)
        try:
            with path.open("xb") as stream:
                while block := file.file.read(1024 * 1024):
                    record["size"] += len(block)
                    if record["size"] > LIMIT:
                        raise HTTPException(400, "El archivo supera 100 MB.")
                    stream.write(block)
            if record["size"] == 0:
                raise HTTPException(400, "El archivo está vacío.")
            store.add_resource(record)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return record

    @app.get("/api/projects/{project_id}/resources/{resource_id}/file")
    def resource_file(project_id: str, resource_id: str, download: bool = False):
        root = directory(project_id)
        record = store.get_resource(project_id, resource_id)
        if not record:
            raise HTTPException(404, "No existe este recurso en el proyecto.")
        path = root / (record["id"] + record["extension"])
        if not path.is_file():
            raise HTTPException(404, "No se encuentra el archivo del recurso.")
        return FileResponse(path, filename=record["name"], media_type=mimetypes.guess_type(record["name"])[0] or "application/octet-stream",
                            content_disposition_type="attachment" if download or record["kind"] == "document" else "inline",
                            headers={"X-Content-Type-Options": "nosniff"})
