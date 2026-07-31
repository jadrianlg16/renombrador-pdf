from __future__ import annotations

import importlib
import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PDF_INPUT_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("PDF_STATE_DIR", str(tmp_path / "state"))
    import app.main as main

    module = importlib.reload(main)
    with TestClient(module.app) as test_client:
        yield test_client, module
    importlib.reload(main)


def upload(test_client: TestClient, names: list[str], **data: str):
    files = [("files", (name, io.BytesIO(MINIMAL_PDF), "application/pdf")) for name in names]
    return test_client.post("/api/upload", files=files, data=data)


def test_upload_creates_batch_and_registers_documents(client):
    test_client, module = client
    response = upload(test_client, ["a.pdf", "sub/b.pdf"], folder="Escrituras 2026")
    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"] == "Escrituras 2026"
    assert payload["saved"] == 2
    assert payload["rejected"] == []

    inbox = module.settings.input_dir
    assert (inbox / "Escrituras 2026" / "a.pdf").is_file()
    assert (inbox / "Escrituras 2026" / "sub" / "b.pdf").is_file()

    documents = test_client.get("/api/documents").json()
    assert documents["total"] == 2
    assert documents["counts"]["pending"] == 2


def test_upload_appends_to_an_existing_batch(client):
    test_client, _ = client
    first = upload(test_client, ["a.pdf"], folder="Lote").json()
    second = upload(test_client, ["b.pdf"], batch=first["batch"]).json()
    assert second["batch"] == first["batch"]
    assert test_client.get("/api/documents").json()["total"] == 2


def test_upload_rejects_non_pdf_and_path_traversal(client):
    test_client, module = client
    response = upload(test_client, ["notas.txt", "../../escape.pdf"], folder="Lote")
    payload = response.json()
    assert payload["saved"] == 1
    assert [item["name"] for item in payload["rejected"]] == ["notas.txt"]
    # El .. se descarta y el archivo queda dentro del lote, nunca fuera de la bandeja.
    assert (module.settings.input_dir / "Lote" / "escape.pdf").is_file()
    assert not (module.settings.input_dir.parent / "escape.pdf").exists()


def test_upload_rejects_a_file_that_is_not_really_a_pdf(client):
    test_client, _ = client
    files = [("files", ("falso.pdf", io.BytesIO(b"no soy un pdf"), "application/pdf"))]
    payload = test_client.post("/api/upload", files=files, data={"folder": "Lote"}).json()
    assert payload["saved"] == 0
    assert payload["rejected"][0]["reason"] == "El archivo no es un PDF válido"


