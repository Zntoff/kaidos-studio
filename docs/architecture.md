# Architecture

Kairos Studio has two apps with the same interface and the same rules:

| | Docker (web) | Desktop (Windows) |
|---|---|---|
| Code | `clipper/` (Python, FastAPI) | `desktop/ClipperStudio/` (C#, .NET 10, WPF + WebView2) |
| Interface | `clipper/web/static/` served by FastAPI | the same files, served by a local server inside the app |
| Transcription | faster-whisper | whisper.cpp |
| Render | FFmpeg on the CPU (libx264), or NVIDIA when the host exposes it | FFmpeg with NVENC, AMF, Quick Sync or the CPU |
| Data | `./data` (SQLite or Postgres) | `%LOCALAPPDATA%\ClipperStudio` |
| CLI | yes (`clipper …`) | no |

Shared files live at the root: `assets/` (fonts, sounds, style catalog), `config/` (AI providers and spoiler
terms) and `clipper/prompts/` (the subagent prompts).

## AI providers

The subagents don't depend on a provider. Each one answers by calling a function whose schema is its contract,
and two APIs support that: Anthropic's (Messages) and OpenAI's (Chat Completions), which Gemini, OpenRouter,
Mistral, DeepSeek, Groq, Ollama, LM Studio and vLLM also speak. The catalog is in `config/providers.json`; the
clients are in `clipper/llm.py` and `desktop/ClipperStudio/Ai/Llm.cs`.

Because servers don't all behave the same, the OpenAI-compatible client forces the function call and, if the server
rejects that, tries again without forcing it. If the model doesn't accept images, it continues without the frames,
and if it answers with JSON as text, it uses that. Contract validation and its retries are the same for all.

## Flow

```
video ─► transcript + signals (loudness, scene cuts)
      ─► Analysis (AI) ─►   the person chooses moments, model, framing, captions and languages
      ─► for each moment:  Editing (EDL) ─► Captions ┐
                                            Metadata ┴─► Render ─► Review ─► approval queue
```

| Subagent | Decides | Contract |
|---|---|---|
| Analysis | Which moments are worth a clip | `AnalysisProposal` |
| Editing | Cut, hook, own commentary, style, sounds, zoom, color | `EditDecision` → `EDL` |
| Captions | Text fixes, words to highlight, translation | `CaptionEdit` |
| Metadata | Title, description and hashtags per platform and language | `MetadataSet` |
| Reviewer (Docker only) | Spoilers and editorial value, on the finished clip | `ReviewJudgement` |

- **Contracts.** Each subagent answers by calling a tool whose schema is its contract (`clipper/schemas.py`,
  `desktop/ClipperStudio/Ai/Agents.cs`). Extra rules are checked too: durations, indices, languages and limits. If
  a check fails, the model gets the error and retries up to 2 times.
- **No invented timestamps.** The AI points to segments and words by index and the code turns them into seconds.
  A cut can only fall on the edge of a real word.
- **EDL.** Editing produces an edit decision list (JSON). The Python render, the C# render and the browser preview
  read the same list and use the same math: color matrix, font size as libass computes it, and zoom and shake
  expressions. That's why the three look the same.
- **A person decides.** No clip posts on its own: every one goes through the approval queue. The decision and who
  made it are stored in the package.
- **Trace.** Each step records the subagent, the prompt version, the model, the attempts, the tokens and the
  duration. API usage is added up in the Settings panel.

## Output package

Each clip gets its own folder with, per language, `clip.mp4`, `captions.srt` and `metadata.json` (YouTube, TikTok,
Instagram), plus `edl.json`, the checks, `sound_licenses.json` and `package.json` with the human decision.

## Known limits

- Automatic posting to the platforms isn't built: it requires their API audits.
- The face inset is a fixed region chosen from frames, not tracking.
- The desktop app doesn't yet include the AI reviewer, automatic re-editing after a rejection, the offline (no-AI)
  mode or the posting schedule proposal.
- Transcription is accelerated only on NVIDIA (CUDA); on AMD and Intel it runs on the CPU.
- The text safe areas and the metadata limits are working values, not official figures.
