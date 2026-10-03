"""URL inputs."""

import functools
import http.server
import re
import ssl
import threading
import urllib.error
from pathlib import Path

import pytest
from cli_helpers import run

import pdfexorcist
import pdfexorcist.fetch as fetch
from pdfexorcist.fetch import TWEET, _file_name, direct, download, is_url, tweet_token


class _Handler(http.server.SimpleHTTPRequestHandler):
    """The test folder, plus /named (the server names the file) and /flaky.pdf (503 once)."""

    flaky_calls = 0

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/named":
            body = (Path(self.directory) / "states.pdf").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="Annual Report.pdf"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/flaky.pdf":
            type(self).flaky_calls += 1
            if type(self).flaky_calls == 1:
                self.send_error(503)
                return
            self.path = "/states.pdf"
        super().do_GET()


@pytest.fixture
def server(states_pdf):
    """Serves states.pdf, report (no suffix), HTML pages, /named and /flaky.pdf."""
    folder = states_pdf.parent
    (folder / "report").write_bytes(states_pdf.read_bytes())
    (folder / "page.html").write_text("<html>sign in</html>")
    (folder / "landing.html").write_text('<p>Report</p><a href="states.pdf">Download</a>')
    (folder / "refresh.html").write_text(
        '<meta http-equiv="refresh" content="0; url=/landing.html">'
    )
    _Handler.flaky_calls = 0
    handler = functools.partial(_Handler, directory=str(folder))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_is_url():
    assert is_url("https://x.org/a.pdf") and is_url("HTTP://x.org/a")
    assert not is_url("a.pdf") and not is_url(None)


STAMP = r"_\d{8}-\d{6}(-\d+)?"  # the download time, and a counter within one second


def test_download_names_and_reuse(server, tmp_path):
    """Pin downloaded filenames, cache reuse, and changed-file handling."""
    out = tmp_path / "dl"
    first = download(f"{server}/states.pdf", out)
    assert first.name == "states.pdf" and download(f"{server}/states.pdf", out) == first
    a = download(f"{server}/report", out)
    assert re.fullmatch(f"127.0.0.1_report{STAMP}.pdf", a.name)
    assert download(f"{server}/report", out) == a  # unchanged: the earlier file
    served = tmp_path / "report"
    served.write_bytes(served.read_bytes() + b"%changed")
    b = download(f"{server}/report", out)
    assert b != a and b.read_bytes().endswith(b"%changed")
    with pytest.raises(ValueError, match="text/html"):
        download(f"{server}/page.html", out)
    assert not (out / "page.html").exists()


def test_page_download(server, tmp_path):
    assert re.fullmatch(f"states{STAMP}.pdf", download(f"{server}/landing.html", tmp_path).name)
    assert re.fullmatch(f"states{STAMP}.pdf", download(f"{server}/refresh.html", tmp_path).name)


def test_file_names_and_share_links():
    assert _file_name("https://x.in/downloadFile.php?link=A+B.pdf&path=c%2F") == "A B.pdf"

    assert direct("https://drive.google.com/file/d/AbC_1/view?usp=sharing") == (
        "https://drive.google.com/uc?export=download&id=AbC_1"
    )
    assert (
        direct("https://www.dropbox.com/s/k/r.pdf?dl=0") == "https://www.dropbox.com/s/k/r.pdf?dl=1"
    )
    assert direct("https://github.com/u/r/blob/main/t.pdf") == (
        "https://raw.githubusercontent.com/u/r/main/t.pdf"
    )


def test_tweet_links():
    m = TWEET.match("https://x.com/mybmc/status/2106224821864698086/photo/2")
    assert m and m.groups() == ("2106224821864698086", "2")
    assert TWEET.match("https://twitter.com/mybmc/status/1")
    assert tweet_token("2106224821864698086") == "53sweybw98v14e"  # what the embed sends


