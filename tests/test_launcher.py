from __future__ import annotations

import socket

import pytest

from launcher import find_available_port, port_is_available


def test_port_is_available_for_temporary_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert port_is_available("127.0.0.1", port)


def test_find_available_port_rejects_occupied_requested_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        with pytest.raises(RuntimeError, match="ocupado"):
            find_available_port("127.0.0.1", port)
