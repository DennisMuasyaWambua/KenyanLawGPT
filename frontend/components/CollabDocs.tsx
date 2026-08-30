"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import CollabEditor from "./CollabEditor";

type Doc = {
  id: string;
  title: string;
  owner_name: string;
  updated_at: string;
};

type User = { id: string; full_name?: string; email: string };

// The share dialog: owners (and Managing Partners) pick who else can co-edit.
function ShareDialog({ docId, onClose }: { docId: string; onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [owner, setOwner] = useState<string>("");
  const [canShare, setCanShare] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const d = await api(`/api/v1/collab-documents/${docId}`);
        setUsers(d.users || []);
        setSelected(new Set(d.shared_user_ids || []));
        setOwner(d.document?.owner_id || "");
        setCanShare(!!d.is_owner);
      } catch (e: any) {
        setErr(e?.message || "Could not load sharing");
      } finally {
        setLoading(false);
      }
    })();
  }, [docId]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setErr("");
    try {
      await api(`/api/v1/collab-documents/${docId}/shares`, {
        method: "PUT",
        body: JSON.stringify({ user_ids: Array.from(selected) }),
      });
      onClose();
    } catch (e: any) {
      setErr(e?.message || "Could not save sharing");
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-lg font-bold text-navy">Share document</h3>
        <p className="mt-1 text-xs text-navy/60">
          Everyone you add can open and edit this document at the same time.
        </p>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
        {loading ? (
          <p className="mt-4 text-sm text-navy/50">Loading…</p>
        ) : (
          <>
            <div className="mt-3 max-h-64 space-y-1 overflow-y-auto">
              {users
                .filter((u) => u.id !== owner)
                .map((u) => (
                  <label
                    key={u.id}
                    className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm ${
                      canShare ? "hover:bg-navy/5" : "cursor-not-allowed opacity-70"
                    }`}
                  >
                    <input
                      type="checkbox"
                      disabled={!canShare}
                      checked={selected.has(u.id)}
                      onChange={() => toggle(u.id)}
                    />
                    <span>{u.full_name || u.email}</span>
                    {u.full_name && <span className="text-xs text-navy/40">{u.email}</span>}
                  </label>
                ))}
              {users.filter((u) => u.id !== owner).length === 0 && (
                <p className="text-sm text-navy/50">No other team members to share with yet.</p>
              )}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="btn-outline text-xs" onClick={onClose}>Close</button>
              {canShare && (
                <button className="btn-gold text-xs" onClick={save} disabled={saving}>
                  {saving ? "Saving…" : "Save sharing"}
                </button>
              )}
            </div>
            {!canShare && (
              <p className="mt-2 text-xs text-navy/50">
                Only the owner or a Managing Partner can change sharing.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function EditorPane({ doc, onBack }: { doc: Doc; onBack: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(doc.title);
  const [sharing, setSharing] = useState(false);

  async function saveTitle() {
    const t = title.trim() || "Untitled document";
    if (t === doc.title) return;
    try {
      await api(`/api/v1/collab-documents/${doc.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: t }),
      });
      qc.invalidateQueries({ queryKey: ["collab-docs"] });
    } catch {
      /* keep editing; title save is best-effort */
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center gap-3">
        <button className="btn-outline text-xs" onClick={onBack}>← All documents</button>
        <input
          className="flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 font-display text-lg font-bold text-navy outline-none hover:border-navy/10 focus:border-gold"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        />
        <button className="btn-gold text-xs" onClick={() => setSharing(true)}>Share</button>
      </div>
      <div className="flex-1 overflow-hidden">
        <CollabEditor docId={doc.id} />
      </div>
      {sharing && <ShareDialog docId={doc.id} onClose={() => setSharing(false)} />}
    </div>
  );
}

export default function CollabDocs() {
  const qc = useQueryClient();
  const [openDoc, setOpenDoc] = useState<Doc | null>(null);
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["collab-docs"],
    queryFn: () => api("/api/v1/collab-documents"),
  });
  const docs: Doc[] = data?.documents || [];

  async function create() {
    setCreating(true);
    try {
      const d = await api("/api/v1/collab-documents", {
        method: "POST",
        body: JSON.stringify({ title: "Untitled document" }),
      });
      await qc.invalidateQueries({ queryKey: ["collab-docs"] });
      setOpenDoc({ id: d.id, title: d.title, owner_name: "", updated_at: new Date().toISOString() });
    } finally {
      setCreating(false);
    }
  }

  if (openDoc) {
    return <EditorPane doc={openDoc} onBack={() => { setOpenDoc(null); qc.invalidateQueries({ queryKey: ["collab-docs"] }); }} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="font-display text-3xl font-bold text-navy">Documents</h2>
          <p className="text-sm text-navy/60">Co-edit in real time — like Google Docs, inside the firm.</p>
        </div>
        <button className="btn-gold" onClick={create} disabled={creating}>
          {creating ? "Creating…" : "New document"}
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-navy/50">Loading documents…</p>
      ) : docs.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-16 text-center">
          <p className="font-display text-lg font-semibold text-navy">No documents yet</p>
          <p className="mt-1 max-w-sm text-sm text-navy/60">
            Create a document to draft together in real time. Share it with colleagues and everyone
            edits the same page live.
          </p>
          <button className="btn-gold mt-4" onClick={create} disabled={creating}>
            {creating ? "Creating…" : "Create your first document"}
          </button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {docs.map((d) => (
            <button
              key={d.id}
              onClick={() => setOpenDoc(d)}
              className="card text-left transition hover:border-gold hover:shadow-md"
            >
              <p className="line-clamp-2 font-display font-semibold text-navy">{d.title}</p>
              <p className="mt-2 text-xs text-navy/50">
                {d.owner_name ? `${d.owner_name} · ` : ""}updated {fmtDate(d.updated_at)}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
