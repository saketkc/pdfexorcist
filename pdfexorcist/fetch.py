"""Download inputs from URLs."""

import functools
import glob
import hashlib
import html.parser
import http.cookiejar
import json
import logging
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .pages import INPUT_SUFFIXES

logger = logging.getLogger(__name__)

MAGIC = {b"%PDF": ".pdf", b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"II*\x00": ".tif",
         b"MM\x00*": ".tif", b"BM": ".bmp", b"RIFF": ".webp"}  # fmt: skip
# some servers refuse clients that do not look like a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/pdf,image/*,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
}
# share and view links -> the file itself
DIRECT = [
    (r"https://drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:.*&)?id=)([\w-]+).*",
     r"https://drive.google.com/uc?export=download&id=\1"),
    (r"(https://(?:www\.)?dropbox\.com/.*?)([?&])dl=0(.*)", r"\1\2dl=1\3"),
    (r"https://github\.com/([^/]+/[^/]+)/blob/(.*)", r"https://raw.githubusercontent.com/\1/\2"),
]  # fmt: skip
TRIES = 3
TWEET = re.compile(
    r"https://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status/(\d+)(?:/photo/(\d))?"
)


def cache_root() -> Path:
    """Cache root, defaulting to ~/.cache/pdfexorcist."""
    return Path(os.environ.get("PDFEXORCIST_CACHE", Path.home() / ".cache" / "pdfexorcist"))


def is_url(text: object) -> bool:
    """Whether text is an http(s) URL."""
    return isinstance(text, str) and bool(re.match(r"https?://", text, re.I))


def download(url: str, folder: Path | None = None) -> Path:
    """Download url into folder or the cache."""
    if folder is None:
        folder = cache_root() / "downloads" / hashlib.sha1(url.encode()).hexdigest()[:12]
    url = direct(url)
    tweet = TWEET.match(url)
    photo = int(tweet[2] or 1) if tweet else 0
    named = f"tweet_{tweet[1]}_{photo}.jpg" if tweet else _file_name(url)  # photo names are opaque
    if named and (folder / named).exists():
        logger.info("using %s, downloaded earlier", folder / named)
        return folder / named
    opener = _opener()
    if tweet:
        url = _tweet_image(opener, tweet[1], photo)
    try:
        data, ctype, sent, final = _get(opener, url)
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
        parts = urllib.parse.urlsplit(url)  # the server left out part of its chain
        opener = _opener(_ssl_context(parts.hostname or "", parts.port or 443))
        data, ctype, sent, final = _get(opener, url)
    for _ in range(3):  # a landing page, Drive's virus-scan page, a redirect page
        if _suffix(data) or "html" not in ctype:
            break
        nxt = _next_link(data.decode("utf-8", "replace"), final)
        if nxt is None:
            break
        data, ctype, sent, final = _get(opener, nxt)
    suffix = _suffix(data)
    if suffix is None:
        raise ValueError(f"the server sent {ctype}, not a PDF or an image")
    folder.mkdir(parents=True, exist_ok=True)
    if named:
        path = folder / named
    else:
        base = Path(sent).name if sent else _file_name(final) or _url_slug(url)
        stem = Path(base).stem if Path(base).suffix.lower() in INPUT_SUFFIXES else base
        earlier = sorted(
            folder.glob(f"{glob.escape(stem)}_*{suffix}"), key=lambda p: p.stat().st_mtime
        )
        if earlier and earlier[-1].read_bytes() == data:  # unchanged since the last download
            return earlier[-1]
        path = _unique(folder, f"{stem}_{time.strftime('%Y%m%d-%H%M%S')}", suffix)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # no half-written file under the final name
    return path


def direct(url: str) -> str:
    """Rewrite supported share links to downloads."""
    for pattern, repl in DIRECT:
        url = re.sub(pattern, repl, url)
    return url


