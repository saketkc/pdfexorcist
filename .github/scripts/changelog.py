"""Changelog edits for the release workflows."""

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

HEADING = re.compile(r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\S+))?\s*$", re.M)
LINK = re.compile(r"^\[[^\]]+\]: \S+\s*$")


def sections(text: str) -> list[tuple[str, int, int]]:
    """(name, start of heading, end of section) for every ## [name] heading."""
    found = list(HEADING.finditer(text))
    ends = [m.start() for m in found[1:]] + [len(text)]
    return [(m["name"], m.start(), end) for m, end in zip(found, ends, strict=True)]


def body(text: str, name: str) -> str:
    """The entries of one section, without its heading or trailing link definitions."""
    for n, start, end in sections(text):
        if n == name:
            lines = text[start:end].splitlines()[1:]
            return "\n".join(ln for ln in lines if not LINK.match(ln)).strip()
    raise SystemExit(f"CHANGELOG.md has no [{name}] section")


def repo_url(text: str) -> str:
    """https://github.com/OWNER/REPO, from the environment or the existing links."""
    if os.environ.get("GITHUB_REPOSITORY"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        return f"{server}/{os.environ['GITHUB_REPOSITORY']}"
    m = re.search(r"^\[[^\]]+\]: (https://[^/\s]+/[^/\s]+/[^/\s]+)/", text, re.M)
    if not m:
        raise SystemExit("set GITHUB_REPOSITORY=owner/repo to write the comparison links")
    return m.group(1)


def links(text: str, url: str) -> str:
    """Link definitions for every heading: each version compared with the one before."""
    names = [n for n, _, _ in sections(text)]
    versions = [n for n in names if n != "Unreleased"]
    out = []
    if "Unreleased" in names:
        base = f"compare/v{versions[0]}...HEAD" if versions else "commits/HEAD"
        out.append(f"[Unreleased]: {url}/{base}")
    for newer, older in zip(versions, [*versions[1:], None], strict=True):
        tail = f"compare/v{older}...v{newer}" if older else f"releases/tag/v{newer}"
        out.append(f"[{newer}]: {url}/{tail}")
    return "\n".join(out)


def release(path: Path, version: str, today: str) -> None:
    text = path.read_text(encoding="utf-8")
    names = [n for n, _, _ in sections(text)]
    if version in names:
        raise SystemExit(f"CHANGELOG.md already has a [{version}] section")
    entries = body(text, "Unreleased")
    if not entries:
        raise SystemExit("CHANGELOG.md: nothing under [Unreleased]; add the changes first")
    url = repo_url(text)
    kept = [ln for ln in text.rstrip().splitlines() if not LINK.match(ln)]
    text = "\n".join(kept).rstrip() + "\n"
    start, end = next((s, e) for n, s, e in sections(text) if n == "Unreleased")
    new = f"## [Unreleased]\n\n## [{version}] - {today}\n\n{entries}\n\n"
    text = text[:start] + new + text[end:].lstrip("\n")
    path.write_text(text.rstrip() + "\n\n" + links(text, url) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("action", choices=["release", "notes"])
    ap.add_argument("version", help="e.g. 1.2.0 or 1.2.0rc1 (no leading v)")
    ap.add_argument("--file", type=Path, default=Path("CHANGELOG.md"))
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="release date")
    a = ap.parse_args()
    version = a.version.removeprefix("v")
    if a.action == "release":
        release(a.file, version, a.date)
        print(f"CHANGELOG.md: [Unreleased] -> [{version}] - {a.date}")
    else:
        print(body(a.file.read_text(encoding="utf-8"), version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
