"""Deterministic, READ-ONLY technical site-audit engine.

The classification logic here is a pure function of already-fetched page
data (`run_audit`). A thin, bounded live fetcher (`fetch_site`) uses only
HTTP GET/HEAD and never modifies the target website. Network fetching is
separated from classification so the audit rules are fully unit-testable
without any network access.

Safety:
- READ-ONLY. Only GET/HEAD requests are issued.
- No writes/publishing to any site.
- Bounded page count + timeout; same-host only; blocks private/loopback
  hosts (basic SSRF guard).
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Mapping, Optional
from urllib.parse import urljoin, urlparse

from .contracts import (
    AuditIssue,
    CATEGORY_ACCESSIBILITY,
    CATEGORY_CONTENT,
    CATEGORY_CRAWLABILITY,
    CATEGORY_INDEXABILITY,
    CATEGORY_LINKS,
    CATEGORY_METADATA,
    CATEGORY_PERFORMANCE,
    SEVERITIES,
    SEVERITY_CRITICAL,
    SEVERITY_INFORMATIONAL,
    SEVERITY_OPPORTUNITY,
    SEVERITY_WARNING,
)

# Response time (ms) above which a page is flagged as slow.
SLOW_RESPONSE_MS = 3000


@dataclass(frozen=True)
class PageFetchResult:
    """Already-fetched page data handed to the deterministic classifier."""
    url: str
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    elapsed_ms: Optional[int] = None
    redirect_chain: tuple[str, ...] = ()
    html: Optional[str] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    fetch_error: Optional[str] = None


@dataclass
class ParsedPage:
    titles: list[str] = field(default_factory=list)
    meta_descriptions: list[str] = field(default_factory=list)
    canonicals: list[str] = field(default_factory=list)
    h1_count: int = 0
    meta_robots: Optional[str] = None
    images_total: int = 0
    images_missing_alt: int = 0
    internal_links: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.page = ParsedPage()
        self._in_title = False
        self._title_buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
            self._title_buffer = []
        elif tag == "h1":
            self.page.h1_count += 1
        elif tag == "meta":
            name = attr.get("name", "").lower()
            if name == "description":
                self.page.meta_descriptions.append(
                    attr.get("content", "").strip()
                )
            elif name == "robots":
                self.page.meta_robots = attr.get("content", "").lower()
        elif tag == "link":
            rel = attr.get("rel", "").lower()
            if "canonical" in rel:
                self.page.canonicals.append(attr.get("href", "").strip())
        elif tag == "img":
            self.page.images_total += 1
            if not attr.get("alt", "").strip():
                self.page.images_missing_alt += 1
        elif tag == "a":
            href = attr.get("href", "").strip()
            if href and not href.startswith(
                ("#", "mailto:", "tel:", "javascript:")
            ):
                absolute = urljoin(self.base_url, href)
                if _same_host(self.base_url, absolute):
                    self.page.internal_links.append(absolute.split("#")[0])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            title = "".join(self._title_buffer).strip()
            if title:
                self.page.titles.append(title)

    def handle_data(self, data):
        if self._in_title:
            self._title_buffer.append(data)


def parse_page(html: str, base_url: str) -> ParsedPage:
    parser = _PageParser(base_url)
    parser.feed(html or "")
    return parser.page


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()


def _issue(
    *,
    severity: str,
    category: str,
    issue_code: str,
    url: str,
    description: str,
    recommended_action: str,
    details: Optional[dict] = None,
) -> AuditIssue:
    return AuditIssue(
        severity=severity,
        category=category,
        issue_code=issue_code,
        url=url,
        description=description,
        recommended_action=recommended_action,
        details=details or {},
    )


def classify_page(
    page: PageFetchResult,
    *,
    link_status: Optional[Mapping[str, int]] = None,
) -> list[AuditIssue]:
    """Deterministic per-page issue classification."""
    issues: list[AuditIssue] = []
    url = page.final_url or page.url

    # 1. Reachability / HTTP status.
    if page.fetch_error or page.status_code is None:
        issues.append(_issue(
            severity=SEVERITY_CRITICAL,
            category=CATEGORY_CRAWLABILITY,
            issue_code="page_unreachable",
            url=url,
            description="The page could not be fetched.",
            recommended_action=(
                "Verify the URL is publicly reachable and returns a "
                "200 response."
            ),
            details={"error": page.fetch_error} if page.fetch_error else {},
        ))
        return issues

    status = page.status_code
    if status >= 500:
        issues.append(_issue(
            severity=SEVERITY_CRITICAL,
            category=CATEGORY_CRAWLABILITY,
            issue_code="http_5xx",
            url=url,
            description=f"Server error status {status}.",
            recommended_action="Resolve the server error so the page loads.",
            details={"status_code": status},
        ))
        return issues
    if 400 <= status < 500:
        issues.append(_issue(
            severity=SEVERITY_CRITICAL,
            category=CATEGORY_CRAWLABILITY,
            issue_code="http_4xx",
            url=url,
            description=f"Client error status {status}.",
            recommended_action=(
                "Fix or redirect this URL; it is not serving content."
            ),
            details={"status_code": status},
        ))
        return issues

    # 2. Redirect chains.
    if len(page.redirect_chain) > 1:
        issues.append(_issue(
            severity=SEVERITY_WARNING,
            category=CATEGORY_CRAWLABILITY,
            issue_code="redirect_chain",
            url=page.url,
            description=(
                f"Redirect chain of {len(page.redirect_chain)} hops "
                "before final URL."
            ),
            recommended_action=(
                "Point the initial URL directly at the final destination."
            ),
            details={"redirect_chain": list(page.redirect_chain)},
        ))

    # 3. Response timing.
    if page.elapsed_ms is not None and page.elapsed_ms > SLOW_RESPONSE_MS:
        issues.append(_issue(
            severity=SEVERITY_OPPORTUNITY,
            category=CATEGORY_PERFORMANCE,
            issue_code="slow_response",
            url=url,
            description=(
                f"Server responded in {page.elapsed_ms} ms "
                f"(> {SLOW_RESPONSE_MS} ms)."
            ),
            recommended_action=(
                "Improve server/page response time for better UX and SEO."
            ),
            details={"elapsed_ms": page.elapsed_ms},
        ))

    parsed = parse_page(page.html or "", url)

    # 4. Indexability (robots).
    robots = parsed.meta_robots or ""
    x_robots = str(page.headers.get("x-robots-tag", "")).lower()
    if "noindex" in robots or "noindex" in x_robots:
        issues.append(_issue(
            severity=SEVERITY_CRITICAL,
            category=CATEGORY_INDEXABILITY,
            issue_code="noindex_directive",
            url=url,
            description="Page is marked noindex and will not be indexed.",
            recommended_action=(
                "Remove the noindex directive if this page should rank."
            ),
        ))

    # 5. Title.
    if len(parsed.titles) == 0:
        issues.append(_issue(
            severity=SEVERITY_CRITICAL,
            category=CATEGORY_METADATA,
            issue_code="missing_title",
            url=url,
            description="Page has no <title> element.",
            recommended_action="Add a unique, descriptive page title.",
        ))
    elif len(parsed.titles) > 1:
        issues.append(_issue(
            severity=SEVERITY_WARNING,
            category=CATEGORY_METADATA,
            issue_code="multiple_titles",
            url=url,
            description="Page has more than one <title> element.",
            recommended_action="Keep exactly one <title> element.",
        ))

    # 6. Meta description.
    non_empty_meta = [m for m in parsed.meta_descriptions if m]
    if len(non_empty_meta) == 0:
        issues.append(_issue(
            severity=SEVERITY_WARNING,
            category=CATEGORY_METADATA,
            issue_code="missing_meta_description",
            url=url,
            description="Page has no meta description.",
            recommended_action="Add a concise, unique meta description.",
        ))
    elif len(non_empty_meta) > 1:
        issues.append(_issue(
            severity=SEVERITY_WARNING,
            category=CATEGORY_METADATA,
            issue_code="multiple_meta_descriptions",
            url=url,
            description="Page has multiple meta descriptions.",
            recommended_action="Keep a single meta description.",
        ))

    # 7. Canonical.
    if len([c for c in parsed.canonicals if c]) == 0:
        issues.append(_issue(
            severity=SEVERITY_OPPORTUNITY,
            category=CATEGORY_METADATA,
            issue_code="missing_canonical",
            url=url,
            description="Page has no canonical link.",
            recommended_action="Add a self-referencing canonical link.",
        ))

    # 8. H1 structure.
    if parsed.h1_count == 0:
        issues.append(_issue(
            severity=SEVERITY_WARNING,
            category=CATEGORY_CONTENT,
            issue_code="missing_h1",
            url=url,
            description="Page has no H1 heading.",
            recommended_action="Add a single descriptive H1 heading.",
        ))
    elif parsed.h1_count > 1:
        issues.append(_issue(
            severity=SEVERITY_OPPORTUNITY,
            category=CATEGORY_CONTENT,
            issue_code="multiple_h1",
            url=url,
            description=f"Page has {parsed.h1_count} H1 headings.",
            recommended_action="Prefer a single H1 per page.",
            details={"h1_count": parsed.h1_count},
        ))

    # 9. Image alt text.
    if parsed.images_missing_alt > 0:
        issues.append(_issue(
            severity=SEVERITY_OPPORTUNITY,
            category=CATEGORY_ACCESSIBILITY,
            issue_code="images_missing_alt",
            url=url,
            description=(
                f"{parsed.images_missing_alt} image(s) missing alt text."
            ),
            recommended_action=(
                "Add descriptive alt text to images for accessibility/SEO."
            ),
            details={
                "images_total": parsed.images_total,
                "images_missing_alt": parsed.images_missing_alt,
            },
        ))

    # 10. Broken internal links (from a provided status map, if any).
    if link_status:
        broken = sorted({
            link for link in parsed.internal_links
            if link_status.get(link, 200) >= 400
        })
        if broken:
            issues.append(_issue(
                severity=SEVERITY_WARNING,
                category=CATEGORY_LINKS,
                issue_code="broken_internal_link",
                url=url,
                description=(
                    f"{len(broken)} internal link(s) return an error."
                ),
                recommended_action=(
                    "Fix or remove links that point to error pages."
                ),
                details={"broken_links": broken[:20]},
            ))

    return issues


def _duplicate_issues(
    pages: list[PageFetchResult],
) -> list[AuditIssue]:
    """Cross-page duplicate <title> and meta-description detection."""
    issues: list[AuditIssue] = []
    titles: dict[str, list[str]] = {}
    metas: dict[str, list[str]] = {}

    for page in pages:
        if page.fetch_error or page.status_code is None:
            continue
        if not (200 <= page.status_code < 300):
            continue
        url = page.final_url or page.url
        parsed = parse_page(page.html or "", url)
        for title in parsed.titles:
            key = title.strip().lower()
            if key:
                titles.setdefault(key, []).append(url)
        for meta in parsed.meta_descriptions:
            key = meta.strip().lower()
            if key:
                metas.setdefault(key, []).append(url)

    for key, urls in titles.items():
        unique_urls = sorted(set(urls))
        if len(unique_urls) > 1:
            for url in unique_urls:
                issues.append(_issue(
                    severity=SEVERITY_WARNING,
                    category=CATEGORY_METADATA,
                    issue_code="duplicate_title",
                    url=url,
                    description=(
                        "Title is duplicated across "
                        f"{len(unique_urls)} pages."
                    ),
                    recommended_action="Make each page title unique.",
                    details={"shared_with": unique_urls},
                ))

    for key, urls in metas.items():
        unique_urls = sorted(set(urls))
        if len(unique_urls) > 1:
            for url in unique_urls:
                issues.append(_issue(
                    severity=SEVERITY_WARNING,
                    category=CATEGORY_METADATA,
                    issue_code="duplicate_meta_description",
                    url=url,
                    description=(
                        "Meta description is duplicated across "
                        f"{len(unique_urls)} pages."
                    ),
                    recommended_action=(
                        "Write a unique meta description per page."
                    ),
                    details={"shared_with": unique_urls},
                ))

    return issues


def run_audit(
    pages: list[PageFetchResult],
    *,
    sitemap_found: Optional[bool] = None,
    link_status: Optional[Mapping[str, int]] = None,
    site_url: Optional[str] = None,
) -> dict[str, Any]:
    """Deterministically classify a set of fetched pages into an audit.

    Returns a summary dict + list of issue dicts. Pure function.
    """
    issues: list[AuditIssue] = []

    for page in pages:
        issues.extend(classify_page(page, link_status=link_status))

    issues.extend(_duplicate_issues(pages))

    # Site-level: sitemap visibility.
    if sitemap_found is False:
        issues.append(_issue(
            severity=SEVERITY_OPPORTUNITY,
            category=CATEGORY_CRAWLABILITY,
            issue_code="missing_sitemap",
            url=(site_url or (pages[0].url if pages else "")),
            description="No XML sitemap was discovered.",
            recommended_action=(
                "Publish a sitemap.xml and reference it in robots.txt."
            ),
        ))

    counts = {severity: 0 for severity in SEVERITIES}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1

    # Deterministic ordering for presentation.
    from .contracts import SEVERITY_ORDER
    ordered = sorted(
        issues,
        key=lambda i: (SEVERITY_ORDER.get(i.severity, 99), i.url, i.issue_code),
    )

    return {
        "pages_scanned": len(pages),
        "issues_total": len(issues),
        "critical_count": counts[SEVERITY_CRITICAL],
        "warning_count": counts[SEVERITY_WARNING],
        "opportunity_count": counts[SEVERITY_OPPORTUNITY],
        "informational_count": counts[SEVERITY_INFORMATIONAL],
        "sitemap_found": sitemap_found,
        "issues": [issue.to_dict() for issue in ordered],
    }


# --------------------------------------------------------------------------
# Bounded, READ-ONLY live fetcher (thin adapter; not used in unit tests)
# --------------------------------------------------------------------------

def is_public_http_url(url: str) -> bool:
    """Basic SSRF guard: http/https + non-private/non-loopback host."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        # Unresolvable now; allow the fetch attempt to fail safely later.
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            return False
    return True


