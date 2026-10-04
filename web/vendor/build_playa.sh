#!/usr/bin/env bash
# playa-pdf (camelot's parser) as a pure-Python wheel; PyPI has only mypyc builds.

set -euo pipefail

VERSION=1.1.0
URL=https://files.pythonhosted.org/packages/af/d2/9575801a5e41fdffbac0fc356a7aae462e11f58473b3e78070185a9e7ced/playa_pdf-1.1.0.tar.gz
SHA256=6414a0779fdcc96284588767738c2bd71ed3aa65a1a8fa647a4ab09dce4ff017
OUT=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
cd "$WORK"
curl -sfLo sdist.tar.gz "$URL"
echo "$SHA256  sdist.tar.gz" | shasum -a 256 -c -
tar xzf sdist.tar.gz
# uv build writes a .gitignore of "*" into its output folder, so build elsewhere
SETUPTOOLS_SCM_PRETEND_VERSION=$VERSION uv build --wheel -o dist playa_pdf-$VERSION
cp dist/*.whl "$OUT"/
