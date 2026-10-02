"""Shared fixtures: a fresh app instance bound to a temporary inbox and state folder."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, ModuleType]]:
    """Yield a TestClient and the reloaded ``app.main`` module, isolated under tmp_path."""
    monkeypatch.setenv("PDF_INPUT_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("PDF_STATE_DIR", str(tmp_path / "state"))
    import app.main as main

    module = importlib.reload(main)
    with TestClient(module.app) as test_client:
        yield test_client, module
    importlib.reload(main)
