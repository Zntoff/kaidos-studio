"""Coverage contracts for shared UI copy. No generation-language translation or remote calls."""
import csv
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "clipper/web/static"


def normalize(value):
    return " ".join(unicodedata.normalize("NFC", value).replace("−", "-").split())


def catalog():
    return list(csv.reader((STATIC / "locales.tsv").open(encoding="utf-8"), delimiter="\t"))


def test_every_ui_message_has_five_translations_and_matching_placeholders():
    seen = set()
    for index, row in enumerate(catalog(), 1):
        assert len(row) == 5 and all(x.strip() for x in row), f"Incomplete row {index}"
        key = normalize(row[0])
        assert key not in seen, f"Duplicate locale source: {key}"
        seen.add(key)
        expected = sorted(re.findall(r"\{\d+\}", row[0]))
        for value in row[1:]:
            assert sorted(re.findall(r"\{\d+\}", value)) == expected, f"Missing placeholder in {row[0]}"


def test_static_html_labels_attributes_and_catalogs_are_localized():
    rows = catalog()
    keys = {normalize(row[i]) for row in rows for i in (0, 1)}
    neutral = set(json.loads((STATIC / "locales-neutral.json").read_text(encoding="utf-8"))["terms"])
    patterns = [re.compile("^" + re.sub(r"\\\{\d+\\\}", ".*?", re.escape(normalize(row[i]))) + "$") for row in rows for i in (0, 1) if "{0}" in row[i]]
    def known(value):
        value = normalize(value)
        if not any(c.isalpha() for c in value) or value in keys or value in neutral:
            return True
        if value.startswith(("http://", "https://")) or re.fullmatch(r"[\d.,%\s]+(?:fps|s|ms|LUFS|px|MB|BPM)", value):
            return True
        return any(p.fullmatch(value) for p in patterns)
    missing = set()
    for file in [*STATIC.glob("*.js"), STATIC / "index.html"]:
        if file.name == "i18n.js":
            continue
        source = file.read_text(encoding="utf-8")
        literals = re.findall(r'(?:>|\})([^<>{}\n`]+)<', source)
        literals += re.findall(r'(?:title|placeholder|aria-label)="([^"$]+)"', source)
        for value in literals:
            value = value.strip()
            # Ignore JS comparisons accidentally matched as HTML and literal entity padding.
            if len(value)<=1 or any(c in value for c in "'\\=;?[]") or "&&" in value or value in ("&nbsp;", "tw(l, font, size)"):
                continue
            if not known(value):
                missing.add(f"{file.name}: {value}")
    def visit(value):
        if isinstance(value, dict):
            for k, child in value.items():
                if k in ("label", "desc", "description", "note") and isinstance(child, str):
                    if not known(child): missing.add(child)
                else: visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    for file in (ROOT / "assets/studio/catalog.json", ROOT / "assets/sfx/library.json", ROOT / "config/providers.json"):
        visit(json.loads(file.read_text(encoding="utf-8")))
    assert not missing, "Untranslated application copy:\n" + "\n".join(sorted(missing))
