"""Stateless cloud-native configuration for Smriti v2 core engine."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AppConfig(BaseModel):
    """Immutable runtime settings populated strictly from environment variables."""

    model_config = ConfigDict(frozen=True)

    env: Literal["dev", "staging", "prod"] = "dev"
    service_name: str = "smriti-v2"
    version: str = "0.1.0"
    default_domain: str | None = None
    require_auth: bool = False
    trust_cloud_run_iam_bearer: bool = False

    @classmethod
    def from_env(cls) -> AppConfig:
        raw_env = os.getenv("SMRITI_ENV", "dev").strip().lower()
        env_val: Literal["dev", "staging", "prod"] = (
            raw_env if raw_env in {"dev", "staging", "prod"} else "dev"  # type: ignore[assignment]
        )
        raw_default_domain = os.getenv("SMRITI_DEFAULT_DOMAIN")
        default_domain = raw_default_domain.strip() if raw_default_domain else None
        on_cloud_run = bool(os.getenv("K_SERVICE", "").strip())

        return cls(
            env=env_val,
            service_name=os.getenv("SMRITI_SERVICE_NAME", "smriti-v2").strip(),
            version=os.getenv("SMRITI_VERSION", "0.1.0").strip(),
            default_domain=default_domain or None,
            require_auth=_parse_bool(
                os.getenv("SMRITI_REQUIRE_AUTH"),
                default=(env_val == "prod"),
            ),
            trust_cloud_run_iam_bearer=_parse_bool(
                os.getenv("SMRITI_TRUST_CLOUD_RUN_BEARER"),
                default=on_cloud_run,
            ),
        )
