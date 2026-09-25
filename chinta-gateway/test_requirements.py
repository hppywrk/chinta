"""Regression: gateway must declare httpx (used by /auth, /me, /api proxies).

PR #16 replaced httpx with pyyaml in requirements.txt when adding OpenAPI YAML
serving. A clean `pip install -r requirements.txt` then failed on `import httpx`,
so the container/local process never started.
"""
from pathlib import Path


def test_requirements_include_httpx_and_pyyaml():
    req = (Path(__file__).resolve().parent / "requirements.txt").read_text()
    assert "httpx" in req
    assert "pyyaml" in req


def test_httpx_importable_with_app():
    import httpx  # noqa: F401
    import app  # noqa: F401
