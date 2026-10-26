"""Legacy Lattes-specific environment configuration, owned by its adapter."""
import os
from typing import Any

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
