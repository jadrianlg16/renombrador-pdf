"""Shared fixtures: a fresh app instance bound to a temporary inbox and state folder."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from helpers import open_app


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Point the app at a temporary inbox and state folder; returns monkeypatch for more env."""
    monkeypatch.setenv("PDF_INPUT_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("PDF_STATE_DIR", str(tmp_path / "state"))
    return monkeypatch


@pytest.fixture()
def client(app_env: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, ModuleType]]:
    """Yield a TestClient and the reloaded ``app.main`` module, isolated under tmp_path."""
    with open_app() as pair:
        yield pair
