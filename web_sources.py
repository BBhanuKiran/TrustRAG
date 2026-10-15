import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

import httpx


MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_WEB_RESULTS = 5
SEARCH_URL = "https://html.duckduckgo.com/html/"


class WebSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchedSource:
    content: bytes
    content_type: str
    final_url: str
    encoding: str


class _VisibleTextParser(HTMLParser):
    _ignored_tags = {
        "script", "style", "noscript", "svg", "nav", "header", "footer",
        "form", "button", "aside", "iframe", "head",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        _ = attrs
        if tag in self._ignored_tags:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if not self._ignored_depth and data.strip():
            self.text_parts.append(data.strip())


class _SearchResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._collecting = ""
        self._result_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div" and "result" in classes and self._current is None:
            self._current = {"title": "", "url": "", "text": ""}
            self._result_depth = 1
        elif tag == "div" and self._current is not None:
            self._result_depth += 1
        if self._current is None:
            return
        if tag == "a" and "result__a" in classes:
            self._current["url"] = attributes.get("href") or ""
            self._collecting = "title"
        elif tag in {"a", "td"} and "result__snippet" in classes:
            self._collecting = "text"

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag in {"a", "td"}:
            self._collecting = ""
        if tag == "div":
            self._result_depth -= 1
            if self._result_depth == 0:
                if self._current["url"] and self._current["title"]:
                    self.results.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._collecting:
            self._current[self._collecting] += data.strip() + " "


def html_to_text(content: str) -> tuple[str, str]:
    parser = _VisibleTextParser()
    parser.feed(content)
    title = " ".join(" ".join(parser.title_parts).split())
    text = " ".join(" ".join(parser.text_parts).split())
    return text, title


def _public_ip_for(hostname: str, port: int) -> str:
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as error:
        raise WebSourceError("The link host could not be resolved.") from error
    if not addresses:
        raise WebSourceError("The link host did not resolve to a public address.")

    resolved = {entry[4][0] for entry in addresses}
    if any(not ipaddress.ip_address(address).is_global for address in resolved):
        raise WebSourceError("Links to private or local network addresses are blocked.")
    return sorted(resolved)[0]


def _safe_url(url: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise WebSourceError("Enter a valid public web link.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username
        or parsed.password
        or hostname.casefold() == "localhost"
        or hostname.casefold().endswith(".localhost")
        or hostname.casefold().endswith(".local")
    ):
        raise WebSourceError("Only public HTTP and HTTPS links are supported.")

    address = _public_ip_for(hostname, port)
    if ":" in address:
        address = f"[{address}]"
    pinned_netloc = f"{address}:{port}"
    host_header = hostname.encode("idna").decode("ascii")
    if ":" in host_header:
        host_header = f"[{host_header}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if port != default_port:
        host_header = f"{host_header}:{port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    pinned_url = urlunsplit((parsed.scheme, pinned_netloc, path, parsed.query, ""))
    return pinned_url, host_header, port, hostname


def fetch_public_url(url: str) -> FetchedSource:
    pinned_url, host_header, _, hostname = _safe_url(url)
    parsed = urlsplit(url)
    extensions = (
        {"sni_hostname": hostname.encode("idna")}
        if parsed.scheme == "https"
        else {}
    )
    try:
        with httpx.Client(
            timeout=12,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            request = client.build_request(
                "GET",
                pinned_url,
                headers={
                    "Host": host_header,
                    "User-Agent": "TrustRAG/1.0 (+source reader)",
                    "Accept": (
                        "text/html, text/plain, text/markdown, application/pdf, "
                        "image/png, image/jpeg, image/webp"
                    ),
                },
                extensions=extensions,
            )
            response = client.send(request, stream=True)
            try:
                if 300 <= response.status_code < 400:
                    raise WebSourceError(
                        "This link redirects. Open the final page and add its "
                        "direct link instead."
                    )
                response.raise_for_status()
                content_type = response.headers.get(
                    "content-type",
                    "application/octet-stream",
                ).split(";", 1)[0].strip().lower()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_SOURCE_BYTES:
                        raise WebSourceError(
                            "Linked source exceeds the 20 MB limit."
                        )
                return FetchedSource(
                    content=bytes(body),
                    content_type=content_type,
                    final_url=url,
                    encoding=response.encoding or "utf-8",
                )
            finally:
                response.close()
    except WebSourceError:
        raise
    except httpx.HTTPError as error:
        raise WebSourceError(
            "The linked page could not be fetched. Check the link and try again."
        ) from error


def search_recent_web(query: str, limit: int = 3) -> list[dict[str, object]]:
    if not query.strip():
        return []
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=True,
            trust_env=True,
        ) as client:
            with client.stream(
                "GET",
                SEARCH_URL,
                params={"q": query, "kl": "us-en"},
                headers={"User-Agent": "TrustRAG/1.0 (evidence research)"},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise WebSourceError(
                            "The web search response exceeded its size limit."
                        )
                content = bytes(body).decode(
                    response.encoding or "utf-8",
                    errors="replace",
                )
    except WebSourceError:
        raise
    except httpx.HTTPError as error:
        raise WebSourceError(
            "Fresh web search is temporarily unavailable. Try again or turn off "
            "web search to use only your library."
        ) from error

    parser = _SearchResultsParser()
    parser.feed(content)
    results: list[dict[str, str | None]] = []
    for item in parser.results:
        raw_url = item["url"].strip()
        if raw_url.startswith("//"):
            raw_url = f"https:{raw_url}"
        if raw_url.startswith("/l/?"):
            raw_url = f"https://duckduckgo.com{raw_url}"
        query_parameters = parse_qs(urlsplit(raw_url).query)
        if "uddg" in query_parameters:
            raw_url = query_parameters["uddg"][0]
        if urlsplit(raw_url).scheme not in {"http", "https"}:
            continue
        title = " ".join(item["title"].split())
        snippet = " ".join(item["text"].split())
        excerpt = f"{title}. {snippet}".strip()
        if excerpt and len(excerpt) > len(title) + 1:
            results.append({
                "source": title[:200],
                "url": raw_url,
                "page": None,
                "text": excerpt[:2000],
            })
        if len(results) >= min(max(limit, 1), MAX_WEB_RESULTS):
            break
    return results
