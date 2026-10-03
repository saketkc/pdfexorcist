#!/usr/bin/env bash
# Smoke-test an installed pdfexorcist: cli_smoke.sh <venv> <fixture.pdf>
# Runs from outside the source tree so the installed package, not ./pdfexorcist, is imported.
set -euo pipefail
unset FORCE_COLOR # plain help text to search below
export NO_COLOR=1 COLUMNS=120

venv=$1
pdf=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
if [ -d "$venv/Scripts" ]; then bin=$venv/Scripts; else bin=$venv/bin; fi
work=$(mktemp -d)
cd "$work"

echo "::group::import"
"$bin/python" -c "import pdfexorcist, sys; print(pdfexorcist.__file__); assert 'site-packages' in pdfexorcist.__file__"
echo "::endgroup::"

echo "::group::pdfexorcist --help"
help=$("$bin/pdfexorcist" --help)
echo "$help"
echo "::endgroup::"

echo "::group::python -m pdfexorcist --help"
"$bin/python" -m pdfexorcist --help
echo "::endgroup::"

echo "::group::extract ${pdf##*/}"
# subcommand CLI: argparse lists "{extract,...}", typer/click a line starting "extract"
plain=$("$bin/python" -c 'import re, sys; sys.stdout.write(re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read()))' <<<"$help")
if grep -qE '\{([^}]*,)?extract(,[^}]*)?\}|^[[:space:]│|]*extract([[:space:]]|$)' <<<"$plain"; then
  "$bin/pdfexorcist" extract "$pdf" -o out # subcommand CLI
else
  "$bin/pdfexorcist" "$pdf" -o out # single-command CLI
fi
echo "::endgroup::"

ls -l out
n=$(find out -name '*.csv' -size +0 | wc -l)
if [ "$n" -lt 1 ]; then
  echo "::error::pdfexorcist wrote no CSV output"
  exit 1
fi
echo "OK: $n non-empty CSV files"