def test_cli_download(server, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    r = run(["extract", f"{server}/report", "-q"])
    assert r.exit_code == 0, r.output
    pdf = next(work.glob("127.0.0.1_report_*.pdf"))
    assert pdf.with_suffix(".csv").exists()
    assert run([f"{server}/page.html"]).exit_code != 0


def test_library_extract_takes_a_link(server, tmp_path, monkeypatch):
    monkeypatch.setenv("PDFEXORCIST_CACHE", str(tmp_path / "cache"))
    res = pdfexorcist.extract(f"{server}/states.pdf")
    assert (res.status == "verified").sum() == 9


def test_server_name(server, tmp_path):
    path = download(f"{server}/named", tmp_path)
    assert re.fullmatch(f"Annual Report{STAMP}.pdf", path.name)


def test_a_server_error_is_retried(server, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    assert download(f"{server}/flaky.pdf", tmp_path).name == "flaky.pdf"
    assert _Handler.flaky_calls == 2


def test_default_cache(server, tmp_path, monkeypatch):
    monkeypatch.setenv("PDFEXORCIST_CACHE", str(tmp_path / "cache"))
    assert fetch.cache_root() == tmp_path / "cache"
    path = download(f"{server}/states.pdf")
    assert path.parent.parent == tmp_path / "cache" / "downloads"


def test_unique_name(tmp_path):
    (tmp_path / "a.pdf").touch()
    (tmp_path / "a-2.pdf").touch()
    assert fetch._unique(tmp_path, "a", ".pdf") == tmp_path / "a-3.pdf"
    assert fetch._unique(tmp_path, "b", ".pdf") == tmp_path / "b.pdf"


def test_url_name():
    url = "https://www.mwrdpravah.in/damsafety/control/pdfLatestReportEng"
    assert fetch._url_slug(url) == "mwrdpravah.in_damsafety_control_pdfLatestReportEng"
    assert _file_name(url) is None


def test_tweet_cache(server, tmp_path, monkeypatch):
    asked = []

    def photo(opener, tweet_id, n):
        asked.append((tweet_id, n))
        return f"{server}/states.pdf"

    monkeypatch.setattr(fetch, "_tweet_image", photo)
    path = download("https://x.com/someone/status/123/photo/2", tmp_path)
    assert path.name == "tweet_123_2.jpg" and asked == [("123", 2)]
    assert download("https://x.com/someone/status/123/photo/2", tmp_path) == path
    assert asked == [("123", 2)]  # the second call read nothing


@pytest.mark.parametrize(
    "page, link",
    [
        (
            '<form id="download-form" action="https://drive.usercontent.google.com/download">'
            '<input type="hidden" name="id" value="X">'
            '<input type="hidden" name="confirm" value="t">'
            "</form>",
            "https://drive.usercontent.google.com/download?id=X&confirm=t",
        ),
        ('<embed src="/files/report.pdf">', "https://example.org/files/report.pdf"),
        ('<meta http-equiv="refresh" content="0; url=/go">', "https://example.org/go"),
        (
            '<a href="notes.html">notes</a><a href="data.pdf">PDF</a>',
            "https://example.org/a/data.pdf",
        ),
        ("<p>no file here</p>", None),
    ],
)
def test_a_page_leads_to_its_file(page, link):
    assert fetch._next_link(page, "https://example.org/a/page.html") == link


def test_intermediate_cert(server, tmp_path, monkeypatch):
    calls = []
    body = (tmp_path / "states.pdf").read_bytes()

    def get(opener, url):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get issuer"))
        return body, "application/pdf", "", url

    hosts = []
    monkeypatch.setattr(fetch, "_get", get)
    monkeypatch.setattr(
        fetch,
        "_ssl_context",
        lambda h, p: hosts.append((h, p)) or ssl.create_default_context(),
    )
    path = download("https://example.org/report.pdf", tmp_path / "dl")
    assert path.read_bytes() == body and hosts == [("example.org", 443)] and len(calls) == 2
