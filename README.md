<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="clipper/web/static/brand/mark.svg">
    <img src="clipper/web/static/brand/mark-black.svg" width="88" alt="Kairos Studio">
  </picture>
</p>

<h1 align="center">Kairos Studio</h1>

<p align="center"><em>The exact moment.</em></p>

<p align="center">
  An AI clipping tool that turns any long video into vertical shorts ready to post.
  The AI picks the best moments, then edits, captions and translates them, and you approve every clip.
  Works with Claude, OpenAI, Gemini, OpenRouter, local models and more.
</p>

<p align="center">Created by <a href="https://github.com/Zntoff"><b>ZNTOff</b></a></p>

<p align="center">
  <a href="https://github.com/Zntoff/kairos-studio/actions/workflows/ci.yml"><img src="https://github.com/Zntoff/kairos-studio/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://github.com/Zntoff/kairos-studio/releases/latest"><img src="https://img.shields.io/github/v/release/Zntoff/kairos-studio?color=black&label=release" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-black" alt="Apache 2.0 license"></a>
  <img src="https://img.shields.io/badge/Docker-web-black" alt="Docker">
  <img src="https://img.shields.io/badge/Windows%2011-desktop-black" alt="Windows 11">
</p>

<p align="center">
  <a href="https://ko-fi.com/K7D12AP6M0"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support the project on Ko-fi"></a>
</p>

---

## What it does

Kairos Studio works with any long-form content: streams, podcasts, interviews, classes, talks, tutorials, vlogs
or gameplay. It is built for creators who want to get more out of their videos, editors who clip a channel, and
teams that post on several platforms and in several languages.

You add a video (a file, or a YouTube, Twitch or Kick link). Kairos Studio transcribes it and the AI proposes the
moments worth a clip, each with a score and a reason. You choose which ones to generate, and with which model,
framing, caption style and languages. Every clip comes out at 1080×1920 with:

- **a hook and your own commentary** on screen, so the clip adds something instead of being a plain cut;
- **word-by-word captions** in 8 styles, with translation (English and Spanish);
- **effects, zooms, color looks, animated titles, sounds and music**, with loudness normalized to −14 LUFS;
- **a title, description and hashtags** per platform (YouTube Shorts, TikTok, Instagram Reels) and per language.

You can then fine-tune everything in a **timeline editor** with a live preview. No clip posts on its own: every
one goes through an **approval queue** where a person decides.

## Two versions, one app

|  | **Desktop** (Windows) | **Docker** (web) |
|---|---|---|
| For | Windows 11, nothing else to install | Linux, macOS, Windows or your own server |
| Used from | A regular Windows window | The browser, at `http://localhost:8000` |
| Render | NVIDIA (NVENC), AMD (AMF), Intel (Quick Sync) or CPU | CPU, or NVIDIA when the host exposes it |
| Extras | One-click tool installer; installer or portable ZIP | Command line, AI reviewer, Postgres |

Both share the interface, the subagents, the styles, the fonts and the sounds.

## Before you start

