"""Build a synthetic test video (test patterns + a robot voice reading an invented gaming
commentary) and a matching word-timed transcript. It exists so the pipeline can be run
end to end without any third-party footage and without downloading a speech model.

Usage: python scripts/make_demo_video.py OUT_DIR
Writes OUT_DIR/demo.mp4 and OUT_DIR/demo_transcript.json
"""
from __future__ import annotations

import json
import os
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

# (text, pause before in seconds, loud?)
LINES = [
    ("Alright chat, welcome back to the stream.", 0.6, False),
    ("Today we are trying the hardest stunt jump on the whole map.", 0.5, False),
    ("Nobody in this lobby has landed it yet.", 0.4, False),
    ("The plan is simple. Full speed down the hill, hit the ramp, and pray.", 0.8, False),
    ("First we need a faster car, because this one handles like a shopping cart.", 0.6, False),
    ("Okay, found one. It is bright pink, but it will do.", 1.2, False),
    ("Chat is telling me to use the boost early. I do not trust chat.", 0.5, False),
    ("Three, two, one, go!", 1.0, True),
    ("Come on, come on, come on!", 0.3, True),
    ("No way! Did you see that? The car flew over the entire bridge!", 0.4, True),
    ("We landed on the roof of the train. On the roof!", 0.3, True),
    ("That was the craziest thing that has ever happened on this channel.", 0.5, True),
    ("Let me check the replay, because I do not believe it.", 1.0, False),
    ("Look at the speed right here. That is two hundred miles an hour.", 0.6, False),
    ("Okay, now for the second challenge of the day.", 1.5, False),
    ("We have to lose a five star chase without leaving this parking lot.", 0.5, False),
    ("I have a secret trick for this. You hide behind the car wash.", 0.5, False),
    ("It works every single time. Almost every time.", 0.4, False),
    ("Wait, why is there a helicopter? There is never a helicopter!", 0.9, True),
    ("Insane! They actually found us in ten seconds.", 0.3, True),
    ("New plan. We run. We just run.", 0.4, True),
    ("And that, chat, is how you fail a challenge with style.", 1.2, False),
    ("Before we end, a quick tip for new players.", 1.0, False),
    ("Always save your game before you try something this dumb.", 0.4, False),
    ("Thanks for watching. See you in the next one.", 0.8, False),
]

SCENES = ["testsrc2", "mandelbrot", "life=mold=10:ratio=0.1:death_color=#102040:life_color=#40ff80", "gradients=speed=0.05",
          "testsrc2", "cellauto=rule=110", "mandelbrot=start_scale=2:end_scale=0.05", "gradients=speed=0.1:c0=red:c1=blue"]


def sh(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def main(out_dir: str, max_lines: int | None = None, size: str = "1280x720") -> None:
    global LINES
    LINES = LINES[:max_lines] if max_lines else LINES
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    words, inputs, graph, t = [], [], [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (text, pause, loud) in enumerate(LINES):
            txt, wav = Path(tmp) / f"l{i}.txt", Path(tmp) / f"l{i}.wav"
            txt.write_text(text)
            if os.name == "nt":
                # Windows builds of FFmpeg commonly omit flite. Use the installed offline voice.
                quote = lambda p: "'" + str(p).replace("'", "''") + "'"
                script = ("Add-Type -AssemblyName System.Speech; $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                          f"$voice.SetOutputToWaveFile({quote(wav)}); $voice.Speak([IO.File]::ReadAllText({quote(txt)})); $voice.Dispose()")
                sh(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", base64.b64encode(script.encode("utf-16le")).decode()])
            else:
                sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"flite=textfile={txt}:voice=slt",
                    "-ar", "48000", "-ac", "1", str(wav)])
            dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)]).strip())
            t += pause
            tokens = text.split()
            weights = [len(tok) + 1 for tok in tokens]
            speech = dur - 0.15  # the voice leaves a short tail of silence
            cur = t + 0.03
            for tok, wgt in zip(tokens, weights):
                d = speech * wgt / sum(weights)
                words.append({"w": tok, "start": round(cur, 3), "end": round(cur + d * 0.92, 3)})
                cur += d
            inputs += ["-i", str(wav)]
            graph.append(f"[{i}:a]volume={2.4 if loud else 0.8},adelay={int(t * 1000)}:all=1[a{i}]")
            t += dur
        total = round(t + 1.5, 2)

        n = len(LINES)
        graph.append(f"anoisesrc=c=brown:a=0.015:d={total}[bed]")
        graph.append("".join(f"[a{i}]" for i in range(n)) + f"[bed]amix=inputs={n + 1}:normalize=0:duration=longest,"
                     "alimiter=limit=0.9,aresample=48000[aout]")
        scene_len = total / len(SCENES)
        v_inputs = []
        for src in SCENES:
            sep = ":" if "=" in src else "="
            v_inputs += ["-f", "lavfi", "-t", f"{scene_len:.3f}", "-i", f"{src}{sep}s={size}:r=30"]
        graph.append("".join(f"[{n + j}:v]" for j in range(len(SCENES))) + f"concat=n={len(SCENES)}:v=1:a=0,format=yuv420p,"
                     "drawtext=text='SYNTHETIC TEST FOOTAGE':fontcolor=white:fontsize=36:box=1:boxcolor=black@0.5:x=30:y=30[vout]")
        sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, *v_inputs, "-filter_complex", ";".join(graph),
            "-map", "[vout]", "-map", "[aout]", "-t", str(total), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", str(out / "demo.mp4")])
    (out / "demo_transcript.json").write_text(json.dumps({"language": "en", "duration": total, "words": words}, indent=1))
    print(f"{out / 'demo.mp4'} ({total:.0f}s, {len(words)} palabras)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo", int(sys.argv[2]) if len(sys.argv) > 2 else None)
