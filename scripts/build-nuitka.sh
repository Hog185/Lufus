#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"
OUTPUT_DIR="${OUTPUT_DIR:-dist/nuitka}"
OUTPUT_NAME="${OUTPUT_NAME:-Lufus-x86_64}"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install --upgrade nuitka ordered-set zstandard
"$PYTHON" -m pip install -e .

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

"$PYTHON" -m nuitka \
    --standalone \
    --onefile \
    --assume-yes-for-downloads \
    --enable-plugin=pyqt6 \
    --include-package=lufus \
    --include-package-data=lufus \
    --include-data-dir=src/lufus/gui/assets=lufus/gui/assets \
    --include-data-dir=src/lufus/gui/languages=lufus/gui/languages \
    --include-data-dir=src/lufus/gui/themes=lufus/gui/themes \
    --include-data-file=src/lufus/writing/grub.cfg=lufus/writing/grub.cfg \
    --include-data-file=src/lufus/writing/uefi-ntfs.img=lufus/writing/uefi-ntfs.img \
    --output-dir="$OUTPUT_DIR" \
    --output-filename="$OUTPUT_NAME" \
    src/lufus/__main__.py

chmod +x "$OUTPUT_DIR/$OUTPUT_NAME"
sha256sum "$OUTPUT_DIR/$OUTPUT_NAME" > "$OUTPUT_DIR/$OUTPUT_NAME.sha256"

echo "Nuitka build created: $OUTPUT_DIR/$OUTPUT_NAME"
