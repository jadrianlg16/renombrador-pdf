"""Cross-site request rejection (CSRF) on the HTTP API."""

from __future__ import annotations

import pytest

from helpers import upload

SAME_ORIGIN = {"Origin": "http://testserver"}
FOREIGN_ORIGIN = {"Origin": "https://evil.example"}


def test_same_origin_writes_are_accepted(client):
    test_client, _ = client
    assert test_client.post("/api/sync", headers=SAME_ORIGIN).status_code == 200
    with_fetch_metadata = {**SAME_ORIGIN, "Sec-Fetch-Site": "same-origin"}
    response = test_client.post("/api/sync", headers=with_fetch_metadata)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path", ["/api/sync", "/api/undo-last", "/api/batches/Lote/delete", "/api/documents/x/skip"]
)
def test_body_less_posts_from_a_foreign_origin_are_rejected(client, path: str):
    test_client, _ = client
    response = test_client.post(path, headers=FOREIGN_ORIGIN)
    assert response.status_code == 403


def test_a_foreign_origin_cannot_delete_a_batch(client):
    test_client, module = client
    upload(test_client, ["a.pdf"], folder="Lote")
    response = test_client.post("/api/batches/Lote/delete", headers=FOREIGN_ORIGIN)
    assert response.status_code == 403
    assert (module.settings.input_dir / "Lote" / "a.pdf").is_file()


def test_a_foreign_origin_cannot_approve_or_upload(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    document = test_client.get("/api/documents").json()["documents"][0]

    approve = test_client.post(
        f"/api/documents/{document['id']}/approve",
        json={"name": "ANA LOPEZ"},
        headers=FOREIGN_ORIGIN,
    )
    assert approve.status_code == 403
    assert (module.settings.input_dir / "Lote" / "S-0001.pdf").is_file()

    test_client.headers.update(FOREIGN_ORIGIN)
    try:
        assert upload(test_client, ["b.pdf"], folder="Otro").status_code == 403
    finally:
        del test_client.headers["Origin"]
    assert not (module.settings.input_dir / "Otro").exists()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "null"},
        {"Origin": "http://testserver:8999"},
        {"Origin": "http://127.0.0.1"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_other_cross_site_signals_are_rejected(client, headers: dict[str, str]):
    test_client, _ = client
    assert test_client.post("/api/sync", headers=headers).status_code == 403


def test_clients_that_send_no_origin_are_allowed(client):
    # curl, scripts and the test client send neither Origin nor Sec-Fetch-Site. A web
    # page cannot make a browser drop them, so these requests are not a CSRF vector.
    test_client, _ = client
    response = test_client.post("/api/sync")
    assert response.status_code == 200


def test_reads_are_not_blocked_by_origin(client):
    test_client, _ = client
    assert test_client.get("/api/documents", headers=FOREIGN_ORIGIN).status_code == 200
