"""Document generation, editing, and the History view derived from it."""


SAMPLE = (
    "Backend Engineer at Acme Ltd. Python, PostgreSQL and AWS. You will design "
    "APIs and own services in production. Five years of experience required."
) * 3


def _first_job(client, headers, title="Backend Engineer"):
    """Jobs are pasted, not searched.

    The URL is the dedup key, so distinct roles need distinct URLs - two pastes
    of the same link deliberately collapse onto one job.
    """
    slug = title.lower().replace(" ", "-")
    return client.post(
        "/api/jobs/from-text",
        headers=headers,
        json={"text": SAMPLE, "title": title, "company": "Acme Ltd",
              "url": f"https://example.com/jobs/{slug}"},
    ).json()


def test_generate_resume_and_cover_letter(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)

    resume_doc = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"}
    )
    assert resume_doc.status_code == 201
    assert resume_doc.json()["kind"] == "resume"
    assert resume_doc.json()["content"]["full_name"] == "Alex Morgan"
    assert resume_doc.json()["edited_content"] is None

    letter = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "cover_letter"}
    )
    assert letter.status_code == 201
    assert letter.json()["content"]["greeting"].startswith("Dear")

    assert ai_stub["resume"] == 1 and ai_stub["cover"] == 1


def test_generation_passes_user_steering_through(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    doc = client.post(
        f"/api/jobs/{job['id']}/documents",
        headers=headers,
        json={"kind": "resume", "instructions": "emphasise my backend work"},
    ).json()
    assert doc["content"]["instructions_seen"] == "emphasise my backend work"


def test_generation_uses_the_match_when_one_exists(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    r = client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"})
    assert r.status_code == 201


def test_generation_requires_a_resume(client, auth, with_resume, ai_stub):
    owner, _ = with_resume()
    job = _first_job(client, owner)
    other, _, _ = auth()
    r = client.post(f"/api/jobs/{job['id']}/documents", headers=other, json={"kind": "resume"})
    assert r.status_code == 409


def test_edits_never_overwrite_the_generated_original(client, with_resume, ai_stub):
    """Keeping both is what makes "reset to generated" possible and auditable."""
    headers, _ = with_resume()
    job = _first_job(client, headers)
    doc = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"}
    ).json()
    original = doc["content"]

    edited = client.patch(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={"edited_content": {"full_name": "Alex M.", "summary": "My own words"}},
    ).json()

    assert edited["edited_content"]["summary"] == "My own words"
    assert edited["content"] == original


def test_reset_discards_edits(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    doc = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"}
    ).json()
    client.patch(
        f"/api/documents/{doc['id']}", headers=headers, json={"edited_content": {"x": 1}}
    )

    reset = client.post(f"/api/documents/{doc['id']}/reset", headers=headers).json()
    assert reset["edited_content"] is None
    assert reset["content"] == doc["content"]
    # Reset must not re-run generation.
    assert ai_stub["resume"] == 1


def test_documents_are_private(client, with_resume, auth, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    doc = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"}
    ).json()

    other, _, _ = auth()
    assert client.get(f"/api/documents/{doc['id']}", headers=other).status_code == 404
    assert client.patch(
        f"/api/documents/{doc['id']}", headers=other, json={"edited_content": {"x": 1}}
    ).status_code == 404


def test_delete_document(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    doc = client.post(
        f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"}
    ).json()
    assert client.delete(f"/api/documents/{doc['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/documents/{doc['id']}", headers=headers).status_code == 404


# --- History --------------------------------------------------------------


def test_history_is_empty_until_something_is_generated(client, with_resume):
    headers, _ = with_resume()
    assert client.get("/api/history", headers=headers).json() == []


def test_history_groups_documents_by_job(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"})
    client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "cover_letter"})

    history = client.get("/api/history", headers=headers).json()
    assert len(history) == 1, "one entry per job, not per document"
    entry = history[0]
    assert entry["job"]["id"] == job["id"]
    assert {d["kind"] for d in entry["documents"]} == {"resume", "cover_letter"}
    # The apply link must survive into History - the user still needs to apply.
    assert entry["job"]["url"]


def test_history_covers_multiple_jobs_most_recent_first(client, with_resume, ai_stub):
    headers, _ = with_resume()
    jobs = [_first_job(client, headers, "Role A"), _first_job(client, headers, "Role B")]
    for job in jobs:
        client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"})

    history = client.get("/api/history", headers=headers).json()
    assert len(history) == 2
    assert history[0]["last_generated_at"] >= history[1]["last_generated_at"]


def test_history_is_per_user(client, with_resume, auth, ai_stub):
    headers, _ = with_resume()
    job = _first_job(client, headers)
    client.post(f"/api/jobs/{job['id']}/documents", headers=headers, json={"kind": "resume"})

    other, _, _ = auth()
    assert client.get("/api/history", headers=other).json() == []


def test_history_requires_auth(client):
    assert client.get("/api/history").status_code == 401
