"""Funnel analytics and follow-up reminders."""

from datetime import datetime, timedelta, timezone

from app.config import settings


def _jobs(client, headers):
    return client.get(
        "/api/jobs/search", params={"use_saved_preferences": "true"}, headers=headers
    ).json()["results"]


def _apply_to(client, headers, jobs, n):
    return [
        client.post("/api/applications", json={"job_id": j["id"]}, headers=headers).json()["id"]
        for j in jobs[:n]
    ]


def test_empty_funnel_has_no_divide_by_zero(client, auth):
    headers, _, _ = auth()
    f = client.get("/api/analytics/funnel", headers=headers).json()
    assert f["total_applications"] == 0
    assert f["response_rate"] == 0.0
    assert f["median_days_to_response"] is None


def test_funnel_rates(client, auth):
    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 5)

    client.patch(f"/api/applications/{ids[0]}", json={"status": "interview"}, headers=headers)
    client.patch(f"/api/applications/{ids[1]}", json={"status": "offer"}, headers=headers)
    client.patch(f"/api/applications/{ids[2]}", json={"status": "rejected"}, headers=headers)

    f = client.get("/api/analytics/funnel", headers=headers).json()
    assert f["total_applications"] == 5
    assert f["responded"] == 3
    assert f["response_rate"] == 60.0
    assert f["offers"] == 1
    assert f["rejected"] == 1
    # 2 still 'applied' + 1 at interview are all non-terminal.
    assert f["awaiting_reply"] == 3


def test_interview_counted_from_history_not_current_status(client, auth):
    """An application that reached interview then got rejected is still an interview."""
    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 1)
    client.patch(f"/api/applications/{ids[0]}", json={"status": "interview"}, headers=headers)
    client.patch(f"/api/applications/{ids[0]}", json={"status": "rejected"}, headers=headers)

    f = client.get("/api/analytics/funnel", headers=headers).json()
    assert f["interviews"] == 1
    assert f["rejected"] == 1


def test_company_breakdown_sums_to_total(client, auth):
    headers, _, _ = auth()
    _apply_to(client, headers, _jobs(client, headers), 4)
    f = client.get("/api/analytics/funnel", headers=headers).json()
    assert sum(c["applications"] for c in f["companies"]) == 4


def test_weekly_series_has_twelve_buckets(client, auth):
    headers, _, _ = auth()
    _apply_to(client, headers, _jobs(client, headers), 2)
    f = client.get("/api/analytics/funnel", headers=headers).json()
    assert len(f["applications_over_time"]) == 12
    assert f["applications_over_time"][-1]["applications"] == 2


def test_analytics_is_per_user(client, auth):
    a_headers, _, _ = auth()
    b_headers, _, _ = auth()
    _apply_to(client, a_headers, _jobs(client, a_headers), 2)
    assert client.get("/api/analytics/funnel", headers=b_headers).json()["total_applications"] == 0


def test_analytics_requires_auth(client):
    assert client.get("/api/analytics/funnel").status_code == 401


def _age(db, app_id, days):
    from app.models import Application

    row = db.get(Application, app_id)
    row.status_updated_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()


def test_stale_application_is_flagged(client, auth, db):
    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 1)

    assert not client.get("/api/applications", headers=headers).json()[0]["needs_follow_up"]

    _age(db, ids[0], settings.follow_up_after_days + 3)
    row = client.get("/api/applications", headers=headers).json()[0]
    assert row["needs_follow_up"] is True
    assert row["days_since_update"] >= settings.follow_up_after_days


def test_finished_applications_are_never_nagged(client, auth, db):
    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 1)
    client.patch(f"/api/applications/{ids[0]}", json={"status": "offer"}, headers=headers)
    _age(db, ids[0], 400)

    row = client.get("/api/applications", headers=headers).json()[0]
    assert row["needs_follow_up"] is False


def test_status_change_clears_the_follow_up_flag(client, auth, db):
    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 1)
    _age(db, ids[0], settings.follow_up_after_days + 3)
    assert client.get("/api/applications", headers=headers).json()[0]["needs_follow_up"]

    client.patch(f"/api/applications/{ids[0]}", json={"status": "interview"}, headers=headers)
    assert not client.get("/api/applications", headers=headers).json()[0]["needs_follow_up"]


def test_reminders_send_once_then_respect_the_repeat_cadence(client, auth, db):
    from app.services.reminders import send_reminders

    headers, _, _ = auth()
    ids = _apply_to(client, headers, _jobs(client, headers), 1)
    _age(db, ids[0], settings.follow_up_after_days + 3)

    first = send_reminders(db)
    assert first["users_notified"] >= 1
    assert first["applications_flagged"] >= 1

    # Immediately re-running must not re-nag about the same application.
    second = send_reminders(db)
    assert second["applications_flagged"] == 0
