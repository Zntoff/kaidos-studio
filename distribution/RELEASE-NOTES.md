Three downloads for this version:

- **Setup-win-x64.exe**: per-user Windows installer, Start menu entry and uninstaller. Upgrades preserve your existing library.
- **Portable-win-x64.zip**: extract everything and run KairosStudio.exe; this copy stores its data beside the executable.
- **Docker.zip**: extract and run `docker compose -f compose.yaml up -d --build`. Docker and internet access are required for the initial build.

Configure your provider and API key on first use. No personal library or API keys are included.
The Windows installer and portable app include .NET and FFmpeg. WebView2 installation (if missing) and speech model downloads need internet.

**Build status:** the default workflow creates an unsigned Windows build and a draft release. A verified publisher identity is required before distributing a signed release. Unsigned builds may trigger Windows publisher/SmartScreen warnings.
Compare downloads with SHA256SUMS.txt before use.
