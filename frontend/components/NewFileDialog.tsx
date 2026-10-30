"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type NewFile = { id: string; reference: string; title: string };

/** Register a new file (matter). Used from the Files page and from the
 *  recordings screen, so a meeting with a new client can be linked to its file
 *  without leaving the recorder. */
export default function NewFileDialog({ onClose, onCreated }: {
  onClose: () => void;
  onCreated?: (file: NewFile) => void;
}) {
  const qc = useQueryClient();
  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => api("/api/v1/clients"),
  });
  const create = useMutation({
    mutationFn: (body: any) => api<{ file: NewFile }>("/api/v1/files", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: ({ file }) => {
      qc.invalidateQueries({ queryKey: ["files"] });
      onCreated?.(file);
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-navy/50 p-4">
      <form
        className="card w-full max-w-lg space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          create.mutate({
            reference: fd.get("reference"), title: fd.get("title"),
            description: fd.get("description"), practice_area: fd.get("practice_area"),
            court: fd.get("court"), court_case_number: fd.get("court_case_number"),
            client_id: fd.get("client_id") || null,
          });
        }}
      >
        <h3 className="font-display text-xl font-bold text-navy">New file</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label className="label">Reference</label><input name="reference" className="input" required /></div>
          <div><label className="label">Practice area</label><input name="practice_area" className="input" /></div>
        </div>
        <div><label className="label">Title</label><input name="title" className="input" required /></div>
        <div><label className="label">Description</label><textarea name="description" className="input" rows={2} /></div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label className="label">Court</label><input name="court" className="input" /></div>
          <div><label className="label">Case number</label><input name="court_case_number" className="input" /></div>
        </div>
        <div>
          <label className="label">Client</label>
          <select name="client_id" className="input">
            <option value="">— none —</option>
            {(clientsData?.clients || []).map((c: any) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        {create.isError && <p className="text-sm text-red-600">{(create.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-primary !bg-ink/20 !text-ink" onClick={onClose}>Cancel</button>
          <button className="btn-gold" disabled={create.isPending}>{create.isPending ? "Creating…" : "Create"}</button>
        </div>
      </form>
    </div>
  );
}
