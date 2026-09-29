#!/usr/bin/env python3
"""CLI for chinta-platform admin APIs. See docs/ADMIN_V1.md."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8085"


def _base_url(args: argparse.Namespace) -> str:
    return (args.platform_url or os.environ.get("CHINTA_PLATFORM_URL") or DEFAULT_URL).rstrip("/")


def _token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("CHINTA_PLATFORM_ADMIN_TOKEN")
    if not token:
        print("error: set CHINTA_PLATFORM_ADMIN_TOKEN or --token", file=sys.stderr)
        sys.exit(2)
    return token


def _headers(args: argparse.Namespace) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(args)}"}


def _print_result(data: Any, output: str) -> None:
    if output == "json":
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            print(f"{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)


def _request(
    args: argparse.Namespace,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> Any:
    url = f"{_base_url(args)}{path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(method, url, headers=_headers(args), json=json_body)
    if resp.status_code == 204:
        return None
    try:
        payload = resp.json()
    except ValueError:
        payload = {"raw": resp.text}
    if resp.is_error:
        print(json.dumps(payload, indent=2), file=sys.stderr)
        sys.exit(1)
    return payload


def cmd_user_create(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"email": args.email}
    if args.name:
        body["display_name"] = args.name
    if args.sub:
        body["external_subject"] = args.sub
    data = _request(args, "POST", "/v1/users", json_body=body)
    _print_result(data, args.output)


def cmd_user_get(args: argparse.Namespace) -> None:
    if args.id:
        path = f"/v1/users/{args.id}"
    elif args.email:
        path = f"/v1/users/by-email/{args.email}"
    else:
        print("error: user get requires --id or --email", file=sys.stderr)
        sys.exit(2)
    _print_result(_request(args, "GET", path), args.output)


def cmd_tenant_create(args: argparse.Namespace) -> None:
    body = {
        "slug": args.slug,
        "display_name": args.name,
        "owner_user_id": args.owner_user_id,
    }
    _print_result(_request(args, "POST", "/v1/tenants", json_body=body), args.output)


def cmd_tenant_get(args: argparse.Namespace) -> None:
    if not args.slug:
        print("error: tenant get requires --slug", file=sys.stderr)
        sys.exit(2)
    _print_result(_request(args, "GET", f"/v1/tenants/by-slug/{args.slug}"), args.output)


def cmd_tenant_list(args: argparse.Namespace) -> None:
    data = _request(args, "GET", "/v1/tenants")
    items = data.get("items", data) if isinstance(data, dict) else data
    _print_result(items, args.output)


def _tenant_id_for_slug(args: argparse.Namespace, slug: str) -> str:
    tenant = _request(args, "GET", f"/v1/tenants/by-slug/{slug}")
    return tenant["tenant_id"]


def cmd_member_list(args: argparse.Namespace) -> None:
    tid = _tenant_id_for_slug(args, args.tenant)
    _print_result(_request(args, "GET", f"/v1/tenants/{tid}/memberships"), args.output)


def cmd_member_set(args: argparse.Namespace) -> None:
    tid = _tenant_id_for_slug(args, args.tenant)
    body = {"role_code": args.role, "membership_status": "ACTIVE"}
    _print_result(
        _request(args, "PUT", f"/v1/tenants/{tid}/memberships/{args.user_id}", json_body=body),
        args.output,
    )


def cmd_member_remove(args: argparse.Namespace) -> None:
    tid = _tenant_id_for_slug(args, args.tenant)
    _request(args, "DELETE", f"/v1/tenants/{tid}/memberships/{args.user_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chinta-admin", description="Chinta platform admin CLI")
    parser.add_argument("--platform-url", help="Platform base URL (or CHINTA_PLATFORM_URL)")
    parser.add_argument("--token", help="Admin token (or CHINTA_PLATFORM_ADMIN_TOKEN)")
    parser.add_argument("--output", choices=("json", "table"), default="table")

    sub = parser.add_subparsers(dest="command", required=True)

    user = sub.add_parser("user", help="Platform user commands")
    user_sub = user.add_subparsers(dest="user_cmd", required=True)

    u_create = user_sub.add_parser("create", help="Create platform user")
    u_create.add_argument("--email", required=True)
    u_create.add_argument("--name")
    u_create.add_argument("--sub", help="OIDC subject (external_subject)")
    u_create.set_defaults(func=cmd_user_create)

    u_get = user_sub.add_parser("get", help="Get platform user")
    u_get.add_argument("--id")
    u_get.add_argument("--email")
    u_get.set_defaults(func=cmd_user_get)

    tenant = sub.add_parser("tenant", help="Tenant commands")
    tenant_sub = tenant.add_subparsers(dest="tenant_cmd", required=True)

    t_create = tenant_sub.add_parser("create", help="Create tenant")
    t_create.add_argument("--slug", required=True)
    t_create.add_argument("--name", required=True)
    t_create.add_argument("--owner-user-id", required=True)
    t_create.set_defaults(func=cmd_tenant_create)

    t_get = tenant_sub.add_parser("get", help="Get tenant by slug")
    t_get.add_argument("--slug", required=True)
    t_get.set_defaults(func=cmd_tenant_get)

    t_list = tenant_sub.add_parser("list", help="List tenants")
    t_list.set_defaults(func=cmd_tenant_list)

    member = sub.add_parser("member", help="Membership commands")
    member_sub = member.add_subparsers(dest="member_cmd", required=True)

    m_list = member_sub.add_parser("list", help="List memberships")
    m_list.add_argument("--tenant", required=True, help="Tenant slug")
    m_list.set_defaults(func=cmd_member_list)

    m_set = member_sub.add_parser("set", help="Upsert membership")
    m_set.add_argument("--tenant", required=True)
    m_set.add_argument("--user-id", required=True)
    m_set.add_argument("--role", required=True, choices=("owner", "admin", "member", "viewer"))
    m_set.set_defaults(func=cmd_member_set)

    m_rm = member_sub.add_parser("remove", help="Remove membership")
    m_rm.add_argument("--tenant", required=True)
    m_rm.add_argument("--user-id", required=True)
    m_rm.set_defaults(func=cmd_member_remove)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
