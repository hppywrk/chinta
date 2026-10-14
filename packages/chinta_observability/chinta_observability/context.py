from __future__ import annotations

from contextvars import ContextVar

_request_id_var: ContextVar[str | None] = ContextVar("chinta_request_id", default=None)
_service_name_var: ContextVar[str | None] = ContextVar("chinta_service_name", default=None)


def set_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_service_name(service_name: str) -> None:
    _service_name_var.set(service_name)


def get_service_name() -> str | None:
    return _service_name_var.get()
