"""Resume upload, text extraction, and the skill profile that drives search."""

import io

from tests.conftest import SAMPLE_RESUME


def test_no_resume_initially(client, auth):
    headers, _, _ = auth()
    assert client.get("/api/resumes/active", headers=headers).json() is None


def test_upload_extracts_a_skill_profile(with_resume, ai_stub):
    _, resume = with_resume()
    assert resume["is_active"] is True
    profile = resume["skill_profile"]
    assert profile is not None
    assert "Python" in profile["skills"]
    assert "Backend Engineer" in profile["job_titles"]
    assert profile["seniority"] == "senior"
    # Extraction runs once per upload, never per search.
    assert ai_stub["extract"] == 1


def test_upload_rejects_unsupported_type(client, auth):
    headers, _, _ = auth()
    r = client.post(
        "/api/resumes",
        headers=headers,
        files={"file": ("cv.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )
    assert r.status_code == 415


def test_upload_rejects_unreadable_file(client, auth, ai_stub):
    """A PDF we cannot read is rejected rather than stored as an empty resume."""
    headers, _, _ = auth()
    r = client.post(
        "/api/resumes",
        headers=headers,
        files={"file": ("cv.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")},
    )
    assert r.status_code == 422


def test_upload_rejects_too_short_text(client, auth, ai_stub):
    headers, _, _ = auth()
    r = client.post(
        "/api/resumes", headers=headers, files={"file": ("cv.txt", b"hi", "text/plain")}
    )
    assert r.status_code == 422


def test_uploading_again_deactivates_the_previous_resume(client, with_resume, ai_stub):
    headers, first = with_resume()
    second = client.post(
        "/api/resumes",
        headers=headers,
        files={"file": ("cv2.txt", SAMPLE_RESUME.encode(), "text/plain")},
    ).json()

    assert second["id"] != first["id"]
    assert client.get("/api/resumes/active", headers=headers).json()["id"] == second["id"]

    # The old one survives - documents reference the resume they were built from.
    all_resumes = client.get("/api/resumes", headers=headers).json()
    assert len(all_resumes) == 2
    assert [r["is_active"] for r in all_resumes].count(True) == 1


def test_user_can_correct_the_skill_profile(client, with_resume):
    headers, resume = with_resume()
    r = client.patch(
        f"/api/resumes/{resume['id']}/skill-profile",
        headers=headers,
        json={"skills": ["Rust", "Go"], "seniority": "lead"},
    )
    assert r.status_code == 200
    assert r.json()["skills"] == ["Rust", "Go"]
    assert r.json()["seniority"] == "lead"
    # Flagged so the UI can show it is no longer the raw extraction.
    assert r.json()["edited_by_user"] is True


def test_skill_profile_edits_are_deduplicated_and_cleaned(client, with_resume):
    headers, resume = with_resume()
    r = client.patch(
        f"/api/resumes/{resume['id']}/skill-profile",
        headers=headers,
        json={"skills": ["Python", "python", "  PYTHON  ", "Go\x00"]},
    )
    assert r.json()["skills"] == ["Python", "Go"]


def test_reanalyze_recomputes(client, with_resume, ai_stub):
    headers, resume = with_resume()
    before = ai_stub["extract"]
    r = client.post(f"/api/resumes/{resume['id']}/analyze", headers=headers)
    assert r.status_code == 200
    assert ai_stub["extract"] == before + 1


def test_cannot_touch_another_users_resume(client, with_resume, auth):
    _, resume = with_resume()
    other_headers, _, _ = auth()
    r = client.patch(
        f"/api/resumes/{resume['id']}/skill-profile",
        headers=other_headers,
        json={"skills": ["Injected"]},
    )
    assert r.status_code == 404


def test_upload_requires_auth(client):
    r = client.post("/api/resumes", files={"file": ("cv.txt", b"x" * 300, "text/plain")})
    assert r.status_code == 401


def test_docx_tables_are_extracted(ai_stub):
    """Resumes routinely put dates and roles in tables, which python-docx keeps
    out of `paragraphs` entirely - missing them loses half the CV."""
    import docx

    from app.services import resume_text

    document = docx.Document()
    document.add_paragraph("Alex Morgan - Backend Engineer - alex.morgan@example.com")
    document.add_paragraph(
        "Backend engineer with six years building Python services at scale, "
        "focused on payments infrastructure and event-driven architecture."
    )
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "2021-2026"
    table.rows[0].cells[1].text = "Senior Backend Engineer at Monzo building Python services"
    document.add_paragraph("Skills: Python, PostgreSQL, AWS, Docker, Kubernetes, Redis, FastAPI")
    document.add_paragraph("Education: BSc Computer Science, University of Manchester")

    buf = io.BytesIO()
    document.save(buf)

    text = resume_text.extract(
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert "Monzo" in text
    assert "2021-2026" in text


def test_delete_resume_removes_derived_data(client, with_resume, ai_stub):
    """A CV is sensitive data - the user must be able to remove it, and
    everything derived from it goes too."""
    headers, resume = with_resume()
    job = client.get("/api/jobs/search", headers=headers).json()["results"][0]
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"})
    assert client.get("/api/history", headers=headers).json()

    assert client.delete(f"/api/resumes/{resume['id']}", headers=headers).status_code == 204
    assert client.get("/api/resumes/active", headers=headers).json() is None
    assert client.get("/api/history", headers=headers).json() == []


def test_deleting_the_active_resume_promotes_the_previous_one(client, with_resume, ai_stub):
    headers, first = with_resume()
    second = client.post(
        "/api/resumes",
        headers=headers,
        files={"file": ("cv2.txt", SAMPLE_RESUME.encode(), "text/plain")},
    ).json()

    client.delete(f"/api/resumes/{second['id']}", headers=headers)
    assert client.get("/api/resumes/active", headers=headers).json()["id"] == first["id"]


def test_cannot_delete_another_users_resume(client, with_resume, auth):
    _, resume = with_resume()
    other, _, _ = auth()
    client.delete(f"/api/resumes/{resume['id']}", headers=other)
    # Still there for its owner.
    assert client.get(f"/api/resumes", headers=other).json() == []


def test_resume_file_url_is_returned(with_resume):
    """Stored verbatim so the user can get their original back - which only
    works if the URL actually reaches them."""
    _, resume = with_resume()
    assert resume["file_url"]
