#!/usr/bin/env bash
# PDFium chromium/7999 as wasm: the build pypdfium2 5.13 bundles on desktop.

set -euo pipefail

SHA256=574e5470cb56b22e638993ad5a39f83fef91eaced2a1acbfe3bb9a4738db5f60
OUT=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
curl -sfLo "$WORK/pdfium-wasm.tgz" \
  https://github.com/bblanchon/pdfium-binaries/releases/download/chromium/7999/pdfium-wasm.tgz
echo "$SHA256  $WORK/pdfium-wasm.tgz" | shasum -a 256 -c -
tar xzf "$WORK/pdfium-wasm.tgz" -C "$WORK"
cp "$WORK"/lib/pdfium.wasm "$OUT"/
cp "$WORK"/lib/pdfium.js "$OUT"/pdfium.cjs  # a classic script
cp "$WORK"/LICENSE "$OUT"/pdfium.LICENSE
