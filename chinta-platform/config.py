from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformConfig:
    database_url: str | None
    admin_token: str | None
    port: int


def get_config() -> PlatformConfig:
    return PlatformConfig(
        database_url=os.environ.get("CHINTA_PLATFORM_DATABASE_URL"),
        admin_token=os.environ.get("CHINTA_PLATFORM_ADMIN_TOKEN"),
        port=int(os.environ.get("CHINTA_PLATFORM_PORT", "8085")),
    )
