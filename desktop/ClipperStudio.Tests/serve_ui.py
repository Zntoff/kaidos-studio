"""Serve an isolated synthetic library for browser checks. No API calls or user-library access."""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["PATH"] = str(ROOT / "desktop/tools") + os.pathsep + os.environ.get("PATH", "")
fixture = Path(tempfile.gettempdir()) / "kairos-workspace-fixture"
fixture.mkdir(exist_ok=True)
os.environ["CLIPPER_DATA_DIR"] = str(fixture / "data")
os.environ["DATABASE_URL"] = "sqlite:///" + (fixture / "qa.db").as_posix()
os.environ.pop("ANTHROPIC_API_KEY", None)

from clipper.config import Settings
from clipper.store import Store
from clipper.media import ffmpeg
from clipper.rights import register_source
from clipper.llm import OfflineLLM
from clipper.agents.base import Context
from clipper.agents.orchestrator import Orchestrator
from clipper.web.app import create_app
import uvicorn

s = Settings.from_env()
s.llm_provider, s.languages, s.scene_mode = "offline", ["en"], "off"
s.clip_min_s, s.clip_max_s, s.max_clips = 10, 22, 1
store = Store(s.database_url)
if not store.list_clips():
    sample = fixture / "workspace-demo.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=24", "-c:v", "libx264", "-preset", "ultrafast", str(sample)])
    source = register_source(store, sample, rights_status="own", evidence="Synthetic workspace fixture", language="en")
    Orchestrator(Context(settings=s, store=store, llm=OfflineLLM(), log=print)).run(source.id, review=False)
uvicorn.run(create_app(s), host="127.0.0.1", port=18765)
