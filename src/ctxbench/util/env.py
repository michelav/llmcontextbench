from __future__ import annotations

import os
import re
from typing import Any


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
# MCP server fields that carry credentials. Their placeholders stay unresolved in plans and trial specs and are
# resolved only when a request is built (resolve_secret_params), so no credential is written to disk.
SECRET_MCP_FIELDS = ("auth_token", "authorization", "headers")
REDACTED = "[REDACTED]"


def resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        return _resolve_string(value)
    if isinstance(value, list):
        return [resolve_env_placeholders(item) for item in value]
    if isinstance(value, dict):
        env_name = value.get("$env")
        if isinstance(env_name, str):
            default = value.get("default")
            return _resolve_env_var(env_name, default if default is None or isinstance(default, str) else str(default))
        return {key: resolve_env_placeholders(item) for key, item in value.items()}
    return value


def resolve_plan_params(value: dict[str, Any]) -> dict[str, Any]:
    """Resolve placeholders except in the MCP server's credential fields, which are only checked."""
    config = value.get("mcp_server")
    if not isinstance(config, dict):
        return resolve_env_placeholders(value)
    secret = {key: config[key] for key in SECRET_MCP_FIELDS if key in config}
    resolve_env_placeholders(secret)
    resolved = resolve_env_placeholders({**value, "mcp_server": {k: v for k, v in config.items() if k not in secret}})
    resolved["mcp_server"] = {**resolved["mcp_server"], **secret}
    return resolved


def resolve_secret_params(value: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Resolve the MCP server's credential fields; return the params and the resolved values to redact."""
    config = value.get("mcp_server")
    if not isinstance(config, dict):
        return value, []
    resolved = dict(config)
    secrets: list[str] = []
    for key in SECRET_MCP_FIELDS:
        if key not in config:
            continue
        resolved[key] = resolve_env_placeholders(config[key])
        if isinstance(resolved[key], dict):
            secrets += [item for name, item in resolved[key].items()
                        if isinstance(item, str) and item != config[key].get(name)]
        elif isinstance(resolved[key], str) and resolved[key] != config[key]:
            secrets.append(resolved[key])
    secrets += [item.removeprefix("Bearer ") for item in secrets if item.startswith("Bearer ")]
    return {**value, "mcp_server": resolved}, sorted({item for item in secrets if item}, key=len, reverse=True)


def redact_secrets(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: redact_secrets(item, secrets) for key, item in value.items()}
    return value


def apply_lattes_mcp_env_overrides(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    config = value.get("mcp_server")
    if not isinstance(config, dict):
        return value

    resolved = dict(config)
    server_url = os.getenv("LATTES_MCP_URL")
    auth_token = "${LATTES_MCP_TOKEN}" if os.getenv("LATTES_MCP_TOKEN") else None

    if server_url:
        resolved["server_url"] = server_url
        resolved.pop("url", None)
    if auth_token:
        resolved["auth_token"] = auth_token
        headers = dict(resolved.get("headers") or {})
        headers.pop("Authorization", None)
        headers.pop("authorization", None)
        resolved["headers"] = headers

    if "authorization" in resolved and "auth_token" not in resolved:
        resolved["auth_token"] = resolved.pop("authorization")
    else:
        resolved.pop("authorization", None)

    auth_token_value = resolved.get("auth_token")
    if isinstance(auth_token_value, str) and auth_token_value:
        headers = dict(resolved.get("headers") or {})
        headers.pop("Authorization", None)
        headers.pop("authorization", None)
        resolved["headers"] = headers

    payload = dict(value)
    payload["mcp_server"] = resolved
    return payload


def _resolve_string(value: str) -> str:
    match = _ENV_PATTERN.fullmatch(value)
    if match:
        env_name, default = match.groups()
        return _resolve_env_var(env_name, default)

    def replace(match_obj: re.Match[str]) -> str:
        env_name, default = match_obj.groups()
        return _resolve_env_var(env_name, default)

    return _ENV_PATTERN.sub(replace, value)


def _resolve_env_var(name: str, default: str | None = None) -> str:
    env_value = os.getenv(name)
    if env_value is not None:
        return env_value
    if default is not None:
        return default
    raise ValueError(f"Missing required environment variable: {name}")
