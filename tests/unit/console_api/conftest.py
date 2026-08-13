from __future__ import annotations

import pytest
from console_api.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def mock_app():
    return create_app(mock=True)


@pytest.fixture
def client(mock_app):
    with TestClient(mock_app) as test_client:
        yield test_client
