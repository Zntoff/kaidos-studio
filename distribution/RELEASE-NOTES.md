### Downloads

- **Setup-win-x64.exe**: per-user Windows installer, Start menu entry and uninstaller. Upgrades preserve your existing library.
- **Portable-win-x64.zip**: extract everything and run KairosStudio.exe; this copy stores its data beside the executable.
- **Docker.zip**: extract and run `docker compose -f compose.yaml up -d --build`. Docker and internet access are required for the initial build.
- **Docker image**: `docker run -d -p 127.0.0.1:8000:8000 -v "$PWD/kairos-data:/data" ghcr.io/zntoff/kairos-studio:latest`, no build needed.

Configure your provider and API key on first use. No personal library or API keys are included.
The Windows installer and portable app include .NET and FFmpeg. WebView2 installation (if missing) and speech model downloads need internet.

**Unsigned build:** Windows may show a publisher/SmartScreen warning until the builds are code-signed.
Compare downloads with SHA256SUMS.txt before use.
