"""Test-wide guards.

The suite must never touch the network. Some of it exercises code whose job is
to call USGS, and a test that quietly made a real request would be slow,
flaky, dependent on a public service staying up, and would fail in CI. So the
socket layer is closed for the whole run and any accidental call fails loudly
rather than succeeding by luck.
"""

from __future__ import annotations

import socket

import pytest


class NetworkUsedInTests(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise NetworkUsedInTests(
            "A test tried to open a network connection. Upstream calls must be "
            "replaced, so that the suite is deterministic and runs offline."
        )

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    yield