def fetch_site(
    base_url: str,
    *,
    max_pages: int = 5,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Fetch a bounded set of same-host pages, READ-ONLY (GET/HEAD only).

    Returns kwargs suitable for run_audit(). Degrades gracefully: network
    failures become a single unreachable PageFetchResult rather than raising.
    """
    import httpx

    if not is_public_http_url(base_url):
        return {
            "pages": [PageFetchResult(
                url=base_url,
                fetch_error="URL is not a public http(s) address",
            )],
            "sitemap_found": None,
            "site_url": base_url,
        }

    headers = {"User-Agent": "NMS-MarketingOS-SearchAudit/1.0 (read-only)"}
    pages: list[PageFetchResult] = []
    link_status: dict[str, int] = {}
    sitemap_found: Optional[bool] = None

    def _fetch_one(client, url: str) -> PageFetchResult:
        start = time.monotonic()
        try:
            resp = client.get(url, headers=headers)
            elapsed = int((time.monotonic() - start) * 1000)
            chain = tuple(str(r.url) for r in resp.history) + (str(resp.url),)
            return PageFetchResult(
                url=url,
                final_url=str(resp.url),
                status_code=resp.status_code,
                elapsed_ms=elapsed,
                redirect_chain=chain if len(chain) > 1 else (),
                html=resp.text if "html" in resp.headers.get(
                    "content-type", ""
                ).lower() else "",
                headers={k.lower(): v for k, v in resp.headers.items()},
            )
        except Exception as exc:  # noqa: BLE001 - degrade safely
            return PageFetchResult(url=url, fetch_error=str(exc)[:200])

    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        limits=httpx.Limits(max_connections=4),
    ) as client:
        root = _fetch_one(client, base_url)
        pages.append(root)

        discovered: list[str] = []
        if root.html:
            parsed = parse_page(root.html, root.final_url or base_url)
            for link in parsed.internal_links:
                if link not in discovered and link != base_url:
                    discovered.append(link)

        for link in discovered[: max(0, max_pages - 1)]:
            page = _fetch_one(client, link)
            pages.append(page)
            if page.status_code is not None:
                link_status[link] = page.status_code

        # robots.txt + sitemap visibility (read-only).
        try:
            parsed_base = urlparse(base_url)
            origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
            robots = client.get(origin + "/robots.txt", headers=headers)
            has_sitemap_directive = (
                robots.status_code < 400
                and "sitemap:" in robots.text.lower()
            )
            sm = client.get(origin + "/sitemap.xml", headers=headers)
            sitemap_found = bool(
                has_sitemap_directive or sm.status_code < 400
            )
        except Exception:  # noqa: BLE001
            sitemap_found = None

    return {
        "pages": pages,
        "sitemap_found": sitemap_found,
        "link_status": link_status,
        "site_url": base_url,
    }
