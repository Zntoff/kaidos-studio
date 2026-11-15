"""Synchronize the three version declarations before tagging a release."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("version")
args = parser.parse_args()
if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
    parser.error("Use a stable semantic version, e.g. 0.10.1")
updates = []
for name, pattern, replacement in [
    ("pyproject.toml", r'(?m)^version = "[^"]+"', f'version = "{args.version}"'),
    ("clipper/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{args.version}"'),
    ("desktop/ClipperStudio/ClipperStudio.csproj", r'<Version>[^<]+</Version>', f'<Version>{args.version}</Version>'),
]:
    path = ROOT / name
    source, count = re.subn(pattern, replacement, path.read_text(encoding="utf-8"))
    if count != 1:
        raise ValueError(f"Expected exactly one version in {name}")
    updates.append((path, source))
for path, source in updates:
    path.write_text(source, encoding="utf-8")
print(f"Desktop and Docker version set to {args.version}")
