"""The page shell: index, favicon and the static files the index links to."""

from __future__ import annotations

import re


def test_index_links_only_to_static_files_that_exist(client):
    test_client, _ = client
    index = test_client.get("/")
    assert index.status_code == 200
    links = re.findall(r'(?:href|src)="(/[^"?]+)', index.text)
    assert "/static/app.js" in links and "/static/styles.css" in links
    for link in links:
        assert test_client.get(link).status_code == 200, link


def test_favicon_is_served(client):
    test_client, _ = client
    response = test_client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"
    assert response.content[:4] == b"\x00\x00\x01\x00"


def test_the_page_forbids_framing_and_foreign_resources(client):
    test_client, _ = client
    headers = test_client.get("/").headers
    policy = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in policy and "default-src 'self'" in policy
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "same-origin"


def test_every_response_gets_nosniff_including_refusals(client):
    test_client, _ = client
    for response in (
        test_client.get("/api/config"),
        test_client.get("/api/config", headers={"Host": "evil.example"}),
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"


def test_no_interactive_docs_that_would_load_a_cdn(client):
    test_client, _ = client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert test_client.get(path).status_code == 404
