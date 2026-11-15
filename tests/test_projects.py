"""Project persistence, migration and API boundaries without an AI or speech model."""
import sqlalchemy as sa
from fastapi.testclient import TestClient

from session import authorize
from clipper.store import Store, DEFAULT_PROJECT
from clipper.web.app import create_app


def seed(store):
    store.add_source({"id": "src_project", "sha256": "abc", "path": "fixture.mp4"})
    job = store.create_job("src_project", {})
    store.update_job(job, status="done")
    clip = store.upsert_clip(job, 0, {"start": 0, "end": 20})
    return job, clip


def test_projects_inherit_move_and_survive_restart(settings):
    store = Store(settings.database_url)
    job, clip = seed(store)
    project = store.create_project("Canal A", "Videos del canal")
    assert store.get_clip(clip)["project_id"] == DEFAULT_PROJECT
    store.move_source("src_project", project["id"])
    again = Store(settings.database_url)
    assert again.list_sources(DEFAULT_PROJECT) == []
    assert again.get_job(job)["project_id"] == project["id"]
    assert again.get_clip(clip)["project_id"] == project["id"]
    assert len(again.list_clips(project_id=project["id"])) == 1
    assert again.find_source_by_hash("abc") is None
    assert again.find_source_by_hash("abc", project["id"])["id"] == "src_project"


def test_existing_database_gets_general_project(settings):
    store = Store(settings.database_url)
    job, clip = seed(store)
    with store.engine.begin() as c:
        for name in ("jobs", "clips"):
            c.execute(sa.text(f"DROP INDEX ix_{name}_project_id"))
            c.execute(sa.text(f"ALTER TABLE {name} DROP COLUMN project_id"))
        c.execute(sa.text("DROP TABLE projects"))
    store.engine.dispose()
    migrated = Store(settings.database_url)
    assert migrated.get_project(DEFAULT_PROJECT)["name"] == "General"
    assert migrated.get_job(job)["project_id"] == DEFAULT_PROJECT
    assert migrated.get_clip(clip)["project_id"] == DEFAULT_PROJECT
    assert migrated.get_source("src_project")["project_id"] == DEFAULT_PROJECT


def test_project_api_validation_scope_and_move(settings, monkeypatch):
    monkeypatch.setattr("clipper.media.hardware.devices", lambda: [])
    store = Store(settings.database_url)
    job, clip = seed(store)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        assert client.post("/api/projects", json={"name": "  "}).status_code == 400
        assert client.post("/api/projects", json={"name": "x" * 81}).status_code == 400
        project = client.post("/api/projects", json={"name": "Mi proyecto"}).json()
        assert client.get("/api/projects").json()[0]["source_count"] == 1
        for path in ("sources", "jobs", "clips", "queue"):
            assert client.get(f"/api/{path}?project_id={project['id']}").json() == []
        assert client.put("/api/sources/src_project/project", json={"project_id": "missing"}).status_code == 404
        assert client.put("/api/sources/src_project/project", json={"project_id": project["id"]}).status_code == 200
        assert len(client.get(f"/api/clips?project_id={project['id']}").json()) == 1
        assert client.get(f"/api/jobs?project_id={DEFAULT_PROJECT}").json() == []
        assert client.put(f"/api/projects/{project['id']}", json={"name": "Renombrado", "description": "Canal"}).status_code == 200
        assert client.get("/api/projects").json()[1]["name"] == "Renombrado"


def test_container_render_settings_persist_and_validate(settings, monkeypatch):
    monkeypatch.setattr("clipper.media.hardware.devices", lambda: [])
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        assert client.put("/api/settings", json={"device": "h264_nvenc"}).status_code == 400
        assert client.put("/api/settings", json={"device": "cpu", "quality": 90}).status_code == 400
        assert client.put("/api/settings", json={"device": "cpu", "fps": 60, "quality": 24}).status_code == 200
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        render = client.get("/api/config").json()["render"]
        assert render["device"] == "cpu" and render["resolved_encoder"] == "libx264"
        assert render["fps"] == 60 and render["quality"] == 24


def test_resources_belong_only_to_their_project(settings, monkeypatch):
    monkeypatch.setattr("clipper.media.hardware.devices", lambda: [])
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        a = client.post('/api/projects', json={'name':'Canal A'}).json()['id']
        b = client.post('/api/projects', json={'name':'Canal B'}).json()['id']
        response = client.post(f'/api/projects/{a}/resources', files={'file':('brief.txt', b'Only project A', 'text/plain')}, data={'description':'Idea del canal'})
        assert response.status_code == 200
        resource = response.json()
        assert resource['project_id'] == a and resource['size'] == 14
        assert client.get(f'/api/projects/{b}/resources').json() == []
        assert client.get(f'/api/projects/{b}/resources/{resource["id"]}/file').status_code == 404
        download = client.get(f'/api/projects/{a}/resources/{resource["id"]}/file')
        assert download.content == b'Only project A'
        assert 'attachment' in download.headers['content-disposition']
        assert download.headers['x-content-type-options'] == 'nosniff'
        assert client.post(f'/api/projects/{a}/resources',files={'file':('page.html', b'<script>bad</script>')}).status_code == 400
        assert client.post(f'/api/projects/{a}/resources',files={'file':('empty.txt', b'')}).status_code == 400
        assert client.post('/api/projects/missing/resources',files={'file':('brief.txt', b'X')}).status_code == 404
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        authorize(client)
        assert client.get(f'/api/projects/{a}/resources').json()[0]['id'] == resource['id']


def test_repeated_hooks_do_not_cross_project_boundaries(settings):
    store = Store(settings.database_url)
    job, clip = seed(store)
    store.update_clip(clip, hook_text={'en':'Private channel A'}, status='approved')
    b = store.create_project('Canal B')['id']
    store.add_source({'id':'src_b','sha256':'b','path':'b.mp4','project_id':b})
    job_b=store.create_job('src_b',{})
    clip_b=store.upsert_clip(job_b,0,{'start':0,'end':20})
    assert store.recent_hooks(clip_b)==[]
