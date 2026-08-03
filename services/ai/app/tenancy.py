"""Tenant identity validation — the single choke point for tenant scoping.

Every RPC handler funnels the caller's TenantContext through
``validate_tenant_id`` before any Postgres or Neo4j access. Schema names are
derived, never received.
"""
from __future__ import annotations

import re

TENANT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SCHEMA_RE = re.compile(r"^tenant_[0-9a-f]{32}$")


class TenantValidationError(ValueError):
    pass


def validate_tenant_id(tenant_id: str) -> str:
    """Return the tenant id lowered, or raise. Rejects anything that is not a
    canonical lowercase UUID — no schema/Cypher metacharacters can pass."""
    if not isinstance(tenant_id, str):
        raise TenantValidationError("tenant_id must be a string")
    tid = tenant_id.strip().lower()
    if not TENANT_ID_RE.match(tid):
        raise TenantValidationError(f"invalid tenant_id: {tenant_id!r}")
    return tid


def schema_for(tenant_id: str) -> str:
    """Derive the Postgres schema name from a validated tenant id."""
    tid = validate_tenant_id(tenant_id)
    schema = "tenant_" + tid.replace("-", "")
    if not SCHEMA_RE.match(schema):  # defense in depth
        raise TenantValidationError(f"derived schema failed validation: {schema}")
    return schema
