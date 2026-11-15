# Kairos Studio for Windows: development guide

This guide is for people who want to **build or change** the desktop app. To just use it, read the
[main README](../README.md#desktop-app-windows).

The app is C# (.NET 10, WPF + WebView2). The window shows the same interface as the Docker version
(`clipper/web/static/`), served by a local HTTP server that starts inside the app on `127.0.0.1` and a random
port. The app's own C# engine transcribes with whisper.cpp, calls the AI provider and renders with FFmpeg.

## Structure

```
desktop/
  ClipperStudio/            the app
    Ai/                     AI clients, subagents, transcription and job flow
    Engine/                 render (FFmpeg), ASS captions, editor, store, settings, GPU, tools
    Server/                 HTTP API used by the interface (same routes as the Docker version)
    MainWindow.xaml(.cs)    window with WebView2
  ClipperStudio.Tests/      integration tests against the real server (no API key), plus browser UI tests
  installer/                Inno Setup script, signing wrapper and install round-trip test
  licenses/                 third-party licenses shipped with the package
  setup.ps1                 downloads FFmpeg and yt-dlp to desktop\tools
  publish.ps1               builds the distributable folder in desktop\dist
  sign.ps1                  Authenticode signing (see SIGNING.md)
```

The project links files from the repository root: the interface, `assets/`, `clipper/prompts/` and `config/`.
They are copied next to the executable at build time, so build from a full clone. The .NET namespaces, the
project folder and the `CLIPPER_*` variables keep their original names so existing libraries keep working.

## Requirements

- Windows 11 x64 (Windows 10 with WebView2 should work but isn't tested) and the
  [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0).
- WebView2 Runtime (included with Windows 11).
- Optional: an NVIDIA, AMD or Intel GPU with a recent driver for hardware encoding.

## Build and run

```powershell
powershell -ExecutionPolicy Bypass -File desktop\setup.ps1   # FFmpeg (with NVENC and libass) and yt-dlp in desktop\tools
dotnet run --project desktop\ClipperStudio
```

`desktop\tools`, `bin`, `obj` and `dist` are in `.gitignore`. If you only have a runtime newer than .NET 10, run
with `$env:DOTNET_ROLL_FORWARD = 'Major'`.

## Distributable

```powershell
powershell -ExecutionPolicy Bypass -File desktop\publish.ps1
```

Creates `desktop\dist\KairosStudio-<version>\`, with a self-contained `KairosStudio.exe` (no .NET install needed)
and FFmpeg, yt-dlp, fonts and sounds beside it. For the installer, the portable ZIP and the Docker bundle together,
use `release.ps1` from the root (see [distribution/README.md](../distribution/README.md)). Releases are built by
GitHub Actions from tags on `main` (see [CONTRIBUTING.md](../CONTRIBUTING.md#releases)).

## Tests

```powershell
dotnet run --project desktop\ClipperStudio.Tests      # integration tests (temporary library, no AI calls)
node desktop\ClipperStudio.Tests\setup-ui.cjs         # first-run setup
node desktop\ClipperStudio.Tests\safe-area-ui.cjs     # safe areas in the preview
```

The browser tests run against an isolated server with synthetic data, without real accounts or AI calls:

```powershell
python desktop\ClipperStudio.Tests\serve_ui.py
# Then, with PLAYWRIGHT_MODULE pointing to Playwright (and optionally CLIPPER_QA_URL / CLIPPER_QA_OUTPUT):
node desktop\ClipperStudio.Tests\layout-ui.cjs        # 320 to 1920 px, low-height windows
node desktop\ClipperStudio.Tests\workspace-ui.cjs     # search, private resources, late responses
node desktop\ClipperStudio.Tests\providers-ui.cjs     # AI provider settings against mock servers
node desktop\ClipperStudio.Tests\locale-audit.cjs     # every screen in the five languages
node desktop\ClipperStudio.Tests\editor-locale-ui.cjs # editor drag, save and restore per language
```

The synthetic library lives in the temporary folder `kairos-workspace-fixture`. `pytest tests/test_locales.py`
checks the translation catalog statically.

## App data

Everything lives in `%LOCALAPPDATA%\ClipperStudio`: library, jobs, transcripts, cache, tools installed from
Settings and `settings.ai.json`, with API keys encrypted with DPAPI. The portable build (with `portable.flag`
beside the executable) uses its own `data` folder instead. To use another folder (for example in tests), set
`CLIPPER_STUDIO_DATA`. Generated videos go to the folder chosen in the first-run setup.

Useful variables: `CLIPPER_MODEL_FAST`, `CLIPPER_MODEL_STANDARD` and `CLIPPER_MODEL_SUPERIOR` to change the Anthropic
models, `ANTHROPIC_API_KEY` as an alternative to saving the key in Settings, and `CLIPPER_ENCODER` (for example
`libx264`, `h264_amf`, `h264_qsv`) to force an encoder; an encoder that doesn't work on the machine is ignored with
a warning.

## GPU and performance

**Settings → Performance and hardware** offers automatic, CPU or a detected GPU, 30/60 fps and quality.

1. **Detection.** Adapters are found through DXGI (falling back to the Windows registry), with vendor, memory,
   integrated or dedicated, and driver version. It runs in the background when the app opens.
2. **Real tests.** Each encoder is tried with a 0.3 s encode, because FFmpeg listing an encoder doesn't mean it
   works. Each vendor has several recipes, from best quality to most basic, and the first one the driver accepts
   is kept.
3. **Order.** Dedicated NVIDIA (NVENC) → dedicated AMD (AMF) → Intel Arc (Quick Sync) → integrated Intel → integrated
   AMD → CPU (x264). Adapters are selected explicitly.
4. **Fallback.** If a render fails midway, the app retries on the CPU and the job log says what happened. If a GPU
   exists but doesn't respond, Settings says so and suggests updating its driver.

| Hardware | Render | Decoding | Transcription |
|---|---|---|---|
| NVIDIA | NVENC H.264 / HEVC / AV1 | CUDA | whisper.cpp CUDA (CPU if it doesn't start) |
| AMD dedicated or integrated | AMF H.264 / HEVC | D3D11VA | whisper.cpp CPU (OpenBLAS) |
| Intel Arc or integrated | Quick Sync H.264 / HEVC | D3D11VA | whisper.cpp CPU (OpenBLAS) |
| No GPU or broken driver | x264 on the CPU | CPU | whisper.cpp CPU |

whisper.cpp doesn't publish Windows builds with Vulkan or ROCm, so on AMD and Intel transcription runs on the CPU.
Choosing CPU in Settings also forces CPU transcription. Physical tests were done on an NVIDIA RTX 5070 Ti, an
integrated AMD Radeon and the CPU; Intel support is implemented but not yet tested on real hardware.

Drivers: the current FFmpeg build (BtbN) needs NVIDIA driver series 570 or later; AMD Adrenalin includes AMF
(Radeon RX 400 and later, Ryzen with integrated graphics); the Intel graphics driver includes Quick Sync (6th
generation and later, Arc and Core Ultra). Detection runs again after reinstalling the tools or restarting the app.

The container uses the same interface and stores its render preferences in the data volume
(`render-settings.json`). It only offers encoders that are reachable and tested inside the container; Docker GPU
access must be configured on the host (`docker-compose.gpu.yml`).

## Safe areas for Shorts and Reels

The shared profile is **conservative**, not an official universal specification: on 1080×1920 the usable area
goes from x=80 to 900 and from y=300 to 1240, leaving room for the header, description, account and side controls.
`Engine/SafeArea.cs` defines the margins and text fitting, and `static/safe-area.js` repeats the calculation in the
preview. The size, borders, glow, rotation and travel of animations count for the fit, not just the position of
their center.

**Full + background** mode fits the main video to the full 1080×1920 canvas, centered and keeping its aspect ratio
(a 16:9 video takes 1080×608), and the background fills the rest. Automatic framing centers the subject in the usable
area, accounting for zooms and shakes; if it doesn't fit, it uses the full video with a background. A manual crop
that pushes an identified main region out of the area is rejected and the draft is kept. When no such region
exists, the review warns that faces and action in the source must be checked. The editor guide is on by default;
hiding it doesn't turn off the render protection. Packages store `safe_area.json` and a check in `review.json`.

References checked on 15 Nov 2026:

- Google recommends avoiding the top 10%, bottom 25% and right 10% in Shorts ads:
  https://business.google.com/us/ad-solutions/youtube-ads/shorts-ads/
- Meta's primary guide required sign-in at the time: https://www.facebook.com/business/help/980593475366490 .
  The public reference https://anjin.media/tools/safe-zone-checker describes 14% top, 35% bottom and 6% sides for
  Reels ads. It is guidance, not a verification of every organic interface.

Interfaces and devices change: also check the platform preview before posting. Reserved bands may hold background
or decoration, but no key elements.

## Features by area

- **Projects.** The previous library moved to the **General** project. Projects can be created and edited; the
  sidebar selector switches the visible videos, jobs, clips and queue. **Move** on a video also moves its
  generations and clips, once the project's active jobs finish. Files keep their locations.
- **Usage.** The bottom-left indicator shows the **estimated** remaining credit from the amount set in Settings and
  the calls logged by the app; without a credit amount it shows the last 30 days of spend. It is not a balance read
  from the provider.
- **AI providers.** Settings → AI provider supports Anthropic, OpenAI, Gemini, OpenRouter, Mistral, DeepSeek, Groq,
  Ollama or any OpenAI-compatible server. Each provider keeps its own key, loads its model list and maps a model
  to each tier; prices drive the usage estimate. Models must return valid JSON for the agent contracts; a model
  without vision runs without frames. Local servers need no key when they don't require authentication. From
  Docker, `localhost` is the container: for Ollama on Windows use `http://host.docker.internal:11434/v1`. Protocol
  references: [OpenAI](https://developers.openai.com/api/reference/resources/chat),
  [Gemini](https://aistudio.google.com/docs/openai) and
  [Ollama](https://docs.ollama.com/api/openai-compatibility). Automated tests use mock servers and spend no credit;
  they don't certify every model of every remote account.
- **Workspace.** The home page has the logo, search and three actions: define a project, add a video or generate
  a short. Opening the short picker makes no AI call until a video is chosen. The sidebar has a persistent compact
  mode and becomes a keyboard-accessible side menu on mobile.
- **Resources.** Images, audio and documents up to 100 MB per file, per project, with preview and download. They
  aren't inserted into videos automatically.
- **Jobs and preview.** Search and filters by project and status, with thumbnails. The preview separates video,
  review and posting suggestions, with copy buttons per platform. **Change AI** in the sidebar switches the
  provider for the next generations.
- **Interface language.** English by default, with Spanish, Portuguese, French and German. Only the local interface
  preference is stored; generation languages, prompts, transcripts and metadata don't change. Selector values stay
  the same when their labels are translated, and native windows reuse the same catalog.
- **Library and security.** The + button next to search imports YouTube/Twitch links, local videos and resources.
  Delete asks for confirmation and keeps managed files for manual recovery. The API requires a local session and a
  CSRF token. Signing is described in [SIGNING.md](SIGNING.md).
- **Brand.** The Kairos identity covers the shared interface, the Windows icon, the splash screen and the executable
  name. Themes: dark, light or system. Inter, Instrument Serif and JetBrains Mono are served locally under the OFL.
  `python scripts/make_kairos_brand.py` rebuilds the brand assets; see
  [the brand reference](../clipper/web/static/brand/README.md).
