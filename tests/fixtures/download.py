"""Download the source PDFs of the test fixtures, from the publisher or the Internet Archive.

Each manifest's source_url (or url) is saved as <out>/<dataset>/<file name>. A download
that is not a PDF comes from the Internet Archive's newest copy.

    python tests/fixtures/download.py                      # every dataset, into sources/
    python tests/fixtures/download.py tb_report kerala_dhs -o /tmp/pdfs
    python tests/fixtures/download.py --list               # print the URLs only
"""

import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

FIXTURES = Path(__file__).parent
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"
ARCHIVE = "https://web.archive.org"
TRIES = 4  # the Internet Archive answers 429 when asked too fast
URL_COLUMNS = ("source_url", "url", "source")  # older manifests name only a file: skipped


def sources(datasets: list[str]) -> dict[str, set[str]]:
    """Each dataset's source URLs, from its manifest."""
    out: dict[str, set[str]] = {}
    for manifest in sorted(FIXTURES.glob("*/manifest.csv")):
        name = manifest.parent.name
        if datasets and name not in datasets:
            continue
        with manifest.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                text = " ".join(row.get(c) or "" for c in URL_COLUMNS)
                for url in re.findall(r"https?://\S+", text):
                    out.setdefault(name, set()).add(url.rstrip(".,;"))
    return out


def _get(url: str) -> bytes:
    """The body at url; retries with a growing wait on errors such as 429."""
    url = urllib.parse.quote(url, safe=":/?&=%#~+,;@!$'()*[]")  # "N°26" in an INSP link
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "*/*"})
    for attempt in range(1, TRIES):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:  # noqa: PERF203 (a retry loop)
            logger.warning("%s: %s, trying again", url, e)
            time.sleep(15 * attempt)
    with urllib.request.urlopen(req, timeout=300) as r:  # the last try raises
        return r.read()


def _archived(url: str) -> str | None:
    """The raw URL of the Internet Archive's newest good copy of url, or None."""
    if url.startswith(ARCHIVE):
        return None
    query = urllib.parse.urlencode(
        {"url": url, "filter": "statuscode:200", "output": "json", "limit": "-1"}
    )
    rows = json.loads(_get(f"{ARCHIVE}/cdx/search/cdx?{query}") or b"[]")
    if len(rows) < 2:  # the first row names the fields
        return None
    timestamp, original = rows[-1][1], rows[-1][2]
    return f"{ARCHIVE}/web/{timestamp}id_/{original}"


def _file_name(url: str) -> str:
    """A file name for url: the last path part, or the filepath= query of HMIS links."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.parse_qs(parts.query).get("filepath", [parts.path])[0]
    name = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1]) or "download"
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def download(url: str, dest: Path) -> str:
    """Save url's PDF to dest, from the archive when the site fails; return where it came from."""
    try:
        data = _get(url)
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning("%s: %s", url, e)
        data = b""
    where = "site"
    if not data.startswith(b"%PDF"):
        archived = _archived(url)
        if archived is None:
            raise FileNotFoundError(f"{url}: not a PDF, and no copy in the Internet Archive")
        data, where = _get(archived), archived
        if not data.startswith(b"%PDF"):
            raise FileNotFoundError(f"{archived}: not a PDF")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return where


def main(argv: list[str] | None = None) -> int:
    """Download every source PDF of the named datasets (default: all); return the failures."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("datasets", nargs="*", help="fixture folders, e.g. tb_report (default: all)")
    p.add_argument("-o", "--out", type=Path, default=Path("sources"), help="folder to save into")
    p.add_argument("--list", action="store_true", help="print the URLs and download nothing")
    p.add_argument("--force", action="store_true", help="download files already saved")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    failed = 0
    for name, urls in sources(args.datasets).items():
        for url in sorted(urls):
            dest = args.out / name / _file_name(url)
            if args.list:
                print(f"{name}\t{url}")
                continue
            if dest.exists() and not args.force:
                logger.info("have %s", dest)
                continue
            try:
                where = download(url, dest)
            except (OSError, ValueError) as e:
                logger.error("failed %s: %s", url, e)
                failed += 1
                continue
            logger.info("saved %s (%s)", dest, where)
    return failed


if __name__ == "__main__":
    sys.exit(min(main(), 1))
