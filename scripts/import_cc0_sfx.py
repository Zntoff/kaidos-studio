"""Import three classic editing accents from their public CC0 previews on Freesound.

No account, paid download or authentication is used. The original full-resolution downloads
are separate; these WAVs are adapted from the publicly playable HQ MP3 previews.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "sfx"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"
SOUNDS = [
    ("record_scratch_cc0", "musicvision31", "431774", 1.9, .45,
     "Record scratch clásico: giro inesperado o interrupción cómica; no usar sobre cada frase."),
    ("rimshot_cc0", "OverlookHotelRecords", "271208", 3.2, .40,
     "Ba-dum-tss / rimshot: remate de un chiste real. Primer acento del conjunto de percusión."),
    ("airhorn_cc0", "guitarguy1985", "64476", 1.5, .22,
     "Air horn: celebración o logro exagerado; usar brevemente y a volumen bajo."),
]


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ClipperStudio/0.4.1 (CC0 audio import)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def main() -> None:
    bundled = ROOT / "desktop" / "tools" / "ffmpeg.exe"
    ffmpeg = str(bundled) if bundled.is_file() else shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("Install FFmpeg first (desktop/setup.ps1).")
    manifest = OUT / "library.json"
    library = json.loads(manifest.read_text(encoding="utf-8"))
    imported = []
    with tempfile.TemporaryDirectory(prefix="clipper-cc0-") as work:
        for sound_id, author, number, duration, gain, description in SOUNDS:
            source = f"https://freesound.org/people/{author}/sounds/{number}/"
            html_bytes = get(source)
            html = html_bytes.decode("utf-8")
            if "creativecommons.org/publicdomain/zero/1.0" not in html:
                raise RuntimeError(f"CC0 license not confirmed for {source}; refusing to import.")
            matches = re.findall(r"https://cdn\.freesound\.org/previews/\d+/" + number + r"_\d+-hq\.mp3", html)
            if not matches:
                raise RuntimeError(f"No public HQ preview for {source}; no login download will be attempted.")
            preview_url = matches[0]
            audio = get(preview_url)
            raw = Path(work) / f"{sound_id}.mp3"
            raw.write_bytes(audio)
            wav = OUT / f"{sound_id}.wav"
            filters = (f"silenceremove=start_periods=1:start_threshold=-50dB,atrim=duration={duration},"
                       f"asetpts=PTS-STARTPTS,afade=t=out:st={duration - .12}:d=0.12,"
                       "alimiter=limit=0.7943:level=false")
            subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(raw), "-af", filters,
                            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)], check=True)
            probe = str(Path(ffmpeg).with_name("ffprobe.exe")) if Path(ffmpeg).suffix == ".exe" else "ffprobe"
            seconds = float(subprocess.check_output([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)], text=True).strip())
            imported.append({"id": sound_id, "file": wav.name, "kind": "sfx", "description": description,
                             "duration": round(seconds, 3), "gain": gain, "license": "CC0-1.0", "license_url": LICENSE,
                             "author": author, "source_url": source, "download_url": preview_url,
                             "source_format": "Public HQ MP3 preview", "license_checked_on": "2026-11-15",
                             "changes": "Leading silence removed; shortened with a fade; peak limited; converted to 48 kHz stereo PCM WAV.",
                             "source_page_sha256": hashlib.sha256(html_bytes).hexdigest(),
                             "download_sha256": hashlib.sha256(audio).hexdigest(), "file_sha256": hashlib.sha256(wav.read_bytes()).hexdigest()})
            print(f"Imported {sound_id}: {seconds:.2f}s, CC0, {author}")
    ids = {entry["id"] for entry in imported}
    library = [entry for entry in library if entry["id"] not in ids] + imported
    manifest.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "provenance.json").write_text(json.dumps(imported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
