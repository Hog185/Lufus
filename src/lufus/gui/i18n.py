import csv
from pathlib import Path
from lufus.gui.constants import _find_resource_dir


def load_translations(language="English"):
    # load language csv files for localization
    lang_dir = _find_resource_dir("languages")
    t = {}
    if lang_dir is None:
        return t
    lang_file = lang_dir / f"{language}.csv"
    if lang_file.exists():
        # utf-8-sig strips BOM that some editors insert before the first byte.
        # Graceful row handling: skip malformed rows (no key column, empty key).
        with open(lang_file, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                key = row.get("key", "").strip()
                value = row.get("value", "")
                if key:
                    t[key] = value
    return t
