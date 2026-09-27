import json
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    role: str


class TenantAuthenticator:
    """Authenticates callers and enforces their tenant-bound role."""

    def __init__(self, mode: str, tenant_api_keys_json: str) -> None:
        self.mode = mode
        try:
            self.api_keys: dict[str, dict[str, str]] = json.loads(tenant_api_keys_json)
        except json.JSONDecodeError as error:
            raise ValueError("RELAYGUARD_TENANT_API_KEYS must be valid JSON.") from error

    def authenticate(self, api_key: str | None, requested_tenant: str | None = None) -> Principal:
        if self.mode == "off":
            return Principal(requested_tenant or "anonymous", "operator")
        if not api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header.")
        credential = next(
            (item for known_key, item in self.api_keys.items() if secrets.compare_digest(api_key, known_key)),
            None,
        )
        if not credential:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
        principal = Principal(credential["tenant_id"], credential["role"])
        if requested_tenant and requested_tenant != principal.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key is not authorized for the requested tenant.",
            )
        return principal

    @staticmethod
    def require_operator(principal: Principal) -> None:
        if principal.role != "operator":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This governed action requires an operator role.",
            )
