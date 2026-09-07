"""Pasted jobs, saving, and on-demand match analysis."""


# --- Saving ---------------------------------------------------------------


def test_save_and_unsave(client, with_resume, with_job):
    headers, _ = with_resume()
    job = with_job(headers)

    assert client.post(f"/api/saved/{job['id']}", headers=headers).status_code == 201
    assert len(client.get("/api/saved", headers=headers).json()) == 1

    assert client.delete(f"/api/saved/{job['id']}", headers=headers).status_code == 204
    assert client.get("/api/saved", headers=headers).json() == []


def test_saved_list_is_per_user(client, with_resume, auth, with_job):
    headers, _ = with_resume()
    job = with_job(headers)
    client.post(f"/api/saved/{job['id']}", headers=headers)

    other, _, _ = auth()
    assert client.get("/api/saved", headers=other).json() == []


# --- Match analysis -------------------------------------------------------


def test_job_detail_does_not_score_on_its_own(client, with_resume, ai_stub, with_job):
    """Opening detail must not silently spend an API call."""
    headers, _ = with_resume()
    job = with_job(headers)

    detail = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert detail["match"] is None
    assert ai_stub["match"] == 0


def test_match_is_computed_then_cached(client, with_resume, ai_stub, with_job):
    headers, _ = with_resume()
    job = with_job(headers)

    first = client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    assert first.status_code == 200
    assert first.json()["match_percentage"] == 72
    assert first.json()["requirements_met"] == ["Python", "PostgreSQL"]
    assert first.json()["requirements_missing"] == ["Go", "Kafka"]
    assert ai_stub["match"] == 1

    # Second call must be free.
    second = client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    assert second.json()["id"] == first.json()["id"]
    assert ai_stub["match"] == 1


def test_refresh_forces_a_recompute(client, with_resume, ai_stub, with_job):
    headers, _ = with_resume()
    job = with_job(headers)
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    client.post(f"/api/jobs/{job['id']}/match", params={"refresh": "true"}, headers=headers)
    assert ai_stub["match"] == 2


def test_match_appears_on_the_card_and_in_detail(client, with_resume, with_job):
    headers, _ = with_resume()
    job = with_job(headers)
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)

    detail = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert detail["match"]["match_percentage"] == 72
    assert detail["job"]["has_match"] is True


def test_matching_requires_a_resume(client, auth, ai_stub, with_resume, with_job):
    """Without a resume there is nothing to match against."""
    owner, _ = with_resume()
    job = with_job(owner)

    other, _, _ = auth()
    r = client.post(f"/api/jobs/{job['id']}/match", headers=other)
    assert r.status_code == 409
    assert "resume" in r.json()["detail"].lower()


def test_match_is_per_user(client, with_resume, ai_stub, with_job):
    a_headers, _ = with_resume()
    b_headers, _ = with_resume()
    job = with_job(a_headers)

    client.post(f"/api/jobs/{job['id']}/match", headers=a_headers)
    assert client.get(f"/api/jobs/{job['id']}", headers=b_headers).json()["match"] is None


def test_match_on_missing_job_is_404(client, with_resume):
    headers, _ = with_resume()
    assert client.post("/api/jobs/999999/match", headers=headers).status_code == 404
