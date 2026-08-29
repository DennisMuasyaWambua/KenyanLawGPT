"""Unit tests for the tenant-isolation invariants of the graph query builders.

These are the load-bearing guarantees: every tenant-scope pattern carries the
tenant filter, variable-length traversals are guarded node-by-node, the public
builder cannot write, and nothing outside the builders can execute.
"""
import pytest

from app.graph.builders import (
    GraphQuery,
    GraphQueryError,
    PublicGraphQuery,
    TenantScopedGraphQuery,
    is_builder_query,
)

TID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_tenant_match_always_injects_tenant_filter():
    q = TenantScopedGraphQuery(TID_A).match("m", "File", id="m-1").returns("m.id").build()
    assert "tenant_id: $tenant_id" in q.cypher
    assert q.params["tenant_id"] == TID_A
    assert q.tenant_scoped


def test_every_tenant_pattern_is_filtered_not_just_the_first():
    q = (TenantScopedGraphQuery(TID_A)
         .match("m", "File", id="m-1")
         .match_rel("m", ["LINKED_TO"], "d", "Archive")
         .returns("d.id").build())
    assert q.cypher.count("tenant_id: $tenant_id") == 2


def test_var_length_expand_guards_every_node_on_the_path():
    q = (TenantScopedGraphQuery(TID_A)
         .match("m", "File", id="m-1")
         .expand("m", ["CITES", "SIMILAR_TO"], "n", max_hops=3)
         .returns("n.id").build())
    assert "all(x IN nodes(p) WHERE x:Public OR x.tenant_id = $tenant_id)" in q.cypher


def test_tenant_writes_stamp_tenant_id_on_nodes_and_relationships():
    q = (TenantScopedGraphQuery(TID_A)
         .merge_node("d", "Archive", {"id": "doc-1"}, {"filename": "x.txt"})
         .merge_node("m", "File", {"id": "m-1"})
         .merge_rel("m", "LINKED_TO", "d")
         .build())
    assert q.write
    assert "d.tenant_id = $tenant_id" in q.cypher
    assert "m.tenant_id = $tenant_id" in q.cypher
    assert "r_linked_to.tenant_id = $tenant_id" in q.cypher


def test_tenant_delete_refuses_public_nodes():
    b = TenantScopedGraphQuery(TID_A).match_public("s", "Statute", doc_id="act-1")
    with pytest.raises(GraphQueryError):
        b.detach_delete("s")


def test_tenant_id_is_validated_at_construction():
    with pytest.raises(Exception):
        TenantScopedGraphQuery("nope' OR 1=1 //")


def test_labels_and_rels_are_allowlisted():
    b = TenantScopedGraphQuery(TID_A)
    with pytest.raises(GraphQueryError):
        b.match("x", "User")  # not a tenant graph label
    with pytest.raises(GraphQueryError):
        b.match("m", "File").match_rel("m", ["HACKED"], "d", "Archive")
    with pytest.raises(GraphQueryError):
        b.match("m", "File").returns("m.id; DROP DATABASE")


def test_public_builder_is_read_only():
    q = PublicGraphQuery().match("s", "Statute", doc_id="act-1").returns("s.title").build()
    assert not q.write
    assert not hasattr(PublicGraphQuery, "merge_node")
    assert not hasattr(PublicGraphQuery, "detach_delete")


def test_public_builder_rejects_tenant_labels_and_scope():
    with pytest.raises(GraphQueryError):
        PublicGraphQuery().match("m", "File")  # tenant label in public scope
    with pytest.raises(GraphQueryError):
        PublicGraphQuery().match("s", "Statute", public=False)


def test_public_expand_only_walks_public_nodes():
    q = (PublicGraphQuery()
         .match("s", "Statute", doc_id="act-1")
         .expand("s", ["CITES"], "n", max_hops=2)
         .returns("n.doc_id").build())
    assert "all(x IN nodes(p) WHERE x:Public)" in q.cypher


def test_handcrafted_queries_cannot_execute():
    forged = GraphQuery(cypher="MATCH (n) RETURN n", params={}, write=False, tenant_scoped=True)
    assert not is_builder_query(forged)
