"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type Task = {
  id: string; file_id: string; file_ref: string; assigned_to?: string | null;
  assigned_to_name?: string; title: string; description: string;
  due_date?: string | null; status: string; priority: string;
};

const STATUSES = ["todo", "in_progress", "blocked", "done"];
const PRIO_COLORS: Record<string, string> = { low: "text-ink/50", medium: "text-navy", high: "text-red-600" };
const overdue = (t: Task) => t.status !== "done" && t.due_date && new Date(t.due_date) < new Date();

export default function TasksPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const canAll = can("tasks.view_all");
  const canCreate = can("tasks.create");
  const canAssign = can("tasks.assign");
  const [scope, setScope] = useState<"own" | "all">("own");

  const { data } = useQuery({ queryKey: ["tasks", scope], queryFn: () => api(`/api/v1/tasks?scope=${scope}`) });
  const tasks: Task[] = data?.tasks || [];
  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files"), enabled: canCreate });
  const { data: usersData } = useQuery({ queryKey: ["users"], queryFn: () => api("/api/v1/users"), enabled: canCreate && canAssign });

  const create = useMutation({
    mutationFn: (b: any) => api("/api/v1/tasks", { method: "POST", body: JSON.stringify(b) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api(`/api/v1/tasks/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/tasks/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Tasks</h2>
        {canAll && (
          <div className="flex gap-1 rounded-lg bg-navy/5 p-1 text-sm">
            {(["own", "all"] as const).map((s) => (
              <button key={s} onClick={() => setScope(s)}
                className={`rounded-md px-3 py-1 capitalize ${scope === s ? "bg-gold text-navy font-semibold" : "text-navy/60"}`}>
                {s === "own" ? "My tasks" : "All firm tasks"}
              </button>
            ))}
          </div>
        )}
      </div>

      {canCreate && (
        <form className="card mt-4 grid grid-cols-1 gap-2 sm:grid-cols-6"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            create.mutate({
              file_id: fd.get("file_id"), title: fd.get("title"),
              assigned_to: fd.get("assigned_to") || undefined,
              due_date: fd.get("due_date") ? new Date(fd.get("due_date") as string).toISOString() : undefined,
              priority: fd.get("priority"),
            });
            (e.target as HTMLFormElement).reset();
          }}>
          <input name="title" className="input sm:col-span-2" placeholder="Task title" required />
          <select name="file_id" className="input" required defaultValue="">
            <option value="" disabled>File…</option>
            {(filesData?.files || []).map((m: any) => <option key={m.id} value={m.id}>{m.reference}</option>)}
          </select>
          {canAssign ? (
            <select name="assigned_to" className="input" defaultValue="">
              <option value="">Assign to me</option>
              {(usersData?.users || []).filter((u: any) => u.role !== "client").map((u: any) => (
                <option key={u.id} value={u.id}>{u.full_name}</option>
              ))}
            </select>
          ) : <div className="hidden sm:block" />}
          <input name="due_date" type="date" className="input" />
          <select name="priority" className="input" defaultValue="medium">
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
          <button className="btn-gold sm:col-span-6" disabled={create.isPending}>Add task</button>
          {create.isError && <p className="text-xs text-red-600 sm:col-span-6">{(create.error as Error).message}</p>}
        </form>
      )}

      <div className="card mt-4 !p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-navy/5 text-left text-xs uppercase text-navy/60">
            <tr><th className="p-3">Task</th><th className="p-3">File</th><th className="p-3">Assignee</th><th className="p-3">Due</th><th className="p-3">Priority</th><th className="p-3">Status</th><th /></tr>
          </thead>
          <tbody>
            {tasks.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-ink/50">No tasks.</td></tr>}
            {tasks.map((t) => (
              <tr key={t.id} className="border-t border-navy/5">
                <td className="p-3 font-medium">{t.title}</td>
                <td className="p-3 text-xs text-ink/60">{t.file_ref}</td>
                <td className="p-3 text-xs">{t.assigned_to_name || "—"}</td>
                <td className={`p-3 text-xs ${overdue(t) ? "font-bold text-red-600" : "text-ink/60"}`}>{t.due_date ? fmtDate(t.due_date) : "—"}</td>
                <td className={`p-3 text-xs font-semibold capitalize ${PRIO_COLORS[t.priority]}`}>{t.priority}</td>
                <td className="p-3">
                  <select className="input !py-1 !text-xs" value={t.status}
                    onChange={(e) => setStatus.mutate({ id: t.id, status: e.target.value })}>
                    {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                  </select>
                </td>
                <td className="p-3">
                  {canCreate && <button className="text-xs text-red-600 hover:underline" onClick={() => remove.mutate(t.id)}>delete</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
