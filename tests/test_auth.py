import time

import jwt
import pytest
from starlette.requests import Request

from decisiongraph.core.config import Settings
from decisiongraph.operations.auth import AuthContext, authenticate_bearer_token, authorize_request


def request_with_headers(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
        }
    )


def test_jwt_authentication_derives_identity_from_valid_claims():
    key = "test-secret-with-at-least-thirty-two-characters"
    settings = Settings(auth_mode="jwt", jwt_signing_key=key)
    token = jwt.encode(
        {
            "sub": "sujal",
            "tenant_id": "acme",
            "roles": ["reader"],
            "scope": "team",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": int(time.time()) + 60,
        },
        key,
        algorithm="HS256",
    )
    context = authenticate_bearer_token(
        request_with_headers({"authorization": f"Bearer {token}"}), settings
    )
    assert context.subject == "sujal"
    assert context.tenant_id == "acme"
    assert context.roles == {"reader"}
    assert context.scopes == {"team"}


def test_authorization_rejects_cross_tenant_and_missing_role():
    request = request_with_headers({})
    request.state.auth_context = AuthContext(
        "sujal", "acme", frozenset({"reader"}), frozenset({"team"}), "jwt"
    )
    with pytest.raises(Exception) as tenant_error:
        authorize_request(request, "other", "sujal", ["team"], "reader")
    assert tenant_error.value.status_code == 403
    with pytest.raises(Exception) as role_error:
        authorize_request(request, "acme", "sujal", ["team"], "reviewer")
    assert role_error.value.status_code == 403
