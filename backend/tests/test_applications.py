"""Applications: creation, status history, ownership isolation."""

from sqlalchemy import select


def _jobs(client, headers):
    return client.get(
        "/api/jobs/search", params={"use_saved_preferences": "true"}, headers=headers
    ).json()["results"]


def test_applying_moves_a_job_off_the_shortlist(client, auth):
    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    client.post(f"/api/saved/{job['id']}", headers=headers)

    r = client.post("/api/applications", json={"job_id": job["id"]}, headers=headers)
    assert r.status_code == 201
    assert r.json()["status"] == "applied"
    assert client.get("/api/saved", headers=headers).json() == []


def test_duplicate_application_conflicts(client, auth):
    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    client.post("/api/applications", json={"job_id": job["id"]}, headers=headers)
    r = client.post("/api/applications", json={"job_id": job["id"]}, headers=headers)
    assert r.status_code == 409


def test_status_update_and_invalid_status(client, auth):
    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    app_id = client.post(
        "/api/applications", json={"job_id": job["id"]}, headers=headers
    ).json()["id"]

    r = client.patch(f"/api/applications/{app_id}", json={"status": "interview"}, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "interview"

    bad = client.patch(
        f"/api/applications/{app_id}", json={"status": "not_a_status"}, headers=headers
    )
    assert bad.status_code == 422


def test_notes_are_stripped_of_control_characters(client, auth):
    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    app_id = client.post(
        "/api/applications", json={"job_id": job["id"]}, headers=headers
    ).json()["id"]

    r = client.patch(
        f"/api/applications/{app_id}", json={"notes": "Recruiter: Sam\x00\x07"}, headers=headers
    )
    assert r.json()["notes"] == "Recruiter: Sam"


def test_status_transitions_are_recorded(client, auth, db):
    from app.models import ApplicationEvent, ApplicationStatus

    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    app_id = client.post(
        "/api/applications", json={"job_id": job["id"]}, headers=headers
    ).json()["id"]
    client.patch(f"/api/applications/{app_id}", json={"status": "online_assessment"}, headers=headers)
    client.patch(f"/api/applications/{app_id}", json={"status": "interview"}, headers=headers)

    events = list(
        db.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app_id)
            .order_by(ApplicationEvent.id)
        )
    )
    assert [e.to_status for e in events] == [
        ApplicationStatus.applied,
        ApplicationStatus.online_assessment,
        ApplicationStatus.interview,
    ]
    assert events[0].from_status is None


def test_another_user_cannot_see_or_touch_your_application(client, auth):
    a_headers, _, _ = auth()
    b_headers, _, _ = auth()

    job = _jobs(client, a_headers)[0]
    app_id = client.post(
        "/api/applications", json={"job_id": job["id"]}, headers=a_headers
    ).json()["id"]

    assert client.get("/api/applications", headers=b_headers).json() == []
    r = client.patch(f"/api/applications/{app_id}", json={"status": "offer"}, headers=b_headers)
    assert r.status_code == 404
    assert client.delete(f"/api/applications/{app_id}", headers=b_headers).status_code == 204
    # ...and it is still there for its real owner.
    assert len(client.get("/api/applications", headers=a_headers).json()) == 1


def test_delete_application(client, auth):
    headers, _, _ = auth()
    job = _jobs(client, headers)[0]
    app_id = client.post(
        "/api/applications", json={"job_id": job["id"]}, headers=headers
    ).json()["id"]
    assert client.delete(f"/api/applications/{app_id}", headers=headers).status_code == 204
    assert client.get("/api/applications", headers=headers).json() == []
