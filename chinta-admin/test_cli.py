from unittest.mock import patch

from cli import _tenant_id_for_slug, build_parser, cmd_user_get


def test_parser_user_create():
    parser = build_parser()
    args = parser.parse_args(["--output", "json", "user", "create", "--email", "a@b.c"])
    assert args.email == "a@b.c"
    assert args.output == "json"


def test_tenant_slug_path_is_quoted():
    """Traversal-like slugs must not normalize into GET /v1/tenants/{uuid}."""
    parser = build_parser()
    args = parser.parse_args(
        ["member", "list", "--tenant", "../11111111-1111-1111-1111-111111111111"]
    )
    with patch("cli._request") as mock_request:
        mock_request.return_value = {"tenant_id": "11111111-1111-1111-1111-111111111111"}
        _tenant_id_for_slug(args, args.tenant)
    path = mock_request.call_args.args[2]
    assert path.startswith("/v1/tenants/by-slug/")
    # Slash must be percent-encoded so httpx cannot collapse "../<uuid>" into
    # GET /v1/tenants/<uuid>. Dot is unreserved and may remain literal.
    assert "../" not in path
    assert "%2F" in path.upper()


def test_user_get_email_path_is_quoted():
    parser = build_parser()
    args = parser.parse_args(["user", "get", "--email", "a@b.c/../../tenants"])
    with patch("cli._request") as mock_request:
        mock_request.return_value = {"email": "a@b.c/../../tenants"}
        with patch("cli._print_result"):
            cmd_user_get(args)
    path = mock_request.call_args.args[2]
    assert path.startswith("/v1/users/by-email/")
    assert "/../../" not in path

