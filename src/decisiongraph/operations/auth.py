"""Authentication and authorization primitives for DecisionGraph API requests.

Development mode deliberately preserves the frictionless local workflow. Shared
deployments use a bearer JWT minted by the organization's identity provider.
The API validates its signature and then derives the tenant, user, scopes and
roles from claims rather than trusting client-supplied request fields.
"""

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError


@dataclass(frozen=True)
class AuthContext:
    subject: str | None
    tenant_id: str | None
    roles: frozenset[str]
    scopes: frozenset[str]
    mode: str

    @property
    def is_development(self) -> bool:
        return self.mode == "development"


def authenticate_bearer_token(request: Request, settings) -> AuthContext:
    """Validate a signed JWT or return an explicit local-development context."""
    if settings.auth_mode == "development":
        return AuthContext(None, None, frozenset({"admin"}), frozenset(), "development")

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A bearer access token is required")
    if not settings.jwt_signing_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "JWT signing key is not configured"
        )
    try:
        claims = jwt.decode(
            token,
            settings.jwt_signing_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "sub", "tenant_id"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired bearer token"
        ) from exc

    scope_claim = claims.get("scope", claims.get("scopes", []))
    scopes = scope_claim.split() if isinstance(scope_claim, str) else scope_claim
    role_claim = claims.get("roles", claims.get("role", []))
    roles = [role_claim] if isinstance(role_claim, str) else role_claim
    if not isinstance(scopes, list) or not isinstance(roles, list):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Bearer token has invalid role or scope claims"
        )
    return AuthContext(
        subject=str(claims["sub"]),
        tenant_id=str(claims["tenant_id"]),
        roles=frozenset(str(role) for role in roles),
        scopes=frozenset(str(scope) for scope in scopes),
        mode="jwt",
    )


def authorize_request(
    request: Request,
    tenant_id: str,
    user_id: str | None,
    requested_scopes: list[str] | None,
    required_role: str,
) -> None:
    """Enforce tenant isolation, actor identity, document scopes and least privilege."""
    context: AuthContext = request.state.auth_context
    if context.is_development:
        return
    if context.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token tenant does not match request tenant")
    if user_id is not None and context.subject != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token subject does not match request user")
    if "admin" not in context.roles and required_role not in context.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Role '{required_role}' is required")
    if (
        requested_scopes
        and "admin" not in context.roles
        and not set(requested_scopes).issubset(context.scopes)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Token scopes do not permit the requested access"
        )
