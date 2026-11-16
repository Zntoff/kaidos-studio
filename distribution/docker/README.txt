KAIROS STUDIO @VERSION@ - DOCKER

Requires Docker Engine with Compose v2, or Docker Desktop, and internet for the first build.
Extract the entire ZIP. From this folder run:

  docker compose -f compose.yaml up -d --build

Or on Windows: powershell -ExecutionPolicy Bypass -File Start-Kairos.ps1
On Linux/macOS: sh start-kairos.sh
Open http://localhost:8000 and configure your AI provider in Settings.
No API keys are shipped. The .env.example file is documentation; configure keys in the UI.

Optional NVIDIA GPU: docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
Requires the host NVIDIA Container Toolkit / compatible Docker Desktop GPU support.

Videos, projects and settings persist in data/. Put source videos in input/.
Treat data/ as private. The Docker version stores provider keys in its protected
settings file; restrict access to your host account and never redistribute data/.

Stop: docker compose -f compose.yaml down
Upgrade: back up data/ and external video folders, stop the old container, then
copy your data/ and input/ directories into the new version's extracted folder
and run the startup command. Do not run both versions on port 8000 simultaneously.
The UI is bound to localhost. Do not expose it publicly; this is a single-user app.
