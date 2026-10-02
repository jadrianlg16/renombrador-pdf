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
