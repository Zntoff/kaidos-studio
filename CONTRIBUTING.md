# Contributing

Thanks for wanting to improve Kairos Studio! Contributions are accepted under the
[Apache License 2.0](LICENSE): by opening a pull request you agree that your code is published under it.

## Before you start

- For large changes, open an issue first and describe what you want to do.
- One pull request, one change. Explain what changes and how you tested it.
- If the change affects what users see, update `README.md` and add a line under `## [Unreleased]` in
  `CHANGELOG.md`.

## Branches and environments

| Branch | Environment | Rules |
|---|---|---|
| `dev` | Development | Default target for pull requests. CI must pass before merging. |
| `main` | Production | Only receives pull requests from `dev`. Every release tag points to a commit on `main`. |

```
feature/your-change ──PR──► dev ──PR (release)──► main ──tag vX.Y.Z──► draft GitHub Release
```

1. Branch from `dev`: `git switch dev && git pull && git switch -c feature/short-name`
   (use `fix/` for bug fixes and `docs/` for documentation).
2. Open the pull request against `dev`. The [CI workflow](.github/workflows/ci.yml) checks that the three version
   declarations match, runs the Python tests on Linux and builds and tests the desktop app on Windows.
3. When `dev` is ready for a release, open a pull request from `dev` to `main` (see [Releases](#releases)).

Hotfixes branch from `main`, go to `main` through a pull request, and are then merged back into `dev`.

## Development setup

### Web app and CLI (Python)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                                # renders real video: takes a few minutes
```

You need FFmpeg with libass on the PATH. The tests don't call any AI provider: they use scripted responses.

### Desktop app (C#, Windows)

```powershell
powershell -ExecutionPolicy Bypass -File desktop\setup.ps1   # FFmpeg and yt-dlp in desktop\tools
dotnet run --project desktop\ClipperStudio                   # open the app
dotnet run --project desktop\ClipperStudio.Tests             # integration tests (no API key)
node desktop\ClipperStudio.Tests\setup-ui.cjs                # first-run setup tests
```

You need the .NET 10 SDK. More details in [desktop/README.md](desktop/README.md).

## What both apps share

The interface (`clipper/web/static/`), the prompts (`clipper/prompts/`), the style catalog
(`assets/studio/catalog.json`), the fonts and the sounds are **the same files** for Docker and desktop. If you
change one, test both apps. The Python render (`clipper/media/`) and the C# render
(`desktop/ClipperStudio/Engine/`) follow the same math: a change in one needs the same change in the other.

## Project rules

- **Language:** code, comments, commit messages and documentation are in English. Interface text is translated
  through `clipper/web/static/locales.tsv`; its first column holds the source strings used in the code, so
  don't edit an interface string without updating its row.
- **Prompts:** if you change a prompt in `clipper/prompts/`, bump the number on its first line
  (`<!-- version: N -->`).
- **Sounds and fonts:** only with a license that allows redistribution. Record the source and the license
  (`assets/sfx/library.json`, `assets/fonts/LICENSES.md`). No license, no entry.
- **No private data:** no keys, videos, transcripts or paths from your computer.
- **Style:** follow the style of the file you touch. Comments explain why, not what.
- **Commits:** short imperative subject (`Add Gemini schema fallback`), with details in the body if needed.

## Versioning

Kairos Studio follows [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

- **PATCH** (`0.10.1`): bug fixes that change no behavior people rely on.
- **MINOR** (`0.11.0`): new features or changes that stay compatible with existing libraries and settings.
- **MAJOR** (`1.0.0`): changes that need people to act, such as a data migration they can't undo.

The same number lives in three places, which must always match: `pyproject.toml`, `clipper/__init__.py` and
`desktop/ClipperStudio/ClipperStudio.csproj`. Change them together with `scripts/set-version.py`, and check them
with `scripts/check-version.py` (CI runs it on every push).

## Releases

1. On `dev`, set the new version and move the `[Unreleased]` entries in `CHANGELOG.md` under a new
   `## [X.Y.Z]` heading:

   ```bash
   git switch dev && git pull
   python scripts/set-version.py 0.11.0
   # Edit CHANGELOG.md: rename the Unreleased entries to ## [0.11.0] and leave an empty ## [Unreleased] above.
   python scripts/check-version.py --changelog
   git commit -am "Release 0.11.0"
   git push
   ```

2. Open a pull request from `dev` to `main` titled `Release 0.11.0`, wait for CI and merge it.

3. Tag the merge commit on `main` and push the tag:

   ```bash
   git switch main && git pull
   git tag -a v0.11.0 -m "Kairos Studio 0.11.0"
   git push origin v0.11.0
   ```

4. The [release workflow](.github/workflows/release.yml) checks that the tag is on `main` and matches the version
   and the changelog, builds the installer, the portable ZIP and the Docker bundle, runs the tests and creates a
   **draft** release. Its notes are the changelog section, the download guide
   ([distribution/RELEASE-NOTES.md](distribution/RELEASE-NOTES.md)) and the list of merged pull requests.

5. Review the draft on GitHub (downloads, checksums, notes) and click **Publish release**.

To build test packages from `dev` without releasing, run the release workflow manually from the **Actions** tab
and download its artifacts. Signing, local builds and the package contents are covered in
[distribution/README.md](distribution/README.md).