def test_export_returns_approved_files_with_their_new_names(client):
    test_client, _ = client
    upload(test_client, ["S-0001.pdf", "S-0002.pdf"], folder="Lote")
    documents = test_client.get("/api/documents").json()["documents"]

    approved = test_client.post(
        f"/api/documents/{documents[0]['id']}/approve", json={"name": "MARÍA GARCÍA"}
    )
    assert approved.status_code == 200

    empty_scope = test_client.get("/api/export", params={"scope": "approved", "folder": "otro"})
    assert empty_scope.status_code == 404

    response = test_client.get("/api/export", params={"scope": "approved", "folder": "Lote"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["MARÍA GARCÍA.pdf"]

    everything = test_client.get("/api/export", params={"scope": "all", "folder": "Lote"})
    with zipfile.ZipFile(io.BytesIO(everything.content)) as archive:
        assert sorted(archive.namelist()) == ["MARÍA GARCÍA.pdf", "S-0002.pdf"]


def test_export_across_batches_keeps_the_folder_prefix(client):
    test_client, _ = client
    upload(test_client, ["a.pdf"], folder="Lote A")
    upload(test_client, ["b.pdf"], folder="Lote B")
    response = test_client.get("/api/export", params={"scope": "all"})
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["Lote A/a.pdf", "Lote B/b.pdf"]


def test_deleting_a_batch_removes_its_files_and_documents(client):
    test_client, module = client
    upload(test_client, ["a.pdf", "sub/b.pdf"], folder="Lote A")
    upload(test_client, ["c.pdf"], folder="Lote B")
    assert test_client.get("/api/documents").json()["total"] == 3

    response = test_client.post("/api/batches/Lote A/delete")
    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == 2 and payload["documents"] == 2

    assert not (module.settings.input_dir / "Lote A").exists()
    assert (module.settings.input_dir / "Lote B" / "c.pdf").is_file()
    remaining = test_client.get("/api/documents").json()
    assert remaining["total"] == 1
    assert remaining["documents"][0]["current_relative_path"] == "Lote B/c.pdf"


def test_deleting_a_batch_frees_the_name_for_a_new_upload(client):
    test_client, module = client
    first = upload(test_client, ["a.pdf"], folder="Lote").json()
    assert first["batch"] == "Lote"
    test_client.post("/api/batches/Lote/delete")
    # Sin borrar, un segundo "Lote" se habria llamado "Lote (2)".
    second = upload(test_client, ["b.pdf"], folder="Lote").json()
    assert second["batch"] == "Lote"
    assert (module.settings.input_dir / "Lote" / "b.pdf").is_file()


def test_a_folder_already_in_the_tray_is_adopted_as_a_batch(client):
    test_client, module = client
    manual = module.settings.input_dir / "Ya estaba"
    manual.mkdir(parents=True)
    (manual / "original.pdf").write_bytes(MINIMAL_PDF)
    test_client.post("/api/sync")

    listed = {b["name"]: b for b in test_client.get("/api/batches").json()["batches"]}
    assert listed["Ya estaba"]["deletable"] is True
    assert listed["Ya estaba"]["source"] == "adopted"


def test_loose_pdfs_at_the_root_never_form_a_deletable_batch(client):
    test_client, module = client
    (module.settings.input_dir / "suelto.pdf").write_bytes(MINIMAL_PDF)
    test_client.post("/api/sync")

    listed = {b["name"]: b for b in test_client.get("/api/batches").json()["batches"]}
    assert listed[""]["deletable"] is False
    # La bandeja completa jamas se borra, ni con el nombre vacio.
    assert test_client.post("/api/batches//delete").status_code in (404, 400, 405, 307)
    assert (module.settings.input_dir / "suelto.pdf").is_file()


def test_uploading_into_an_adopted_batch_promotes_it(client):
    test_client, module = client
    manual = module.settings.input_dir / "Mixto"
    manual.mkdir(parents=True)
    (manual / "original.pdf").write_bytes(MINIMAL_PDF)
    test_client.post("/api/sync")
    assert test_client.get("/api/batches").json()["batches"][0]["source"] == "adopted"

    upload(test_client, ["nuevo.pdf"], batch="Mixto")
    listed = {b["name"]: b for b in test_client.get("/api/batches").json()["batches"]}
    assert listed["Mixto"]["source"] == "upload"


@pytest.mark.parametrize("target", ["..", "../..", "  ", "Lote/../..", "raiz"])
def test_delete_rejects_names_outside_the_whitelist(client, target: str):
    test_client, module = client
    upload(test_client, ["a.pdf"], folder="Lote")
    outside = module.settings.input_dir.parent / "no-tocar.pdf"
    outside.write_bytes(MINIMAL_PDF)

    response = test_client.post(f"/api/batches/{target}/delete")
    assert response.status_code in (404, 400, 405, 307)
    assert outside.is_file()
    assert module.settings.input_dir.is_dir()
    assert (module.settings.input_dir / "Lote" / "a.pdf").is_file()


def test_batches_endpoint_tracks_export_state(client):
    test_client, _ = client
    upload(test_client, ["a.pdf"], folder="Lote")
    documents = test_client.get("/api/documents").json()["documents"]
    test_client.post(f"/api/documents/{documents[0]['id']}/approve", json={"name": "ANA LOPEZ"})

    before = next(b for b in test_client.get("/api/batches").json()["batches"] if b["name"] == "Lote")
    assert before["approved"] == 1 and before["exported_at"] is None and before["deletable"] is True

    test_client.get("/api/export", params={"scope": "approved", "folder": "Lote"})
    after = next(b for b in test_client.get("/api/batches").json()["batches"] if b["name"] == "Lote")
    assert after["exported_at"] is not None


def test_latest_upload_points_at_the_most_recent_batch(client):
    test_client, _ = client
    upload(test_client, ["a.pdf"], folder="Primero")
    upload(test_client, ["b.pdf"], folder="Segundo")
    assert test_client.get("/api/batches").json()["latest_upload"] == "Segundo"


def test_documents_keep_a_stable_order_after_approving(client):
    test_client, _ = client
    upload(test_client, ["S-0001.pdf", "S-0002.pdf", "S-0003.pdf"], folder="Lote")
    before = [item["id"] for item in test_client.get("/api/documents").json()["documents"]]

    test_client.post(f"/api/documents/{before[0]}/approve", json={"name": "ZZZ ÚLTIMO"})
    after = [item["id"] for item in test_client.get("/api/documents").json()["documents"]]
    assert before == after
