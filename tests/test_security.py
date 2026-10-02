"""Request guards: allowed host names (DNS rebinding) and cross-site rejection (CSRF)."""

from __future__ import annotations

import pytest

from helpers import open_app, upload

SAME_ORIGIN = {"Origin": "http://localhost"}
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
        {"Origin": "http://localhost:8999"},
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


REBIND_HOST = "rebind.attacker.test:8765"


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/health"), ("GET", "/api/documents"), ("POST", "/api/sync")]
)
def test_a_rebound_host_name_is_refused(client, method: str, path: str):
    # DNS rebinding: the attacker's page and the request both carry the attacker's domain.
    test_client, _ = client
    headers = {"Host": REBIND_HOST, "Origin": f"http://{REBIND_HOST}"}
    response = test_client.request(method, path, headers=headers)
    assert response.status_code == 400
    assert "ALLOWED_HOSTS" in response.json()["detail"]


@pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765", "LOCALHOST"])
def test_loopback_host_names_on_any_port_are_served(client, host: str):
    test_client, _ = client
    assert test_client.get("/api/config", headers={"Host": host}).status_code == 200


def test_an_origin_on_another_allowed_host_is_still_cross_site(client):
    test_client, _ = client
    headers = {"Host": "localhost:8765", "Origin": "http://127.0.0.1:8765"}
    assert test_client.post("/api/sync", headers=headers).status_code == 403


def test_extra_host_names_come_from_allowed_hosts(app_env: pytest.MonkeyPatch):
    app_env.setenv("ALLOWED_HOSTS", "renombrador.lan, 192.168.1.20")
    with open_app() as (test_client, _):
        lan = {"Host": "renombrador.lan:8765", "Origin": "http://renombrador.lan:8765"}
        assert test_client.post("/api/sync", headers=lan).status_code == 200
        assert test_client.get("/api/config", headers={"Host": "192.168.1.20"}).status_code == 200
        assert test_client.get("/api/config", headers={"Host": REBIND_HOST}).status_code == 400


# Fetch metadata a browser attaches to an <img> on another site.
CROSS_SITE_IMAGE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Dest": "image",
}


def test_another_site_cannot_mark_a_batch_as_exported(client):
    test_client, _ = client
    upload(test_client, ["a.pdf"], folder="Lote")

    image = test_client.get("/api/export", params={"scope": "all"}, headers=CROSS_SITE_IMAGE)
    assert image.status_code == 403
    record = test_client.post(
        "/api/export/record", json={"scope": "all", "folder": None}, headers=FOREIGN_ORIGIN
    )
    assert record.status_code == 403

    batches = test_client.get("/api/batches").json()["batches"]
    assert [batch["exported_at"] for batch in batches] == [None]


@pytest.mark.parametrize(
    "fetch",
    [
        CROSS_SITE_IMAGE,
        {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"},
        {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},
        {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        },
    ],
)
def test_other_sites_cannot_load_the_api(client, fetch: dict[str, str]):
    test_client, _ = client
    assert test_client.get("/api/documents", headers=fetch).status_code == 403


def test_other_sites_can_open_the_page_but_not_frame_it(client):
    # A launcher page on another port opens the app with a plain link: same-site, top level.
    test_client, _ = client
    link = {
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    assert test_client.get("/", headers=link).status_code == 200
    frame = {**link, "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "iframe"}
    assert test_client.get("/", headers=frame).status_code == 403
    own_page = {
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    assert test_client.get("/api/documents", headers=own_page).status_code == 200
