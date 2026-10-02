"""Document endpoints: page rendering, review actions and their effect on disk."""

from __future__ import annotations

import pytesseract
import pytest

from helpers import open_app, upload


def _png_width(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(png[16:20], "big")


def test_page_images_use_the_configured_render_dpi(app_env: pytest.MonkeyPatch):
    app_env.setenv("PDF_RENDER_DPI", "100")
    with open_app() as (test_client, _):
        upload(test_client, ["a.pdf"], folder="Lote")
        document_id = test_client.get("/api/documents").json()["documents"][0]["id"]
        page_url = f"/api/documents/{document_id}/page/1"

        default = test_client.get(page_url)
        assert default.status_code == 200
        explicit = test_client.get(page_url, params={"dpi": 100})
        assert _png_width(default.content) == _png_width(explicit.content)
        sharper = test_client.get(page_url, params={"dpi": 150})
        assert _png_width(default.content) < _png_width(sharper.content)


def _fake_tesseract(*readings: tuple[str, float]):
    """Stand-in for pytesseract.image_to_data that answers each call with the next reading."""
    calls = {"count": 0}

    def image_to_data(*_args, **_kwargs) -> dict:
        text, confidence = readings[min(calls["count"], len(readings) - 1)]
        calls["count"] += 1
        words = text.split()
        return {
            "text": words,
            "conf": [str(confidence)] * len(words),
            "block_num": [1] * len(words),
            "par_num": [1] * len(words),
            "line_num": [1] * len(words),
            "word_num": list(range(1, len(words) + 1)),
        }

    return image_to_data


def _documents(test_client) -> list[dict]:
    return test_client.get("/api/documents").json()["documents"]


def _approve(test_client, document_id: str, name: str):
    return test_client.post(f"/api/documents/{document_id}/approve", json={"name": name})


def test_approving_renames_the_file_on_disk_and_logs_it(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    document = _documents(test_client)[0]

    response = _approve(test_client, document["id"], "MARÍA: GARCÍA")
    assert response.status_code == 200
    assert response.json()["after"] == "Lote/MARÍA GARCÍA.pdf"

    lote = module.settings.input_dir / "Lote"
    assert sorted(path.name for path in lote.iterdir()) == ["MARÍA GARCÍA.pdf"]
    assert _documents(test_client)[0]["status"] == "approved"
    actions = test_client.get("/api/history").json()["actions"]
    assert [action["action_type"] for action in actions] == ["rename"]


def test_approving_the_same_name_twice_never_overwrites(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf", "S-0002.pdf"], folder="Lote")
    first, second = _documents(test_client)

    _approve(test_client, first["id"], "ANA LOPEZ")
    assert (
        _approve(test_client, second["id"], "ANA LOPEZ").json()["filename"] == "ANA LOPEZ (2).pdf"
    )
    names = sorted(path.name for path in (module.settings.input_dir / "Lote").iterdir())
    assert names == ["ANA LOPEZ (2).pdf", "ANA LOPEZ.pdf"]


def test_undo_restores_renames_newest_first(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf", "S-0002.pdf"], folder="Lote")
    first, second = _documents(test_client)
    _approve(test_client, first["id"], "PRIMERO")
    _approve(test_client, second["id"], "SEGUNDO")

    assert test_client.post("/api/undo-last").json()["restored"] == "Lote/S-0002.pdf"
    assert test_client.post("/api/undo-last").json()["restored"] == "Lote/S-0001.pdf"
    assert test_client.post("/api/undo-last").status_code == 404

    names = sorted(path.name for path in (module.settings.input_dir / "Lote").iterdir())
    assert names == ["S-0001.pdf", "S-0002.pdf"]
    assert {document["status"] for document in _documents(test_client)} == {"pending"}


def test_undo_refuses_when_the_old_name_was_taken(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    _approve(test_client, _documents(test_client)[0]["id"], "ANA LOPEZ")
    lote = module.settings.input_dir / "Lote"
    (lote / "S-0001.pdf").write_bytes(b"%PDF-1.4 another file")

    response = test_client.post("/api/undo-last")
    assert response.status_code == 409
    assert (lote / "ANA LOPEZ.pdf").is_file()
    assert (lote / "S-0001.pdf").read_bytes() == b"%PDF-1.4 another file"


def test_skipping_keeps_the_file_and_logs_it(client):
    test_client, module = client
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    document_id = _documents(test_client)[0]["id"]

    assert test_client.post(f"/api/documents/{document_id}/skip").status_code == 200
    assert _documents(test_client)[0]["status"] == "skipped"
    assert (module.settings.input_dir / "Lote" / "S-0001.pdf").is_file()
    actions = test_client.get("/api/history").json()["actions"]
    assert [action["action_type"] for action in actions] == ["skip"]


SELECTION = {"page": 1, "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.05}


def test_ocr_proposes_a_name_without_renaming(client, monkeypatch: pytest.MonkeyPatch):
    test_client, module = client
    monkeypatch.setattr("app.ocr.pytesseract.image_to_data", _fake_tesseract(("ANA LOPEZ", 91)))
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    document_id = _documents(test_client)[0]["id"]

    response = test_client.post(
        f"/api/documents/{document_id}/ocr", json={"selections": [SELECTION]}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["joined_text"] == "ANA LOPEZ"
    assert result["needs_review"] is False

    stored = test_client.get(f"/api/documents/{document_id}").json()
    assert stored["proposed_name"] == "ANA LOPEZ" and stored["status"] == "pending"
    assert (module.settings.input_dir / "Lote" / "S-0001.pdf").is_file()


def test_ocr_without_tesseract_answers_503(client, monkeypatch: pytest.MonkeyPatch):
    test_client, _ = client

    def missing(*_args, **_kwargs):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr("app.ocr.pytesseract.image_to_data", missing)
    upload(test_client, ["S-0001.pdf"], folder="Lote")
    document_id = _documents(test_client)[0]["id"]

    response = test_client.post(
        f"/api/documents/{document_id}/ocr", json={"selections": [SELECTION]}
    )
    assert response.status_code == 503
    assert "TESSERACT_CMD" in response.json()["detail"]
