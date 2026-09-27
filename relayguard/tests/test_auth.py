import pytest
from fastapi import HTTPException

from relayguard.services.auth import TenantAuthenticator


def test_matching_tenant_key_is_accepted() -> None:
    authenticator = TenantAuthenticator("api_key", '{"key-a":{"tenant_id":"acme","role":"viewer"}}')
    principal = authenticator.authenticate("key-a", "acme")
    assert principal.tenant_id == "acme"
    assert principal.role == "viewer"


def test_key_cannot_impersonate_another_tenant() -> None:
    authenticator = TenantAuthenticator("api_key", '{"key-a":{"tenant_id":"acme","role":"viewer"}}')
    with pytest.raises(HTTPException) as error:
        authenticator.authenticate("key-a", "globex")
    assert error.value.status_code == 403


def test_viewer_cannot_run_privileged_action() -> None:
    authenticator = TenantAuthenticator("api_key", '{"key-a":{"tenant_id":"acme","role":"viewer"}}')
    with pytest.raises(HTTPException) as error:
        authenticator.require_operator(authenticator.authenticate("key-a", "acme"))
    assert error.value.status_code == 403