- **An AI provider with your own API key.** Everyone uses their own key and pays that provider for usage:

  | Provider | Where to create the key | Notes |
  |---|---|---|
  | Anthropic · Claude (default) | [console.anthropic.com](https://console.anthropic.com/settings/keys) | Models already set up: Haiku, Sonnet and Opus |
  | OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) | |
  | Google Gemini | [aistudio.google.com](https://aistudio.google.com/apikey) | |
  | OpenRouter | [openrouter.ai](https://openrouter.ai/keys) | One key for models from many providers |
  | Mistral, DeepSeek, Groq | In each provider's console | Check that the model accepts images |
  | Ollama, LM Studio, vLLM | No key | Free and private; needs a capable GPU. Lower quality than cloud models |

  For providers other than Claude, choose which model each tier uses (fast, standard, superior) in
  **Settings → AI provider**: the app loads the provider's own model list. The prompts were written and tested with
  Claude, so analysis and editing quality may vary with other models. **Settings** also shows how much you have
  spent and how much is left of the budget you set.
- **Rights to the video.** Before processing, the app asks for the rights status (`own`,
  `written_permission`, `official_press` or `cc_licensed`) and some evidence. Downloading a video does not give
  you the right to publish it.

---

## Desktop app (Windows)

### Install

Download one of these from the [latest release](https://github.com/Zntoff/kairos-studio/releases/latest):

- **`KairosStudio-<version>-Setup-win-x64.exe`**: per-user installer with a Start menu entry and an uninstaller.
  Updates keep your library.
- **`KairosStudio-<version>-Portable-win-x64.zip`**: extract the whole ZIP to a writable folder and open
  `KairosStudio.exe`. This copy keeps its data in a `data` folder beside the executable.

Neither needs .NET, Python or FFmpeg installed: everything is included. Compare the downloads with
`SHA256SUMS.txt`. If Windows SmartScreen warns about an unknown publisher, the build is unsigned; see
[SECURITY.md](SECURITY.md#windows-signing-and-distribution).

### First run

1. The **first-run setup** asks for the folder where generated videos go, your AI provider and your API key.
   You can skip both and do them later in **Settings**.
2. In **Settings → Tools**, install **transcription** (whisper.cpp and a multilingual model of about 200 MB).
   If FFmpeg is missing, install it from the same panel.
3. Click **Create clip**, or register a video with its rights, click **Process** and follow the same steps as in
   the Docker version: choose moments, generate and approve.
4. Each clip has buttons to open it in the editor or **open its folder**.

Without an API key the app still works as a manual editor: you can create, edit and render clips.

### Hardware

**Settings → Performance and hardware** lets you choose automatic, CPU or a detected GPU, 30/60 fps and quality.
Every encoder is tested with a real encode before it is offered: NVIDIA uses NVENC, AMD uses AMF and Intel uses
Quick Sync. If a GPU rejects a render, the app retries on the CPU and says so in the log.

### Where your data lives

- Generated videos go to the folder you chose.
- The library, jobs, cache and downloaded tools live in `%LOCALAPPDATA%\ClipperStudio` (the portable copy uses
  its own `data` folder).
- API keys are stored **encrypted for your Windows user** (DPAPI). Uninstalling keeps your data; delete that
  folder to remove it.

---

## Docker (web)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS) or Docker Engine
(Linux). You do not need Python, FFmpeg or fonts.

The easiest way is `KairosStudio-<version>-Docker.zip` from the
[latest release](https://github.com/Zntoff/kairos-studio/releases/latest): extract it and follow its `README.txt`.
To run it from source:

```bash
git clone https://github.com/Zntoff/kairos-studio.git
cd kairos-studio
cp .env.example .env          # Windows (PowerShell): Copy-Item .env.example .env
docker compose up --build
```

Open **http://localhost:8000**. The first build takes a few minutes.

1. Go to **Settings → AI provider**, choose the provider, paste your API key and, if it isn't Claude, choose
   the models. You can also use the variables in `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `CLIPPER_AI_PROVIDER`…). For Ollama on your computer, use `http://host.docker.internal:11434/v1`.
2. In **Videos**, upload a video (or pick one from the `./input` folder, better for large files) and fill in its
   rights.
3. Click **Process** and the AI proposes the moments.
4. In **Jobs → Choose the moments**, select the ones you want and choose model, framing, captions and languages.
5. Review the clips in the **approval queue**, open them in the editor if you want to adjust them, and approve or
   reject them.

Results are saved in `./data/out/`: for each clip and language, `clip.mp4`, `captions.srt` and `metadata.json`.

**Useful commands**

```bash
docker compose up -d                       # run in the background
docker compose logs -f                     # follow the log
docker compose down                        # stop (data stays in ./data)
git pull && docker compose up --build -d   # update
docker compose run --rm app --help         # command line
```

To render with an NVIDIA GPU on a host with Docker GPU support:
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`.

> [!WARNING]
> The panel has no login. `docker-compose.yml` publishes it only on your computer (`127.0.0.1`). Do not expose
> it to the internet or a shared network without a reverse proxy with authentication.

The first transcription downloads the Whisper model (needs internet). Every other option is documented in
[`.env.example`](.env.example): languages, maximum clips, duration, Whisper model, Postgres…

<details>
<summary><b>Without Docker (Python)</b></summary>

You need Python 3.11 or later and FFmpeg with libass on the PATH.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .                                      # add [postgres] to use Postgres
cp .env.example .env                                  # then set your ANTHROPIC_API_KEY
clipper web                                           # panel at http://localhost:8000
```
</details>

<details>
<summary><b>Command line</b></summary>

```bash
clipper source add video.mp4 --rights own --evidence "my own recording" --language en
clipper analyze src_xxxx --analysis-model fast                       # propose moments
clipper generate job_xxxx --pick cand00,cand02 --model standard      # generate the chosen ones
clipper queue                                                        # approval queue
clipper approve <clip_id> --by <your-name>
clipper reject  <clip_id> --by <your-name> --note "needs context"
clipper run src_xxxx --offline        # the whole pipeline without AI, for testing
```

In Docker, prefix with `docker compose run --rm app` (for example, `docker compose run --rm app queue`).
</details>

---

## Privacy

The project has no servers of its own and no telemetry. It only connects to the AI provider you choose, with your
key, and, when you ask, to the sites you download videos from. Your videos, transcripts and clips stay on your
computer. More details in [SECURITY.md](SECURITY.md).

## Development

| Branch | Environment | Purpose |
|---|---|---|
| `dev` | Development | Day-to-day work and integration. Changes land here first. |
| `main` | Production | Only receives tested changes from `dev`. Every release is tagged here. |

Releases follow [semantic versioning](https://semver.org) with tags like `v0.10.0`. Pushing a tag on `main`
builds the installer, the portable ZIP and the Docker bundle, runs the tests and prepares a draft GitHub
Release. The full process is in [CONTRIBUTING.md](CONTRIBUTING.md#releases).

```bash
pip install -e ".[dev]" && pytest                                  # Python app (renders real video)
powershell -ExecutionPolicy Bypass -File desktop\setup.ps1          # desktop: download FFmpeg and yt-dlp
dotnet run --project desktop\ClipperStudio                          # desktop: open the app
dotnet run --project desktop\ClipperStudio.Tests                    # desktop: integration tests
```

No test calls a real API: they use scripted responses, including for the OpenAI-compatible mode.
How it works inside (subagents, contracts, EDL, output package): [docs/architecture.md](docs/architecture.md).
Desktop details: [desktop/README.md](desktop/README.md).

### Project structure

```
clipper/            web app and CLI (Python): subagents, render, panel
  agents/           analysis, editing, captions, metadata, reviewer, orchestrator
  media/            FFmpeg, transcription, ASS captions, audio, render
  prompts/          subagent prompts (shared with desktop)
  web/static/       interface and editor (shared with desktop)
desktop/            desktop app (C#, .NET 10, WPF + WebView2)
  ClipperStudio/    the app: Ai/, Engine/, Server/
  ClipperStudio.Tests/
  installer/        Inno Setup installer
assets/             fonts, sounds, style catalog and brand (shared)
config/             AI providers and spoiler terms
distribution/       release guide, release notes and the Docker download bundle
docs/               architecture
scripts/            utilities: versioning, packaging, sounds, icon, demo video
tests/              Python app tests
release.ps1         builds the three release formats
```

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and, for security issues,
[SECURITY.md](SECURITY.md). The changes in each version are in [CHANGELOG.md](CHANGELOG.md).

## Support the project

Kairos Studio is free and open source. If it saves you time and you want it to keep growing, you can leave a tip
on Ko-fi:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/K7D12AP6M0)

## License

Copyright 2026 [ZNTOff](https://github.com/Zntoff). Released under the [Apache License 2.0](LICENSE): you can use,
modify and redistribute it, including commercially, as long as you keep the license notice and the
[NOTICE](NOTICE) file. The fonts, some sounds and the downloaded tools (FFmpeg, yt-dlp, whisper.cpp) have their
own licenses, also listed in [NOTICE](NOTICE).

Kairos Studio is not affiliated with Anthropic, OpenAI, Google, YouTube, TikTok, Instagram or the owners of the
content you clip. Publishing a clip is still your responsibility: check the rights and the editorial value before
you do.
