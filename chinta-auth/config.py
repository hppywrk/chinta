"""OIDC configuration from environment."""
import os


def get_config():
    return {
        "issuer": os.environ.get("OIDC_ISSUER", "https://accounts.google.com"),
        "client_id": os.environ.get("OIDC_CLIENT_ID", ""),
        "client_secret": os.environ.get("OIDC_CLIENT_SECRET", ""),
        "redirect_uri_base": os.environ.get("OIDC_REDIRECT_URI_BASE", "http://localhost:8083"),
    }
