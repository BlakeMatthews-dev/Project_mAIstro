"""
Authentication Interface — Provider-agnostic OIDC + API key auth.

Supports:
  - API key auth (homelab default — simple Bearer token)
  - OIDC token validation (any provider: Keycloak, Entra, Okta, Auth0, Google)
  - K8s service account tokens (for inter-service auth)

The auth middleware extracts identity and creates a TenantContext.
Provider-specific claim mapping is configured via environment variables,
not hardcoded.

Config:
  CONDUCTOR_AUTH_MODE: apikey | oidc | k8s | none
  CONDUCTOR_OIDC_ISSUER: https://login.microsoftonline.com/{tenant}/v2.0
  CONDUCTOR_OIDC_AUDIENCE: api://conductor
  CONDUCTOR_OIDC_JWKS_URI: (auto-discovered from issuer if not set)
  CONDUCTOR_OIDC_CLAIM_ORG: org_id (claim name for organization)
  CONDUCTOR_OIDC_CLAIM_TEAM: group (claim name for team)
  CONDUCTOR_OIDC_CLAIM_ROLES: roles (claim name for roles)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of authentication."""
    authenticated: bool
    user_id: str = ""
    claims: dict | None = None
    error: str = ""


class AuthProvider:
    """Provider-agnostic authentication."""

    def __init__(self) -> None:
        self._mode = os.environ.get("CONDUCTOR_AUTH_MODE", "apikey")
        self._api_key = os.environ.get("ROUTER_API_KEY", "")
        self._oidc_issuer = os.environ.get("CONDUCTOR_OIDC_ISSUER", "")
        self._oidc_audience = os.environ.get("CONDUCTOR_OIDC_AUDIENCE", "")
        self._jwks_client = None  # PyJWKClient, lazy-imported from jwt
        logger.info("Auth mode: %s", self._mode)

    async def authenticate(self, authorization: str | None) -> AuthResult:
        """Authenticate a request from the Authorization header."""
        if self._mode == "none":
            return AuthResult(authenticated=True, user_id="anonymous")

        if not authorization:
            return AuthResult(authenticated=False, error="Missing Authorization header")

        token = authorization.replace("Bearer ", "").strip()

        if self._mode == "apikey":
            return self._check_api_key(token)
        elif self._mode == "oidc":
            return await self._check_oidc(token)
        elif self._mode == "k8s":
            return await self._check_k8s_token(token)
        else:
            return AuthResult(authenticated=False, error=f"Unknown auth mode: {self._mode}")

    def _check_api_key(self, token: str) -> AuthResult:
        """Simple API key authentication."""
        if token == self._api_key:
            return AuthResult(
                authenticated=True,
                user_id="admin",
                claims={"roles": ["admin"], "sub": "admin"},
            )
        return AuthResult(authenticated=False, error="Invalid API key")

    async def _check_oidc(self, token: str) -> AuthResult:
        """Validate a JWT token against the OIDC provider's JWKS endpoint.

        Provider-agnostic: works with any OIDC-compliant issuer.
        """
        if not self._oidc_issuer:
            return AuthResult(authenticated=False, error="OIDC issuer not configured")

        try:
            import jwt
            from jwt import PyJWKClient

            if not self._jwks_client:
                jwks_uri = os.environ.get("CONDUCTOR_OIDC_JWKS_URI", "")
                if not jwks_uri:
                    # Auto-discover from issuer
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.get(
                            f"{self._oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
                        )
                        resp.raise_for_status()
                        jwks_uri = resp.json()["jwks_uri"]
                self._jwks_client = PyJWKClient(jwks_uri) # type: ignore[assignment]

            assert self._jwks_client is not None
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self._oidc_audience or None,
                issuer=self._oidc_issuer or None,
            )

            # Map provider-specific claims to standard fields
            claim_map = {
                "org_id": os.environ.get("CONDUCTOR_OIDC_CLAIM_ORG", "org_id"),
                "team_id": os.environ.get("CONDUCTOR_OIDC_CLAIM_TEAM", "group"),
                "roles": os.environ.get("CONDUCTOR_OIDC_CLAIM_ROLES", "roles"),
            }
            mapped = dict(claims)
            for standard, custom in claim_map.items():
                if custom in claims and standard != custom:
                    mapped[standard] = claims[custom]

            return AuthResult(
                authenticated=True,
                user_id=claims.get("sub", claims.get("email", "")),
                claims=mapped,
            )

        except ImportError:
            return AuthResult(
                authenticated=False,
                error="PyJWT not installed — pip install pyjwt[crypto]",
            )
        except Exception as exc:
            logger.debug("OIDC validation failed: %s", exc)
            return AuthResult(authenticated=False, error=str(exc))

    async def _check_k8s_token(self, token: str) -> AuthResult:
        """Validate a K8s service account token via the TokenReview API."""
        try:
            import httpx

            k8s_api = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
            k8s_port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
            ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
            sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"

            from pathlib import Path
            sa_token = Path(sa_token_path).read_text().strip() if Path(sa_token_path).exists() else ""

            async with httpx.AsyncClient(
                verify=ca_path if Path(ca_path).exists() else False,
                timeout=5,
            ) as client:
                resp = await client.post(
                    f"https://{k8s_api}:{k8s_port}/apis/authentication.k8s.io/v1/tokenreviews",
                    json={
                        "apiVersion": "authentication.k8s.io/v1",
                        "kind": "TokenReview",
                        "spec": {"token": token},
                    },
                    headers={"Authorization": f"Bearer {sa_token}"},
                )
                resp.raise_for_status()
                review = resp.json()

                status = review.get("status", {})
                if status.get("authenticated"):
                    user = status.get("user", {})
                    return AuthResult(
                        authenticated=True,
                        user_id=user.get("username", ""),
                        claims={"groups": user.get("groups", [])},
                    )

            return AuthResult(authenticated=False, error="K8s token not authenticated")
        except Exception as exc:
            logger.debug("K8s token validation failed: %s", exc)
            return AuthResult(authenticated=False, error=str(exc))