def _get(opener: urllib.request.OpenerDirector, url: str) -> tuple[bytes, str, str, str]:
    """Get a URL with retries for transient failures."""
    parts = urllib.parse.urlsplit(url)
    headers = {**HEADERS, "Referer": f"{parts.scheme}://{parts.netloc}/"}
    for attempt in range(TRIES):
        try:
            logger.info("downloading %s", url)
            with opener.open(urllib.request.Request(url, headers=headers), timeout=120) as r:
                name = r.headers.get_filename() or ""
                return r.read(), r.headers.get_content_type(), name, r.geturl()
        except urllib.error.HTTPError as e:
            if (e.code != 429 and e.code < 500) or attempt == TRIES - 1:
                raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == TRIES - 1 or isinstance(
                getattr(e, "reason", None), ssl.SSLCertVerificationError
            ):
                raise
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _opener(context: ssl.SSLContext | None = None) -> urllib.request.OpenerDirector:
    """Build an opener that retains download cookies."""
    handlers: list = [urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


@functools.lru_cache(maxsize=16)
def _ssl_context(host: str, port: int) -> ssl.SSLContext:
    """Build verification context with a missing intermediate certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import AuthorityInformationAccessOID

    # unverified, only to read where the issuer certificate is published
    leaf = x509.load_pem_x509_certificate(ssl.get_server_certificate((host, port)).encode())
    aia = leaf.extensions.get_extension_for_class(x509.AuthorityInformationAccess)
    issuer_url = next(
        d.access_location.value
        for d in aia.value
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS
    )
    raw = urllib.request.urlopen(issuer_url, timeout=30).read()
    issuer = (
        x509.load_pem_x509_certificate(raw)
        if raw.startswith(b"-----")
        else x509.load_der_x509_certificate(raw)
    )
    ctx = ssl.create_default_context()
    # a fetched intermediate helps build the chain but is never itself a trust anchor
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    ctx.load_verify_locations(cadata=issuer.public_bytes(Encoding.PEM).decode())
    return ctx


def _tweet_image(opener: urllib.request.OpenerDirector, tweet_id: str, n: int) -> str:
    """Get a tweet photo URL by 1-based position."""
    api = (
        f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}"
        f"&token={tweet_token(tweet_id)}&lang=en"
    )
    tweet = json.loads(_get(opener, api)[0])
    photos = [
        m["media_url_https"] for m in tweet.get("mediaDetails", []) if m.get("type") == "photo"
    ]
    if len(photos) < n:
        raise ValueError(f"the tweet has {len(photos)} photo(s), none numbered {n}")
    return f"{photos[n - 1]}?name=orig"  # the full-size upload


def tweet_token(tweet_id: str) -> str:
    """Derive the token required by embedded tweets."""
    x = int(tweet_id) / 1e15 * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    whole, frac, out = int(x), x - int(x), ""
    while whole:
        whole, d = divmod(whole, 36)
        out = digits[d] + out
    out += "."
    for _ in range(11):
        frac *= 36
        out += digits[int(frac)]
        frac -= int(frac)
    return re.sub(r"0+|\.", "", out)


def _suffix(data: bytes) -> str | None:
    """Identify a PDF or image by magic bytes."""
    return next((s for magic, s in MAGIC.items() if data.startswith(magic)), None)


def _file_name(url: str) -> str | None:
    """Find an input filename in a URL."""
    parts = urllib.parse.urlsplit(url)
    name = Path(urllib.parse.unquote(parts.path)).name
    if Path(name).suffix.lower() in INPUT_SUFFIXES:
        return name
    for values in urllib.parse.parse_qs(parts.query).values():
        for v in values:
            if Path(v).suffix.lower() in INPUT_SUFFIXES:
                return Path(v).name
    return None


def _url_slug(url: str) -> str:
    """Build a filename slug from a URL."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "download").removeprefix("www.")
    words = [host, *(w for w in urllib.parse.unquote(parts.path).split("/") if w)]
    return re.sub(r"[^\w.-]+", "-", "_".join(words))[:120]


def _unique(folder: Path, stem: str, suffix: str) -> Path:
    """Choose an unused path with stem and suffix."""
    path, n = folder / f"{stem}{suffix}", 1
    while path.exists():
        n += 1
        path = folder / f"{stem}-{n}{suffix}"
    return path


class _Links(html.parser.HTMLParser):
    """Collect file links from a download page."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[int, str]] = []
        self._form: list | None = None  # [action, method, {name: value}]

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: v or "" for k, v in attrs}
        src = a.get("src") or a.get("data", "")
        if tag == "form" and "download" in (a.get("id", "") + a.get("action", "")).lower():
            self._form = [a.get("action", ""), a.get("method", "get").lower(), {}]
        elif tag == "input" and self._form is not None and a.get("name"):
            self._form[2][a["name"]] = a.get("value", "")
        elif tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            if m := re.search(r"url\s*=\s*['\"]?([^'\";]+)", a.get("content", ""), re.I):
                self.found.append((1, m.group(1)))
        elif tag in ("iframe", "embed", "object") and _looks_like_file(src):
            self.found.append((2, src))
        elif tag == "a" and _looks_like_file(a.get("href")):
            self.found.append((3, a["href"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._form is not None:
            action, method, fields = self._form
            if method == "get":
                sep = "&" if "?" in action else "?"
                self.found.append((0, f"{action}{sep}{urllib.parse.urlencode(fields)}"))
            self._form = None


def _looks_like_file(href: str | None) -> bool:
    path = urllib.parse.urlsplit(href or "").path.lower()
    return any(path.endswith(s) for s in INPUT_SUFFIXES)


def _next_link(page: str, base: str) -> str | None:
    """Find a download link in an HTML page."""
    p = _Links()
    p.feed(page)
    return urllib.parse.urljoin(base, min(p.found)[1]) if p.found else None
