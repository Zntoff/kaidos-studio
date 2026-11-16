"""Verify archives without running application code or accessing personal data."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(directory: Path):
    manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8-sig"))
    for item in manifest["files"]:
        assert Path(item["name"]).name == item["name"], "Artifact path must be a filename"
        file = directory / item["name"]
        assert file.stat().st_size == item["bytes"] and digest(file.read_bytes()) == item["sha256"], file.name
        if file.suffix != ".zip":
            continue
        with zipfile.ZipFile(file) as archive:
            assert archive.testzip() is None, file.name
            names = archive.namelist()
            roots = {PurePosixPath(name).parts[0] for name in names}
            assert len(roots) == 1
            root = roots.pop() + "/"
            for name in names:
                p = PurePosixPath(name)
                assert not p.is_absolute() and ".." not in p.parts, name
                assert p.name not in (".env", "settings.ai.json", "usage.jsonl", "ui-language.json"), name
                assert not p.name.startswith(".env") or p.name == ".env.example", name
                assert p.suffix.lower() not in (".db", ".sqlite", ".sqlite3", ".pfx", ".p12", ".pem", ".key"), name
                assert p.name != "library.json" or name == root + "assets/sfx/library.json", name
            if "Portable" in file.name:
                assert root + "portable.flag" in names
                assert not any(name.startswith(root + "data/") for name in names)
                covered = set()
                for line in archive.read(root + "SHA256SUMS.txt").decode("ascii").splitlines():
                    expected, relative = line.split("  ", 1)
                    assert digest(archive.read(root + relative)) == expected, relative
                    covered.add(root + relative)
                assert covered == {name for name in names if not name.endswith("/") and name != root + "SHA256SUMS.txt"}
                assert root + "tools/MicrosoftEdgeWebview2Setup.exe" in names
                assert root + "LICENSE" in names
            else:
                package = json.loads(archive.read(root + "package-manifest.json"))
                assert package["version"] == manifest["version"]
                for relative, expected in package["files"].items():
                    assert digest(archive.read(root + relative)) == expected, relative
                assert root + "compose.yaml" in names
        print(f"Verified {file.name}")
    print(f"Release {manifest['version']}: integrity and package privacy checks passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
