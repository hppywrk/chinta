from unittest.mock import patch

from cli import build_parser, cmd_member_remove, cmd_member_set, cmd_user_get


def test_parser_user_create():
    parser = build_parser()
    args = parser.parse_args(["--output", "json", "user", "create", "--email", "a@b.c"])
    assert args.email == "a@b.c"
    assert args.output == "json"


def test_member_remove_user_id_path_is_quoted():
    """Traversal-like --user-id must not normalize onto another tenant."""
    parser = build_parser()
    evil = "../../11111111-1111-1111-1111-111111111111/memberships/22222222-2222-2222-2222-222222222222"
    args = parser.parse_args(
        ["member", "remove", "--tenant", "acme", "--user-id", evil]
    )
    with patch("cli._tenant_id_for_slug", return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"):
        with patch("cli._request") as mock_request:
            mock_request.return_value = None
            cmd_member_remove(args)
    path = mock_request.call_args.args[2]
    assert path.startswith("/v1/tenants/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/memberships/")
    # Slash must be percent-encoded so httpx cannot collapse "../..." into
    # DELETE /v1/tenants/<other>/memberships/<user>.
    assert "../" not in path
    assert "%2F" in path.upper()


def test_member_set_user_id_path_is_quoted():
    parser = build_parser()
    evil = "../../11111111-1111-1111-1111-111111111111/memberships/22222222-2222-2222-2222-222222222222"
    args = parser.parse_args(
        ["member", "set", "--tenant", "acme", "--user-id", evil, "--role", "admin"]
    )
    with patch("cli._tenant_id_for_slug", return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"):
        with patch("cli._request") as mock_request:
            mock_request.return_value = {"role_code": "admin"}
            with patch("cli._print_result"):
                cmd_member_set(args)
    path = mock_request.call_args.args[2]
    assert path.startswith("/v1/tenants/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/memberships/")
    assert "../" not in path
    assert "%2F" in path.upper()


def test_user_get_id_path_is_quoted():
    parser = build_parser()
    args = parser.parse_args(["user", "get", "--id", "../bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"])
    with patch("cli._request") as mock_request:
        mock_request.return_value = {"user_id": "x"}
        with patch("cli._print_result"):
            cmd_user_get(args)
    path = mock_request.call_args.args[2]
    assert path.startswith("/v1/users/")
    assert "../" not in path
    assert "%2F" in path.upper() or "%2E" in path.upper()
