"""OAuth 2.0 Resource Server authentication and metadata configuration for StillDone MCP.

Provides deterministic configuration and Alexa+ compatibility for the
protected Streamable HTTP MCP endpoint:
- Resource Server boundary: StillDone is an OAuth Resource Server only.
  Does NOT act as an Authorization Server, does not mint tokens, and does
  not issue authorization codes.
- Token verification delegation via official MCP SDK TokenVerifier protocol.
- RFC 9728 Protected Resource Metadata (PRM) generation via official SDK.
- Alexa+ 401 compatibility: suppresses WWW-Authenticate on 401 responses
  for the Alexa+ judge profile, while leaving 403 / other responses intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    pass

# Truth boundary: External Authorization Server live compatibility is not proven in P-05.05.
# Current Alexa+ documentation (2026-10-01) defines a two-tier auth model for private MCP:
# - Tier 1: client_credentials (service-level / M2M, reserved scope 'mcp:service',
#   used for initialize, tools/list, service operations).
# - Tier 2: authorization_code + PKCE S256 (user-level authentication and consent).
# StillDone acts strictly as an OAuth Resource Server (RS); no Authorization Server is implemented,
# and external AS live compatibility remains classified as NOT_ESTABLISHED.
AUTHORIZATION_SERVER_LIVE_COMPATIBILITY: Final[str] = "NOT_ESTABLISHED"


@dataclass(frozen=True, slots=True)
class MCPAuthConfig:
    """Explicit immutable configuration for the OAuth resource-server boundary.

    Defines parameters for authenticating callers to the protected MCP endpoint
    and publishing RFC 9728 Protected Resource Metadata (PRM).

    Resource Server Law:
    - StillDone is an OAuth Resource Server only. It does NOT mint tokens, issue
      authorization codes, provide login/consent UI, or act as an Authorization Server.
    - Token verification is delegated to an external TokenVerifier implementation.
    - External Authorization Server live compatibility is classified as NOT_ESTABLISHED.
    """

    issuer_url: str
    resource_server_url: str
    required_scopes: tuple[str, ...] = ("stilldone:mcp",)
    validate_token_resource: bool = True
    alexa_profile: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.issuer_url, str) or not self.issuer_url.strip():
            raise ValueError("issuer_url must be a non-empty string")
        if not (self.issuer_url.startswith("http://") or self.issuer_url.startswith("https://")):
            raise ValueError("issuer_url must start with http:// or https://")

        if not isinstance(self.resource_server_url, str) or not self.resource_server_url.strip():
            raise ValueError("resource_server_url must be a non-empty string")
        if not (
            self.resource_server_url.startswith("http://")
            or self.resource_server_url.startswith("https://")
        ):
            raise ValueError("resource_server_url must start with http:// or https://")

        if not isinstance(self.required_scopes, (tuple, list)):
            raise TypeError("required_scopes must be a tuple or list of strings")
        if len(self.required_scopes) == 0:
            raise ValueError("required_scopes must be a non-empty collection of strings")

        seen_scopes: set[str] = set()
        cleaned_scopes: list[str] = []
        for s in self.required_scopes:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("All required scopes must be non-empty strings")
            stripped = s.strip()
            if stripped in seen_scopes:
                raise ValueError(f"Duplicate scope '{stripped}' in required_scopes")
            seen_scopes.add(stripped)
            cleaned_scopes.append(stripped)

        object.__setattr__(self, "required_scopes", tuple(cleaned_scopes))

        if not isinstance(self.validate_token_resource, bool):
            raise TypeError("validate_token_resource must be a boolean")

        if not isinstance(self.alexa_profile, bool):
            raise TypeError("alexa_profile must be a boolean")

    def to_sdk_auth_settings(self) -> AuthSettings:
        """Convert to official MCP SDK AuthSettings model."""
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer_url),
            resource_server_url=AnyHttpUrl(self.resource_server_url),
            required_scopes=list(self.required_scopes),
            validate_token_resource=self.validate_token_resource,
        )


class Alexa401CompatibilityMiddleware:
    """Bounded ASGI compatibility layer suppressing WWW-Authenticate on HTTP 401 responses.

    Platform Compatibility Rationale:
    - Official MCP Python SDK emits WWW-Authenticate header on 401 responses
      per RFC 6750 / RFC 9728.
    - Current Alexa+ specification explicitly requires that HTTP 401 responses
      must NOT contain the WWW-Authenticate header.
    - This middleware intercepts outgoing HTTP responses:
      - If status == 401: suppresses the WWW-Authenticate header.
      - If status == 403 (or any other status): leaves headers intact.
      - Preserves authentication strength, response body, and status codes.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status") == 401:
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                filtered_headers = [
                    (name, value)
                    for name, value in raw_headers
                    if name.lower() != b"www-authenticate"
                ]
                new_message = dict(message)
                new_message["headers"] = filtered_headers
                await send(new_message)
            else:
                await send(message)

        await self.app(scope, receive, send_wrapper)


class SyntheticTokenVerifier(TokenVerifier):
    """Test-only synthetic token verifier.

    DO NOT USE IN PRODUCTION.
    This is an in-memory fixture for LOCAL_EXECUTION test verification only.
    """

    def __init__(
        self,
        valid_tokens: dict[str, AccessToken] | None = None,
    ) -> None:
        self._tokens: dict[str, AccessToken] = (
            dict(valid_tokens) if valid_tokens is not None else {}
        )

    def register_token(self, token: str, access_token: AccessToken) -> None:
        self._tokens[token] = access_token

    def revoke_token(self, token: str) -> None:
        self._tokens.pop(token, None)

    async def verify_token(self, token: str) -> AccessToken | None:
        return self._tokens.get(token)


def get_expected_prm_path(resource_url: str) -> str:
    """Calculate the RFC 9728 well-known protected resource metadata path."""
    parsed = urlparse(resource_url)
    res_path = parsed.path.rstrip("/")
    return f"/.well-known/oauth-protected-resource{res_path}"
