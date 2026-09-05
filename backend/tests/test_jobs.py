"""Search, preferences-as-one-source-of-truth, saving, following."""


def search(client, headers, **params):
    return client.get("/api/jobs/search", params=params, headers=headers).json()


def test_login_autosearch_uses_stored_preferences(client, auth):
    headers, _, _ = auth()
    body = search(client, headers, use_saved_preferences="true")
    assert body["source"] == "sample"  # no API key in tests, so fixtures
    assert len(body["results"]) > 0


def test_submitted_filters_become_the_stored_preferences(client, auth):
    headers, _, _ = auth()
    body = search(client, headers, keywords="engineer", location="London", job_type="full_time")
    assert body["preferences"]["keywords"] == "engineer"

    # The profile must read back exactly what the search form wrote.
    prefs = client.get("/api/profile/preferences", headers=headers).json()
    assert prefs["keywords"] == "engineer"
    assert prefs["location"] == "London"


def test_saving_a_job_does_not_follow_its_company(client, auth):
    headers, _, _ = auth()
    job = search(client, headers, use_saved_preferences="true")["results"][0]

    r = client.post(f"/api/saved/{job['id']}", headers=headers)
    assert r.status_code == 201
    assert r.json()["job"]["is_company_followed"] is False
    assert client.get("/api/follows", headers=headers).json() == []


def test_saving_is_idempotent(client, auth):
    headers, _, _ = auth()
    job = search(client, headers, use_saved_preferences="true")["results"][0]
    client.post(f"/api/saved/{job['id']}", headers=headers)
    client.post(f"/api/saved/{job['id']}", headers=headers)
    assert len(client.get("/api/saved", headers=headers).json()) == 1


def test_unsave(client, auth):
    headers, _, _ = auth()
    job = search(client, headers, use_saved_preferences="true")["results"][0]
    client.post(f"/api/saved/{job['id']}", headers=headers)
    assert client.delete(f"/api/saved/{job['id']}", headers=headers).status_code == 204
    assert client.get("/api/saved", headers=headers).json() == []


def test_followed_company_jobs_are_pinned_and_deduped_from_general(client, auth):
    headers, _, _ = auth()
    job = search(client, headers, use_saved_preferences="true")["results"][0]
    company_id = job["company"]["id"]

    assert client.post(f"/api/follows/{company_id}", headers=headers).status_code == 201

    body = search(client, headers, use_saved_preferences="true")
    assert len(body["followed"]) > 0
    assert all(j["company"]["id"] == company_id for j in body["followed"])
    # A pinned job must not also appear in the general list.
    assert all(j["company"]["id"] != company_id for j in body["results"])


def test_unfollow(client, auth):
    headers, _, _ = auth()
    job = search(client, headers, use_saved_preferences="true")["results"][0]
    cid = job["company"]["id"]
    client.post(f"/api/follows/{cid}", headers=headers)
    assert client.delete(f"/api/follows/{cid}", headers=headers).status_code == 204
    assert client.get("/api/follows", headers=headers).json() == []


def test_every_listing_carries_an_apply_link(client, auth):
    """The apply link is the only route from browsing to actually applying."""
    headers, _, _ = auth()
    results = search(client, headers, use_saved_preferences="true")["results"]
    assert results
    for job in results:
        assert job["url"], f"listing {job['id']} has no apply URL"


def test_search_requires_auth(client):
    assert client.get("/api/jobs/search").status_code == 401


def test_saved_list_is_per_user(client, auth):
    a_headers, _, _ = auth()
    b_headers, _, _ = auth()
    job = search(client, a_headers, use_saved_preferences="true")["results"][0]
    client.post(f"/api/saved/{job['id']}", headers=a_headers)
    assert client.get("/api/saved", headers=b_headers).json() == []
