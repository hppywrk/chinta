"""Shared fixtures for functional tests."""
import os

import httpx
import pytest

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8084")
NOTEBOOK_URL = os.environ.get("NOTEBOOK_URL", "http://localhost:8085")
AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:8083")


@pytest.fixture
def gateway():
    return httpx.Client(base_url=GATEWAY_URL, timeout=10.0)


@pytest.fixture
def notebook():
    return httpx.Client(base_url=NOTEBOOK_URL, timeout=10.0)


@pytest.fixture
def auth():
    return httpx.Client(base_url=AUTH_URL, timeout=10.0)
