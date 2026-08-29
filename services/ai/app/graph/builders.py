"""Tenant-safe Cypher composition.

Graph multi-tenancy model (single Neo4j database, property-based partitions):

  * ``public_law_graph``      — nodes labeled ``:Public`` (Statute, CaseLaw,
    Judgment, Opinion, Judge, GazetteNotice, Guideline …). No tenant_id.
    Shared, read-only for request-path code.
  * ``tenant_graph:<id>``     — every node and relationship carries
    ``tenant_id``. There is no way to compose a query over tenant data except
    through :class:`TenantScopedGraphQuery`, which injects the tenant filter
    into every pattern it emits — including an ``all(x IN nodes(p) …)`` guard
    on variable-length paths so multi-hop traversals cannot walk across
    tenants.

Raw Cypher is never accepted from callers. Labels, relationship types, and
property names are validated against fixed allowlists; values always travel
as bound parameters.

(When a deployment tier with Neo4j multi-database is available, ``Graph`` can
additionally pin a session database per tenant; the property filter stays on
as defense-in-depth.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..tenancy import validate_tenant_id

ALLOWED_TENANT_LABELS = frozenset(
    # File == the firm's own case/file; Archive == an uploaded firm
    # archive (a.k.a. "FirmArchive" in the spec). Submission/Advocate/Outcome
    # power the judge-reasoning graph (Tasks 3-4); all carry tenant_id.
    {"File", "Archive", "Party", "PrecedentNote", "Draft",
     "Submission", "Advocate", "Outcome"}
)
ALLOWED_PUBLIC_LABELS = frozenset(
    {"Statute", "CaseLaw", "Judgment", "Opinion", "Judge", "GazetteNotice",
     "Guideline", "CauseList", "Treaty", "Bill", "TribunalDecision"}
)
ALLOWED_RELS = frozenset(
    {"CITES", "INVOLVES", "SIMILAR_TO", "PART_OF", "AUTHORED", "AMENDS",
     "OVERTURNS", "DISTINGUISHES", "INTERPRETS", "LINKED_TO", "REFERS_TO",
     "HAS_OPINION", "SUPERSEDED_BY",
     # Judge/outcome reasoning + statutory lifecycle (Tasks 4-5).
     "FILED_IN", "RESULTED_IN", "DECIDED_BY", "RULED_ON", "REPEALS"}
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RETURN_EXPR_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
    r"|labels\([A-Za-z_][A-Za-z0-9_]*\)"
    r"|count\((?:\*|[A-Za-z_][A-Za-z0-9_]*)\))"
    r"(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_]*)?$",
    re.IGNORECASE,
)


class GraphQueryError(Exception):
    pass


@dataclass(frozen=True)
class GraphQuery:
    """A finished, executable query. Only the builders in this module can
    produce one — Graph.read/write refuse anything else."""

    cypher: str
    params: dict
    write: bool
    tenant_scoped: bool
    _builder_token: object = field(repr=False, default=None)


_TOKEN = object()  # module-private capability token


def _check_ident(name: str, what: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise GraphQueryError(f"invalid {what}: {name!r}")
    return name


def _check_label(label: str, public: bool) -> str:
    allowed = ALLOWED_PUBLIC_LABELS if public else ALLOWED_TENANT_LABELS
    if label not in allowed:
        raise GraphQueryError(f"label {label!r} not allowed for {'public' if public else 'tenant'} scope")
    return label


def _check_rels(rel_types: Sequence[str]) -> list[str]:
    rels = list(rel_types)
    if not rels:
        raise GraphQueryError("at least one relationship type required")
    for r in rels:
        if r not in ALLOWED_RELS:
            raise GraphQueryError(f"relationship type {r!r} not allowed")
    return rels


class _BaseBuilder:
    def __init__(self) -> None:
        self._matches: list[str] = []
        self._wheres: list[str] = []
        self._writes: list[str] = []
        self._returns: list[str] = []
        self._order: str = ""
        self._limit: Optional[int] = None
        self._params: dict[str, Any] = {}
        self._aliases: dict[str, bool] = {}  # alias -> is_public
        self._pcount = 0

    # -- params ------------------------------------------------------------
    def _bind(self, value: Any) -> str:
        self._pcount += 1
        key = f"p{self._pcount}"
        self._params[key] = value
        return f"${key}"

    # -- pattern fragments ---------------------------------------------------
    def _node_pattern(self, alias: str, label: Optional[str], public: bool, props: dict) -> str:
        _check_ident(alias, "alias")
        parts = [alias]
        if label is not None:
            parts.append(":" + _check_label(label, public))
            if public:
                parts.append(":Public")
        prop_frags = []
        if not public and self._tenant_filtered():
            prop_frags.append("tenant_id: $tenant_id")
        for key, value in props.items():
            _check_ident(key, "property")
            prop_frags.append(f"{key}: {self._bind(value)}")
        pattern = "".join(parts)
        if prop_frags:
            pattern += " {" + ", ".join(prop_frags) + "}"
        self._aliases[alias] = public
        return "(" + pattern + ")"

    def _tenant_filtered(self) -> bool:
        return False

    # -- clauses -------------------------------------------------------------
    def match(self, alias: str, label: str, public: bool = False, **props: Any) -> "_BaseBuilder":
        self._matches.append("MATCH " + self._node_pattern(alias, label, public, props))
        return self

    def match_rel(
        self,
        from_alias: str,
        rel_types: Sequence[str],
        to_alias: str,
        to_label: str,
        to_public: bool = False,
        direction: str = "any",
        **to_props: Any,
    ) -> "_BaseBuilder":
        """MATCH (from)-[:R1|R2]-(to:...). ``from_alias`` must already be bound."""
        if from_alias not in self._aliases:
            raise GraphQueryError(f"unbound alias {from_alias!r}")
        rels = "|".join(_check_rels(rel_types))
        left, right = ("-", "->") if direction == "out" else ("<-", "-") if direction == "in" else ("-", "-")
        to_pat = self._node_pattern(to_alias, to_label, to_public, to_props)
        self._matches.append(f"MATCH ({from_alias}){left}[:{rels}]{right}{to_pat}")
        return self

    def expand(
        self,
        from_alias: str,
        rel_types: Sequence[str],
        to_alias: str,
        max_hops: int,
        path_alias: str = "p",
    ) -> "_BaseBuilder":
        """Variable-length traversal. In tenant scope, a WHERE guard keeps
        every node on the path inside the tenant partition or the public
        graph — the invariant that makes multi-hop reasoning safe."""
        if from_alias not in self._aliases:
            raise GraphQueryError(f"unbound alias {from_alias!r}")
        _check_ident(to_alias, "alias")
        _check_ident(path_alias, "alias")
        if not 1 <= int(max_hops) <= 6:
            raise GraphQueryError("max_hops must be between 1 and 6")
        rels = "|".join(_check_rels(rel_types))
        self._matches.append(
            f"MATCH {path_alias} = ({from_alias})-[:{rels}*1..{int(max_hops)}]-({to_alias})"
        )
        if self._tenant_filtered():
            self._wheres.append(
                f"all(x IN nodes({path_alias}) WHERE x:Public OR x.tenant_id = $tenant_id)"
            )
        else:
            self._wheres.append(f"all(x IN nodes({path_alias}) WHERE x:Public)")
        self._aliases[to_alias] = False if self._tenant_filtered() else True
        return self

    def where_prop(self, alias: str, prop: str, op: str, value: Any) -> "_BaseBuilder":
        if alias not in self._aliases:
            raise GraphQueryError(f"unbound alias {alias!r}")
        _check_ident(prop, "property")
        if op not in ("=", "<>", "<", "<=", ">", ">=", "CONTAINS", "STARTS WITH"):
            raise GraphQueryError(f"operator {op!r} not allowed")
        self._wheres.append(f"{alias}.{prop} {op} {self._bind(value)}")
        return self

    def where_in(self, alias: str, prop: str, values: Sequence[Any]) -> "_BaseBuilder":
        if alias not in self._aliases:
            raise GraphQueryError(f"unbound alias {alias!r}")
        _check_ident(prop, "property")
        self._wheres.append(f"{alias}.{prop} IN {self._bind(list(values))}")
        return self

    def returns(self, *exprs: str) -> "_BaseBuilder":
        for e in exprs:
            if not _RETURN_EXPR_RE.match(e.strip()):
                raise GraphQueryError(f"return expression not allowed: {e!r}")
            self._returns.append(e.strip())
        return self

    def order_by(self, expr: str, desc: bool = False) -> "_BaseBuilder":
        if not _RETURN_EXPR_RE.match(expr.strip()):
            raise GraphQueryError(f"order expression not allowed: {expr!r}")
        self._order = f"ORDER BY {expr.strip()}" + (" DESC" if desc else "")
        return self

    def limit(self, n: int) -> "_BaseBuilder":
        self._limit = max(1, min(int(n), 500))
        return self

    # -- build ----------------------------------------------------------------
    def _assemble(self) -> str:
        if not self._matches and not self._writes:
            raise GraphQueryError("empty query")
        clauses = list(self._matches)
        if self._wheres:
            clauses.append("WHERE " + " AND ".join(self._wheres))
        clauses.extend(self._writes)
        if self._returns:
            clauses.append("RETURN " + ", ".join(self._returns))
        if self._order:
            clauses.append(self._order)
        if self._limit is not None:
            clauses.append(f"LIMIT {self._limit}")
        return "\n".join(clauses)


class TenantScopedGraphQuery(_BaseBuilder):
    """Composes Cypher for ONE tenant's partition. The tenant filter is not
    optional, not caller-supplied, and applied to every tenant-label pattern
    and every variable-length path."""

    def __init__(self, tenant_id: str) -> None:
        super().__init__()
        self.tenant_id = validate_tenant_id(tenant_id)
        self._params["tenant_id"] = self.tenant_id

    def _tenant_filtered(self) -> bool:
        return True

    # -- writes (tenant partition only) -----------------------------------
    def merge_node(self, alias: str, label: str, key_props: dict, set_props: Optional[dict] = None) -> "TenantScopedGraphQuery":
        pattern = self._node_pattern(alias, label, public=False, props=key_props)
        self._writes.append("MERGE " + pattern)
        sets = [f"{alias}.tenant_id = $tenant_id"]
        for key, value in (set_props or {}).items():
            _check_ident(key, "property")
            sets.append(f"{alias}.{key} = {self._bind(value)}")
        self._writes.append("SET " + ", ".join(sets))
        return self

    def merge_rel(self, from_alias: str, rel_type: str, to_alias: str) -> "TenantScopedGraphQuery":
        if from_alias not in self._aliases or to_alias not in self._aliases:
            raise GraphQueryError("both endpoints must be bound before merge_rel")
        [rel] = _check_rels([rel_type])
        # Relationships are also stamped so erasure can match on them.
        self._writes.append(
            f"MERGE ({from_alias})-[r_{rel.lower()}:{rel}]->({to_alias}) "
            f"SET r_{rel.lower()}.tenant_id = $tenant_id"
        )
        return self

    def match_public(self, alias: str, label: str, **props: Any) -> "TenantScopedGraphQuery":
        """Bind a PUBLIC node (e.g. the Statute a private note cites). Public
        nodes are never mutated from tenant scope — merge_node/merge_rel only
        target tenant aliases or create edges, never SET on public aliases."""
        self._matches.append("MATCH " + self._node_pattern(alias, label, public=True, props=props))
        return self

    def detach_delete(self, alias: str) -> "TenantScopedGraphQuery":
        """Delete tenant nodes — the WHERE tenant guard is forced here even
        though patterns already carry it (double lock for the destructive path)."""
        if alias not in self._aliases:
            raise GraphQueryError(f"unbound alias {alias!r}")
        if self._aliases[alias]:
            raise GraphQueryError("refusing to delete a public node from tenant scope")
        self._wheres.append(f"{alias}.tenant_id = $tenant_id")
        self._writes.append(f"DETACH DELETE {alias}")
        return self

    def build(self) -> GraphQuery:
        write = bool(self._writes)
        return GraphQuery(
            cypher=self._assemble(), params=dict(self._params),
            write=write, tenant_scoped=True, _builder_token=_TOKEN,
        )


class PublicGraphQuery(_BaseBuilder):
    """Read-only composition over the shared public law graph. There are no
    write methods on this class, and build() hard-fails if a write clause
    somehow appears. Public-corpus WRITES happen only in the ingestion
    pipeline via PublicCorpusWriter (internal batch path, not request path)."""

    def match(self, alias: str, label: str, public: bool = True, **props: Any) -> "PublicGraphQuery":
        if not public:
            raise GraphQueryError("PublicGraphQuery can only match public nodes")
        super().match(alias, label, public=True, **props)
        return self

    def match_rel(self, from_alias, rel_types, to_alias, to_label, to_public=True, direction="any", **to_props):
        if not to_public:
            raise GraphQueryError("PublicGraphQuery can only match public nodes")
        return super().match_rel(from_alias, rel_types, to_alias, to_label, True, direction, **to_props)

    def build(self) -> GraphQuery:
        if self._writes:
            raise GraphQueryError("PublicGraphQuery is read-only")
        return GraphQuery(
            cypher=self._assemble(), params=dict(self._params),
            write=False, tenant_scoped=False, _builder_token=_TOKEN,
        )


def is_builder_query(q: GraphQuery) -> bool:
    """Capability check used by Graph.read/write: only queries assembled by
    the builders in this module carry the private token."""
    return getattr(q, "_builder_token", None) is _TOKEN
