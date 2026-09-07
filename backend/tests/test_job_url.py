"""Pasting a job in: SSRF defenses, extraction, and the text fallback.

The server makes an outbound request to a string the user controls, so the SSRF
checks here are the highest-value tests in the suite.
"""

import pytest

from app.services import job_url


# --- SSRF ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5433/",
        "http://localhost:8000/health",
        "http://169.254.169.254/latest/meta-data/",  # cloud instance metadata
        "http://[::1]:8000/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/admin",
        "http://172.16.0.1/",
        "http://0.0.0.0/",
    ],
)
def test_private_and_loopback_addresses_are_refused(url):
    with pytest.raises(job_url.JobFetchError):
        job_url.validate_url(url)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "javascript:alert(1)"],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(job_url.JobFetchError):
        job_url.validate_url(url)


def test_absurdly_long_urls_are_refused():
    with pytest.raises(job_url.JobFetchError):
        job_url.validate_url("https://example.com/" + "a" * 3000)


def test_public_urls_pass():
    assert job_url.validate_url("https://example.com/jobs/1") == "https://example.com/jobs/1"


def test_redirects_are_revalidated(monkeypatch):
    """An open redirect to an internal address is the standard SSRF bypass."""
    seen = []

    def fake_validate(raw):
        seen.append(raw)
        if "169.254" in raw or "localhost" in raw:
            raise job_url.JobFetchError("That URL could not be reached.")
        return raw

    class FakeResponse:
        is_redirect = True
        status_code = 302
        headers = {"location": "http://169.254.169.254/"}
        url = type("U", (), {"join": staticmethod(lambda loc: loc)})()

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(job_url, "validate_url", fake_validate)
    monkeypatch.setattr(job_url.httpx, "Client", lambda **kw: FakeClient())

    with pytest.raises(job_url.JobFetchError):
        job_url.fetch_page("https://example.com/jobs/1")
    assert any("169.254" in s for s in seen), "redirect target was never validated"


# --- Extraction ----------------------------------------------------------

JSON_LD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Senior Backend Engineer",
 "hiringOrganization":{"@type":"Organization","name":"Acme Ltd"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"London","addressCountry":"UK"}},
 "description":"<p>Build <b>Python</b> services.</p><ul><li>Five years experience</li></ul>"}
</script></head><body>irrelevant</body></html>
"""


def test_json_ld_is_preferred():
    """Exact structured data, and it costs no AI quota."""
    parsed = job_url.parse_json_ld(JSON_LD_PAGE)
    assert parsed["title"] == "Senior Backend Engineer"
    assert parsed["company"] == "Acme Ltd"
    assert "London" in parsed["location"]
    assert "Python" in parsed["description"]
    assert "<b>" not in parsed["description"], "HTML should be stripped"


def test_json_ld_found_inside_a_graph():
    page = """<script type="application/ld+json">
    {"@graph":[{"@type":"WebSite"},{"@type":"JobPosting","title":"Dev",
     "hiringOrganization":{"name":"X"},"description":"Long enough description here."}]}
    </script>"""
    assert job_url.parse_json_ld(page)["title"] == "Dev"


def test_malformed_json_ld_does_not_crash():
    assert job_url.parse_json_ld('<script type="application/ld+json">{ broken</script>') is None


def test_container_fallback_for_pages_without_json_ld():
    page = (
        '<html><head><title>Backend Engineer - Acme</title></head><body>'
        '<div class="job-description">' + "<p>Python and PostgreSQL. </p>" * 20 + "</div></body></html>"
    )
    parsed = job_url.parse_containers(page)
    assert parsed is not None
    assert "Python" in parsed["description"]


def test_publisher_names_known_boards():
    assert job_url.publisher_for("https://uk.linkedin.com/jobs/view/1") == "LinkedIn"
    assert job_url.publisher_for("https://boards.greenhouse.io/x") == "Greenhouse"
    # Unknown hosts fall back to the domain rather than nothing.
    assert job_url.publisher_for("https://careers.monzo.com/x") == "careers.monzo.com"
    assert job_url.publisher_for(None) is None


# --- Endpoints -----------------------------------------------------------


def test_paste_text_creates_a_job(client, auth, with_job):
    headers, _, _ = auth()
    job = with_job(headers)
    assert job["title"] == "Backend Engineer"
    assert job["company"]["name"] == "Acme Ltd"
    assert job["url"], "apply link must survive"
    assert job["source_publisher"]


def test_paste_text_rejects_a_stub(client, auth):
    headers, _, _ = auth()
    r = client.post(
        "/api/jobs/from-text", headers=headers, json={"text": "too short to be a job"}
    )
    assert r.status_code == 422


def test_pasting_the_same_job_twice_reuses_the_row(client, auth, with_job):
    headers, _, _ = auth()
    first = with_job(headers)
    second = with_job(headers)
    assert first["id"] == second["id"]


def test_from_url_refuses_internal_addresses(client, auth):
    headers, _, _ = auth()
    r = client.post(
        "/api/jobs/from-url", headers=headers, json={"url": "http://169.254.169.254/"}
    )
    assert r.status_code == 422


def test_job_list_shows_only_your_own(client, auth, with_job):
    a, _, _ = auth()
    job = with_job(a)
    client.post(f"/api/saved/{job['id']}", headers=a)

    b, _, _ = auth()
    assert client.get("/api/jobs", headers=b).json() == []
    assert len(client.get("/api/jobs", headers=a).json()) == 1


def test_adding_a_job_requires_auth(client):
    assert client.post("/api/jobs/from-text", json={"text": "x" * 300}).status_code == 401
