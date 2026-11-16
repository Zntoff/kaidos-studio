KAIROS STUDIO - PORTABLE (Windows x64)

1. Extract the ENTIRE ZIP to a writable folder, outside Program Files.
2. Open KairosStudio.exe. Do not run it directly from the ZIP preview.
3. Complete the first-run setup: video output folder and optional AI provider.

The portable.flag file makes this copy keep its library, settings, WebView2 profile
and downloaded models in the adjacent data folder. Installed Kairos copies keep
their separate library in %LOCALAPPDATA%\ClipperStudio.

Keep portable.flag and data when replacing the application with a newer ZIP.
Back up data and any external video folders before upgrading. Never distribute
your data folder: it contains personal projects and encrypted API credentials.
Windows protects saved API keys for your Windows account on this computer.
After moving to another computer/account, enter your keys again. External video
paths may also need to be updated. CLIPPER_STUDIO_DATA overrides portable mode.

Microsoft WebView2 Runtime is required (normally present on Windows 11).
If missing, run tools\MicrosoftEdgeWebview2Setup.exe. It downloads the runtime
from Microsoft and needs internet access. The app itself includes .NET and FFmpeg;
speech models are downloaded separately when needed.

For the supported installation/uninstallation workflow, use the Setup EXE instead.
Unsigned local builds can show Windows publisher/SmartScreen warnings.
