"""Create a short-lived local bearer token for testing AUTH_MODE=jwt.

This is not an identity provider. Production deployments must use tokens from
the organization-approved provider and configure the matching validation key.
"""

import os
import time

import jwt


def main() -> None:
    key = os.environ.get("JWT_SIGNING_KEY")
    if not key:
        raise SystemExit("JWT_SIGNING_KEY is required")
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": os.environ.get("JWT_TEST_SUBJECT", "sujal"),
            "tenant_id": os.environ.get("JWT_TEST_TENANT", "acme"),
            "roles": os.environ.get("JWT_TEST_ROLES", "admin").split(","),
            "scope": os.environ.get("JWT_TEST_SCOPES", "private team company"),
            "iss": os.environ.get("JWT_ISSUER", "decisiongraph-local"),
            "aud": os.environ.get("JWT_AUDIENCE", "decisiongraph-api"),
            "iat": now,
            "exp": now + 900,
        },
        key,
        algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
    )
    print(token)


if __name__ == "__main__":
    main()
