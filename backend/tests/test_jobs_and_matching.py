"""Skill-profile-driven search, saving, and on-demand match analysis."""

from app.models import SkillProfile
from app.routers.jobs import build_query


def _search(client, headers, **params):
    return client.get("/api/jobs/search", params=params, headers=headers).json()


# --- Query construction ---------------------------------------------------


def test_query_prefers_job_titles_over_raw_skills():
    """Boards index adverts by role name, so titles return far better results."""
    profile = SkillProfile(
        job_titles=["Backend Engineer", "Platform Engineer"],
        skills=["Python", "Docker"],
    )
    assert build_query(profile, None) == "Backend Engineer OR Platform Engineer"


def test_query_falls_back_to_skills_when_no_titles():
    profile = SkillProfile(job_titles=[], skills=["Python", "Kubernetes"])
    assert build_query(profile, None) == "Python Kubernetes"


def test_explicit_keywords_override_the_profile():
    profile = SkillProfile(job_titles=["Backend Engineer"], skills=[])
    assert build_query(profile, "data scientist") == "data scientist"


def test_no_profile_and_no_keywords_yields_nothing():
    assert build_query(None, None) is None


# --- Search ---------------------------------------------------------------


def test_search_without_a_resume_returns_empty_not_an_error(client, auth):
    """Nothing sensible to search for, but the feed must still render."""
    headers, _, _ = auth()
    body = _search(client, headers)
    assert body["results"] == []
    assert body["source"] == "none"


def test_search_uses_the_skill_profile_automatically(client, with_resume):
    headers, _ = with_resume()
    body = _search(client, headers)
    assert body["results"], "feed should populate from the resume alone"
    # The UI shows what it searched for, since the user typed nothing.
    assert "Backend Engineer" in body["searched_for"]


def test_feed_cards_carry_no_match_percentage(client, with_resume):
    """Scoring every card would cost ~20x the search itself."""
    headers, _ = with_resume()
    for job in _search(client, headers)["results"]:
        assert "match_percentage" not in job
        assert job["has_match"] is False


def test_every_card_has_an_apply_link(client, with_resume):
    headers, _ = with_resume()
    results = _search(client, headers)["results"]
    assert results
    assert all(job["url"] for job in results)


def test_explicit_keywords_are_honoured(client, with_resume):
    headers, _ = with_resume()
    body = _search(client, headers, keywords="data engineer")
    assert body["searched_for"] == "data engineer"


# --- Saving ---------------------------------------------------------------


def test_save_and_unsave(client, with_resume):
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]

    assert client.post(f"/api/saved/{job['id']}", headers=headers).status_code == 201
    assert len(client.get("/api/saved", headers=headers).json()) == 1

    assert client.delete(f"/api/saved/{job['id']}", headers=headers).status_code == 204
    assert client.get("/api/saved", headers=headers).json() == []


def test_saved_list_is_per_user(client, with_resume, auth):
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]
    client.post(f"/api/saved/{job['id']}", headers=headers)

    other, _, _ = auth()
    assert client.get("/api/saved", headers=other).json() == []


# --- Match analysis -------------------------------------------------------


def test_job_detail_does_not_score_on_its_own(client, with_resume, ai_stub):
    """Opening detail must not silently spend an API call."""
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]

    detail = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert detail["match"] is None
    assert ai_stub["match"] == 0


def test_match_is_computed_then_cached(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]

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


def test_refresh_forces_a_recompute(client, with_resume, ai_stub):
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)
    client.post(f"/api/jobs/{job['id']}/match", params={"refresh": "true"}, headers=headers)
    assert ai_stub["match"] == 2


def test_match_appears_on_the_card_and_in_detail(client, with_resume):
    headers, _ = with_resume()
    job = _search(client, headers)["results"][0]
    client.post(f"/api/jobs/{job['id']}/match", headers=headers)

    detail = client.get(f"/api/jobs/{job['id']}", headers=headers).json()
    assert detail["match"]["match_percentage"] == 72
    assert detail["job"]["has_match"] is True


def test_matching_requires_a_resume(client, auth, ai_stub, with_resume):
    """Without a resume there is nothing to match against."""
    owner, _ = with_resume()
    job = _search(client, owner)["results"][0]

    other, _, _ = auth()
    r = client.post(f"/api/jobs/{job['id']}/match", headers=other)
    assert r.status_code == 409
    assert "resume" in r.json()["detail"].lower()


def test_match_is_per_user(client, with_resume, ai_stub):
    a_headers, _ = with_resume()
    b_headers, _ = with_resume()
    job = _search(client, a_headers)["results"][0]

    client.post(f"/api/jobs/{job['id']}/match", headers=a_headers)
    assert client.get(f"/api/jobs/{job['id']}", headers=b_headers).json()["match"] is None


def test_match_on_missing_job_is_404(client, with_resume):
    headers, _ = with_resume()
    assert client.post("/api/jobs/999999/match", headers=headers).status_code == 404
