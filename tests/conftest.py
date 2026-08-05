"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from queryguard.api.main import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """HTTP client bound to the FastAPI app, with no network calls."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def nplus1_statement_log() -> str:
    """A real p6spy excerpt captured from the sandbox's N+1 fixture.

    Taken from an actual run rather than hand-written, so the parser is tested
    against the format p6spy really emits — including the setup chatter a real log
    carries.
    """
    return (FIXTURES / "p6spy" / "nplus1-excerpt.log").read_text(encoding="utf-8")
