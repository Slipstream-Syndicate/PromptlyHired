"""Fetch a job advert from a URL the user pasted.

This is the only way jobs enter the system. It is deliberately *user-initiated
and one page at a time* - not a crawler. We fetch a page the user was going to
open anyway, which is a different thing from harvesting a board in bulk (that
violates every major board's terms and gets IPs banned).

**SSRF is the main risk here.** The server makes an outbound request to a string
the user controls. Without checks, `http://169.254.169.254/` reads cloud
instance metadata, and `http://localhost:5433/` probes the database. Every
resolved address is checked against private ranges, before connecting and again
after each redirect.

Extraction order, cheapest first:
  1. JSON-LD `JobPosting` - the schema.org markup most boards emit, exact data.
  2. Known container classes for boards that do not emit JSON-LD.
  3. Whole-page text handed to the model, which costs a call.
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 4
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# A real browser UA: many boards serve a stub or a 403 to obvious bots, and we
# are fetching one page on a user's behalf, not crawling.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Boards that reliably need the model to read the page.
_DESCRIPTION_PATTERNS = [
    r'class="[^"]*(?:description__text|show-more-less-html__markup)[^"]*"(.*?)</section>',
    r'<div[^>]+class="[^"]*(?:job-?description|jobDescription|posting-?description)[^"]*"[^>]*>(.*?)</div>\s*</div>',
    r'<div[^>]+id="jobDescriptionText"[^>]*>(.*?)</div>',
    # Greedier last resort: description containers usually hold nested divs, so
    # the non-greedy patterns above stop at the first inner </div>.
    r'<div[^>]+class="[^"]*(?:job-?description|jobDescription|posting-?description)[^"]*"[^>]*>(.*)</div>',
]


class JobFetchError(ValueError):
    """Fetch or parse failed - the message is safe to show the user."""


def _is_public_address(host: str) -> bool:
    """Resolve and reject anything not on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        # Covers loopback, RFC1918, link-local (cloud metadata), CGNAT,
        # multicast, reserved and unspecified.
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def validate_url(raw: str) -> str:
    """Reject anything that is not a public http(s) URL. Raises JobFetchError."""
    raw = (raw or "").strip()
    if len(raw) > 2048:
        raise JobFetchError("That URL is too long.")

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise JobFetchError("Paste a full http:// or https:// link to the job posting.")
    if not parsed.hostname:
        raise JobFetchError("That does not look like a valid URL.")
    if not _is_public_address(parsed.hostname):
        # Deliberately vague: do not confirm what does or does not resolve
        # internally for whoever is probing.
        raise JobFetchError("That URL could not be reached.")
    return raw


def fetch_page(url: str) -> tuple[str, str]:
    """Return (final_url, html). Follows redirects manually so each hop is checked."""
    url = validate_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                raise JobFetchError(f"Could not load that page: {exc}") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                # Re-validate: an open redirect to an internal address is the
                # standard way round a naive SSRF check.
                url = validate_url(str(response.url.join(location)))
                continue

            if response.status_code == 403:
                raise JobFetchError(
                    "That site blocked the request. Try copying the job description "
                    "text and pasting it directly instead."
                )
            if response.status_code >= 400:
                raise JobFetchError(f"That page returned an error ({response.status_code}).")

            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                raise JobFetchError("That link is not a web page.")

            body = response.content[:MAX_PAGE_BYTES]
            return str(response.url), body.decode(response.encoding or "utf-8", errors="replace")

    raise JobFetchError("That link redirected too many times.")


def _strip_html(fragment: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def _walk_json_ld(node):
    """JobPosting can be nested inside @graph or a list."""
    if isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "JobPosting" in types:
            return node
        for value in node.values():
            found = _walk_json_ld(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_json_ld(item)
            if found:
                return found
    return None


def parse_json_ld(page: str) -> dict | None:
    """schema.org JobPosting - exact data, no model call needed."""
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.S | re.I
    ):
        try:
            posting = _walk_json_ld(json.loads(block.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
        if not posting:
            continue

        org = posting.get("hiringOrganization") or {}
        company = org.get("name") if isinstance(org, dict) else str(org)

        location = ""
        loc = posting.get("jobLocation")
        loc = loc[0] if isinstance(loc, list) and loc else loc
        if isinstance(loc, dict):
            address = loc.get("address") or {}
            if isinstance(address, dict):
                location = ", ".join(
                    str(address[k])
                    for k in ("addressLocality", "addressRegion", "addressCountry")
                    if address.get(k) and isinstance(address.get(k), str)
                )

        return {
            "title": str(posting.get("title") or "").strip(),
            "company": str(company or "").strip(),
            "location": location.strip(),
            "description": _strip_html(str(posting.get("description") or "")),
        }
    return None


def parse_containers(page: str) -> dict | None:
    """Known description containers for boards without JSON-LD."""
    for pattern in _DESCRIPTION_PATTERNS:
        m = re.search(pattern, page, re.S | re.I)
        if not m:
            continue
        description = _strip_html(m.group(1))
        if len(description) < 200:
            continue
        title = ""
        t = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
        if t:
            title = html.unescape(_strip_html(t.group(1)))[:200]
        return {"title": title, "company": "", "location": "", "description": description}
    return None


def page_text(page: str, limit: int = 40_000) -> str:
    """Whole-page text, for handing to the model as a last resort."""
    return _strip_html(page)[:limit]


# Recognisable boards, so the Apply button can name where it is sending the user
# ("Apply on LinkedIn") exactly as it did when listings came from an aggregator.
_KNOWN_BOARDS = {
    "linkedin.": "LinkedIn",
    "indeed.": "Indeed",
    "glassdoor.": "Glassdoor",
    "ziprecruiter.": "ZipRecruiter",
    "monster.": "Monster",
    "totaljobs.": "Totaljobs",
    "reed.co.uk": "Reed",
    "otta.com": "Otta",
    "wellfound.com": "Wellfound",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "workable.com": "Workable",
    "smartrecruiters.": "SmartRecruiters",
    "bamboohr.": "BambooHR",
    "myworkdayjobs.": "Workday",
}


def publisher_for(url: str | None) -> str | None:
    """Name the destination of the Apply link, falling back to the domain."""
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    for fragment, name in _KNOWN_BOARDS.items():
        if fragment in host:
            return name
    host = host.removeprefix("www.")
    return host[:120] or None
