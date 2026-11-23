def test_health_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_answers_head_for_uptime_monitors(client):
    response = client.head("/health")

    assert response.status_code == 200
    assert response.content == b""
