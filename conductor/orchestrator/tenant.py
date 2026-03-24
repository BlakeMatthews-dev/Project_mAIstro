"""
Tenant Context — Multi-user, multi-team isolation primitive.

Every operation in the conductor is scoped to a tenant. A tenant represents
an isolated workspace — it could be a user, a team, or an entire organization.

Hierarchy:
  Organization → Team → User
  org:acme      team:platform   user:alice

Each tenant gets:
  - Its own APM (personality, standing orders, guardrails)
  - Its own episodic memory (isolated PG schema or row-level filtering)
  - Its own skill allowlist and trust tier overrides
  - Its own message board and task queue
  - Its own heartbeat schedule
  - Access to shared T7 wisdom (read-only cross-tenant)

The tenant context flows through every component via dependency injection,
not global state. This is the foundation for K8s namespace-per-tenant deployment.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Context variable — set once per request/task, flows through async calls
_current_tenant: ContextVar["TenantContext"] = ContextVar("_current_tenant")


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context that flows through all operations."""

    tenant_id: str              # Unique identifier: "org:acme/team:platform/user:alice"
    org_id: str = ""            # Organization level
    team_id: str = ""           # Team level (optional)
    user_id: str = ""           # User level
    display_name: str = ""      # Human-readable name
    roles: tuple[str, ...] = () # RBAC roles: ("admin", "operator", "viewer")

    # Resource scoping
    namespace: str = ""         # K8s namespace (derived from tenant_id)
    db_schema: str = "public"   # PG schema for tenant isolation
    secrets_prefix: str = ""    # Prefix for secret names in vault

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def can_write(self) -> bool:
        return "admin" in self.roles or "operator" in self.roles

    @property
    def can_read(self) -> bool:
        return len(self.roles) > 0

    @classmethod
    def from_env(cls) -> TenantContext:
        """Create tenant context from environment variables.

        For single-user homelab: just reads CONDUCTOR_TENANT_ID.
        For K8s: reads from downward API / service account metadata.
        """
        tenant_id = os.environ.get("CONDUCTOR_TENANT_ID", "homelab")
        org_id = os.environ.get("CONDUCTOR_ORG_ID", "")
        team_id = os.environ.get("CONDUCTOR_TEAM_ID", "")
        user_id = os.environ.get("CONDUCTOR_USER_ID", "")
        namespace = os.environ.get("CONDUCTOR_NAMESPACE", tenant_id)
        db_schema = os.environ.get("CONDUCTOR_DB_SCHEMA", "public")

        return cls(
            tenant_id=tenant_id,
            org_id=org_id,
            team_id=team_id,
            user_id=user_id,
            display_name=os.environ.get("CONDUCTOR_DISPLAY_NAME", tenant_id),
            roles=tuple(os.environ.get("CONDUCTOR_ROLES", "admin").split(",")),
            namespace=namespace,
            db_schema=db_schema,
            secrets_prefix=f"{tenant_id}/",
        )

    @classmethod
    def from_oidc_claims(cls, claims: dict) -> TenantContext:
        """Create tenant context from OIDC token claims.

        Works with any OIDC provider (Entra, Keycloak, Okta, Auth0, Google).
        Maps standard claims to tenant fields.
        """
        # Standard OIDC claims
        sub = claims.get("sub", "")
        email = claims.get("email", "")
        name = claims.get("name", email)

        # Custom claims (provider-specific, mapped at the gateway level)
        org_id = claims.get("org_id", claims.get("tenant_id", ""))
        team_id = claims.get("team_id", claims.get("group", ""))
        roles = claims.get("roles", claims.get("realm_access", {}).get("roles", []))
        if isinstance(roles, str):
            roles = [roles]

        # Build tenant_id from hierarchy
        parts = []
        if org_id:
            parts.append(f"org:{org_id}")
        if team_id:
            parts.append(f"team:{team_id}")
        parts.append(f"user:{sub or email}")
        tenant_id = "/".join(parts)

        return cls(
            tenant_id=tenant_id,
            org_id=org_id,
            team_id=team_id,
            user_id=sub or email,
            display_name=name,
            roles=tuple(roles) if roles else ("viewer",),
            namespace=org_id or tenant_id,
            db_schema=org_id.replace("-", "_") if org_id else "public",
            secrets_prefix=f"{org_id}/" if org_id else "",
        )


def set_tenant(ctx: TenantContext) -> None:
    """Set the current tenant context for this async task."""
    _current_tenant.set(ctx)


def get_tenant() -> TenantContext:
    """Get the current tenant context. Falls back to env-based default."""
    try:
        return _current_tenant.get()
    except LookupError:
        default = TenantContext.from_env()
        _current_tenant.set(default)
        return default
