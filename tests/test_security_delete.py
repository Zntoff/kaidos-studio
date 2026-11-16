"""Local session isolation and library removal, without real videos, keys or paid calls."""
from pathlib import Path
import re
import threading
import time

from fastapi.testclient import TestClient

from clipper.store import Store
from clipper.web.app import create_app
from session import authorize
import pytest


def test_session_origin_host_and_secret_redaction(settings, monkeypatch):
    secret = "sk-test-secret-that-must-never-be-exposed"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    store = Store(settings.database_url)
    store.create_project("test", "Provider echoed " + secret)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/settings/ai").status_code == 401
        page = client.get("/")
        assert "HttpOnly" in page.headers["set-cookie"] and "SameSite=strict" in page.headers["set-cookie"]
        csrf = re.search(r'name="kairos-csrf" content="([a-fA-F0-9]+)"', page.text)[1]
        assert csrf not in page.headers["set-cookie"], "CSRF and session credentials must be independent"
        assert client.post("/api/projects", json={"name": "no token"}).status_code == 403
        authorize(client)
        assert client.post("/api/projects", json={"name": "allowed"}).status_code == 200
        assert client.get("/api/settings/ai", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/settings/ai", headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/projects", json={"name": "blocked"}, headers={"X-Kairos-CSRF": "wrong"}).status_code == 403
        assert client.get("/api/config", headers={"Origin": "http://[invalid"}).status_code == 403
        response = client.get("/api/projects")
        assert secret not in response.text and "[REDACTED]" in response.text
        assert response.headers["cache-control"] == "no-store" and response.headers["x-frame-options"] == "DENY"
        assert secret not in client.get("/api/config").text
        assert secret not in client.get("/api/settings/ai").text


def seed(store, settings, project_id):
    managed = settings.data_dir / "uploads" / "managed.mp4"
    managed.parent.mkdir(parents=True, exist_ok=True); managed.write_bytes(b"synthetic")
    external = settings.data_dir.parent / "external-original.mp4"; external.write_bytes(b"keep me")
    for sid, path in [("owned", managed), ("external", external)]:
        store.add_source({"id": sid, "sha256": sid, "project_id": project_id, "path": str(path)})
    job = store.create_job("owned", {}); store.update_job(job, status="done")
    clip = store.upsert_clip(job, 0, {"id": "candidate", "start": 0, "end": 3})
    package = settings.data_dir / "out" / clip; package.mkdir(parents=True); (package / "clip.mp4").write_bytes(b"render")
    store.update_clip(clip, package_dir=str(package))
    resource = {"id": "res_test", "project_id": project_id, "name": "brief.txt", "extension": ".txt", "kind": "document", "size": 4, "description": "", "created_at": __import__('datetime').datetime.now()}
    store.add_resource(resource)
    root = settings.data_dir / "projects" / project_id / "resources"; root.mkdir(parents=True); (root / "res_test.txt").write_text("test")
    return managed, external, job, clip


def test_project_delete_is_scoped_cascades_and_keeps_originals(settings):
    store = Store(settings.database_url)
    a, b = store.create_project("A"), store.create_project("B")
    managed, external, job, clip = seed(store, settings, a["id"])
    store.add_source({"id": "other", "sha256": "other", "project_id": b["id"], "path": "other.mp4"})
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        assert client.delete("/api/library/projects/project_default").status_code == 400
        assert client.delete("/api/library/../nope").status_code == 404
        response = client.delete("/api/library/projects/" + a["id"])
        assert response.status_code == 200, response.text
        assert response.json()["removed"] == {"sources": 2, "jobs": 1, "clips": 1, "resources": 1}
        assert not store.get_project(a["id"]) and store.get_project(b["id"])
        assert store.get_source("other") and not store.get_job(job) and not store.get_clip(clip)
        assert external.read_bytes() == b"keep me" and not managed.exists()
        assert list((settings.data_dir / "trash").glob("*/manifest.json"))
        assert client.delete("/api/library/projects/" + a["id"]).status_code == 404


def test_individual_delete_and_shared_file_protection(settings):
    store = Store(settings.database_url)
    a = store.create_project("A")
    managed, external, job, clip = seed(store, settings, a["id"])
    store.add_source({"id": "shared", "sha256": "same", "project_id": "project_default", "path": str(managed)})
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        assert client.delete("/api/library/resources/res_test").json()["removed"]["resources"] == 1
        assert client.delete("/api/library/clips/" + clip).status_code == 200
        assert store.get_job(job) and store.get_source("owned")
        assert client.delete("/api/library/sources/owned").status_code == 200
        assert managed.exists(), "Another project still references this file"
        assert client.delete("/api/library/sources/external").status_code == 200
        assert external.exists()


def test_deletion_waits_for_active_project_work(settings, monkeypatch):
    from clipper.agents.orchestrator import Orchestrator
    started, release = threading.Event(), threading.Event()
    def work(*args, **kwargs):
        started.set(); release.wait(10)
    monkeypatch.setattr(Orchestrator, "run", work)
    store = Store(settings.database_url); project = store.create_project("Busy")
    seed(store, settings, project["id"])
    try:
        with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
            authorize(client)
            response = client.post("/api/jobs", json={"source_id": "owned", "offline": True})
            assert response.status_code == 200 and started.wait(2)
            assert client.delete("/api/library/projects/" + project["id"]).status_code == 409
            assert client.delete("/api/library/sources/owned").status_code == 409
            assert store.get_project(project["id"]) and store.get_source("owned")
    finally:
        release.set()


def test_failed_file_move_restores_files_and_records(settings, monkeypatch):
    import shutil
    store = Store(settings.database_url); project = store.create_project("Rollback")
    managed, external, job, clip = seed(store, settings, project["id"])
    original_move, calls = shutil.move, []
    def fail_second(source, target):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("Simulated file move failure")
        return original_move(source, target)
    monkeypatch.setattr(shutil, "move", fail_second)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        with pytest.raises(OSError):
            client.delete("/api/library/projects/" + project["id"])
    assert managed.exists() and external.exists() and store.get_clip(clip) and store.get_job(job)
    assert Path(store.get_clip(clip)["package_dir"]).is_dir()


def test_keys_cannot_be_sent_over_remote_plain_http(monkeypatch):
    from clipper import ai_settings
    from clipper.llm import OpenAICompatLLM, LLMError
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("Credential request must not be sent"))
    with pytest.raises(ai_settings.KeyError_, match="HTTPS"):
        ai_settings.list_models("http://remote.example/v1", "private-key", "Remote")
    with pytest.raises(LLMError, match="HTTPS"):
        OpenAICompatLLM(base_url="http://remote.example/v1", api_key="private-key", name="Remote")
    assert ai_settings.credential_transport_error("http://127.0.0.1:11434/v1", "local-key") is None
    assert ai_settings.credential_transport_error("http://localhost:1234/v1", "local-key") is None
    assert ai_settings.credential_transport_error("https://remote.example/v1", "private-key") is None
    assert ai_settings.credential_transport_error("http://remote.example/v1", None) is None


def test_json_reference_download_preserves_original_encoding(settings):
    payload = '{"reference":"original text"}'.encode("utf-16")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        record = client.post("/api/projects/project_default/resources", files={"file": ("reference.json", payload, "application/json")}).json()
        response = client.get(f"/api/projects/project_default/resources/{record['id']}/file?download=true")
        assert response.status_code == 200 and response.content == payload
