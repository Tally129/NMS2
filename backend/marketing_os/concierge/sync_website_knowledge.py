"""Build the NMS Concierge public website knowledge snapshot.

Reads:
    https://preview.natmedsol.org/sitemap.xml

Fetches the corresponding preview pages while preserving each page's
public natmedsol.com canonical URL.

No database writes.
No LLM calls.
No patient data.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    Request,
    urlopen,
)

from marketing_os.concierge.knowledge import (
    KNOWLEDGE_PATH,
    normalize_text,
    validate_public_url,
    validate_source_url,
)


SITEMAP_URL = (
    "https://preview.natmedsol.org/sitemap.xml"
)

PREVIEW_BASE = (
    "https://preview.natmedsol.org"
)

USER_AGENT = (
    "NMS-MarketingOS-ConciergeKnowledge/1.0"
)

REQUEST_TIMEOUT = 15

MAX_PAGE_BYTES = 2 * 1024 * 1024

MAX_PARAGRAPHS = 120

MAX_LIST_ITEMS = 100

MAX_HEADINGS = 60

SKIP_PATHS = {
    "/contact-submit/",
    "/contact-success/",
    "/contact-us/",
}

SKIP_PREFIXES = (
    "/api/",
)


class PublicPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.title_parts: list[str] = []
        self.description = ""
        self.canonical = ""

        self.h1_parts: list[str] = []
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self.list_items: list[str] = []

        self._capture: str | None = None
        self._buffer: list[str] = []

        self._inside_main = 0
        self._saw_main = False

        self._ignore_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        attrs_dict = dict(attrs)

        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
        }:
            self._ignore_depth += 1
            return

        if self._ignore_depth:
            return

        if tag == "main":
            self._inside_main += 1
            self._saw_main = True

        if tag == "meta":
            name = (
                attrs_dict.get("name")
                or ""
            ).lower()

            if name == "description":
                self.description = normalize_text(
                    attrs_dict.get(
                        "content"
                    )
                )

        if tag == "link":
            rel = (
                attrs_dict.get("rel")
                or ""
            ).lower()

            if "canonical" in rel:
                self.canonical = normalize_text(
                    attrs_dict.get(
                        "href"
                    )
                )

        if tag in {
            "title",
            "h1",
            "h2",
            "h3",
            "p",
            "li",
        }:
            self._capture = tag
            self._buffer = []

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
        }:
            if self._ignore_depth:
                self._ignore_depth -= 1
            return

        if self._ignore_depth:
            return

        if (
            self._capture == tag
        ):
            value = normalize_text(
                " ".join(
                    self._buffer
                )
            )

            in_content = (
                self._inside_main > 0
                or not self._saw_main
            )

            if value:
                if tag == "title":
                    self.title_parts.append(
                        value
                    )

                elif tag == "h1" and in_content:
                    self.h1_parts.append(
                        value
                    )
                    self.headings.append(
                        value
                    )

                elif (
                    tag in {"h2", "h3"}
                    and in_content
                ):
                    self.headings.append(
                        value
                    )

                elif (
                    tag == "p"
                    and in_content
                ):
                    self.paragraphs.append(
                        value
                    )

                elif (
                    tag == "li"
                    and in_content
                ):
                    self.list_items.append(
                        value
                    )

            self._capture = None
            self._buffer = []

        if (
            tag == "main"
            and self._inside_main
        ):
            self._inside_main -= 1

    def handle_data(
        self,
        data: str,
    ) -> None:
        if (
            self._ignore_depth
            or not self._capture
        ):
            return

        self._buffer.append(data)


def fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept":
                "text/html,application/xml,text/xml",
        },
    )

    with urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        content_type = (
            response.headers.get(
                "Content-Type",
                "",
            )
        )

        raw = response.read(
            MAX_PAGE_BYTES + 1
        )

    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError(
            f"Response too large: {url}"
        )

    charset = "utf-8"

    match = re.search(
        r"charset=([A-Za-z0-9._-]+)",
        content_type,
        re.I,
    )

    if match:
        charset = match.group(1)

    return raw.decode(
        charset,
        errors="replace",
    )


def sitemap_urls(xml_text: str) -> list[str]:
    values = re.findall(
        r"<loc>\s*(.*?)\s*</loc>",
        xml_text,
        flags=re.I | re.S,
    )

    urls: list[str] = []

    for raw in values:
        url = html.unescape(
            normalize_text(raw)
        )

        if not url:
            continue

        validate_public_url(url)

        parsed = urlparse(url)

        path = parsed.path or "/"

        if path in SKIP_PATHS:
            continue

        if any(
            path.startswith(prefix)
            for prefix in SKIP_PREFIXES
        ):
            continue

        urls.append(url)

    return sorted(
        set(urls)
    )


def preview_url_for(
    canonical_url: str,
) -> str:
    parsed = urlparse(
        canonical_url
    )

    path = parsed.path or "/"

    if parsed.query:
        path += "?" + parsed.query

    url = PREVIEW_BASE + path

    validate_source_url(url)

    return url


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        cleaned = normalize_text(
            value
        )

        key = cleaned.lower()

        if (
            not cleaned
            or key in seen
        ):
            continue

        seen.add(key)
        result.append(cleaned)

    return result


def parse_page(
    canonical_url: str,
    source_url: str,
    text: str,
) -> dict:
    parser = PublicPageParser()
    parser.feed(text)

    canonical = (
        parser.canonical
        or canonical_url
    )

    validate_public_url(canonical)

    parsed = urlparse(
        canonical_url
    )

    title = normalize_text(
        " ".join(
            parser.title_parts
        )
    )

    h1_values = dedupe(
        parser.h1_parts
    )

    headings = dedupe(
        parser.headings
    )[:MAX_HEADINGS]

    paragraphs = dedupe(
        parser.paragraphs
    )[:MAX_PARAGRAPHS]

    list_items = dedupe(
        parser.list_items
    )[:MAX_LIST_ITEMS]

    return {
        "path":
            parsed.path or "/",
        "title":
            title,
        "description":
            normalize_text(
                parser.description
            ),
        "canonical_url":
            canonical,
        "source_url":
            source_url,
        "h1":
            (
                h1_values[0]
                if h1_values
                else ""
            ),
        "headings":
            headings,
        "paragraphs":
            paragraphs,
        "list_items":
            list_items,
    }


def main() -> int:
    print(
        f"Fetching sitemap: {SITEMAP_URL}"
    )

    try:
        xml_text = fetch_text(
            SITEMAP_URL
        )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
    ) as exc:
        print(
            f"ERROR: sitemap fetch failed: {exc}",
            file=sys.stderr,
        )
        return 1

    urls = sitemap_urls(
        xml_text
    )

    print(
        f"Approved sitemap URLs: {len(urls)}"
    )

    if not urls:
        print(
            "ERROR: sitemap contained no approved URLs.",
            file=sys.stderr,
        )
        return 1

    documents: list[dict] = []

    failures: list[dict] = []

    for index, canonical_url in enumerate(
        urls,
        start=1,
    ):
        source_url = preview_url_for(
            canonical_url
        )

        try:
            page_text = fetch_text(
                source_url
            )

            document = parse_page(
                canonical_url,
                source_url,
                page_text,
            )

            if not (
                document["title"]
                or document["h1"]
                or document["paragraphs"]
            ):
                raise ValueError(
                    "No usable page content"
                )

            documents.append(
                document
            )

            print(
                f"[{index:03d}/{len(urls):03d}] "
                f"PASS {document['path']}"
            )

        except Exception as exc:
            failures.append(
                {
                    "canonical_url":
                        canonical_url,
                    "source_url":
                        source_url,
                    "error":
                        str(exc)[:300],
                }
            )

            print(
                f"[{index:03d}/{len(urls):03d}] "
                f"FAIL {source_url}: {exc}"
            )

        time.sleep(0.05)

    snapshot = {
        "version": 1,
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),
        "source_sitemap":
            SITEMAP_URL,
        "source_environment":
            "preview",
        "documents":
            documents,
        "failures":
            failures,
    }

    output_path = Path(
        os.environ.get(
            "NMS_CONCIERGE_KNOWLEDGE_OUTPUT",
            str(KNOWLEDGE_PATH),
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = Path(
        str(output_path)
        + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            snapshot,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temp_path.replace(
        output_path
    )

    print()
    print(
        f"Knowledge documents: {len(documents)}"
    )
    print(
        f"Fetch failures:       {len(failures)}"
    )
    print(
        f"Snapshot: {output_path}"
    )

    if not documents:
        return 1

    failure_ratio = (
        len(failures)
        / len(urls)
    )

    if failure_ratio > 0.05:
        print(
            "ERROR: more than 5% of website pages failed.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
