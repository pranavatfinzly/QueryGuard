"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """HTTP client bound to the FastAPI app, with no network calls."""
    with TestClient(app) as test_client:
        yield test_client
