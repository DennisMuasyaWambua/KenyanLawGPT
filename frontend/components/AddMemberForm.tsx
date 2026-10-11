"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Role } from "@/components/RolesManager";

type Result = { name: string; email: string; emailed: boolean; tempPassword?: string; emailError?: string };

/** Adds a firm member with a role. The gateway generates a temporary password
 *  and emails it; the member must replace it at first sign-in. */
export default function AddMemberForm({ roles, onAdded }: { roles: Role[]; onAdded?: () => void }) {
  const qc = useQueryClient();
  const [results, setResults] = useState<Result[]>([]);

  const add = useMutation({
    mutationFn: (body: Record<string, string>) => api("/api/v1/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (d: any, body) => {
      setResults((prev) => [{
        name: body.full_name, email: body.email, emailed: !!d.credentials_emailed,
        tempPassword: d.temp_password, emailError: d.email_error,
      }, ...prev]);
      qc.invalidateQueries({ queryKey: ["users"] });
      qc.invalidateQueries({ queryKey: ["roles"] });
      onAdded?.();
    },
  });

  return (
    <div className="space-y-3">
      <form
        className="grid grid-cols-1 gap-2 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const fd = new FormData(form);
          add.mutate(
            {
              full_name: String(fd.get("full_name") || ""), email: String(fd.get("email") || ""),
              phone: String(fd.get("phone") || ""), role_id: String(fd.get("role_id") || ""),
            },
            { onSuccess: () => form.reset() },
          );
        }}
      >
        <input name="full_name" className="input" placeholder="Full name" required aria-label="Full name" />
        <input name="email" type="email" className="input" placeholder="Email" required aria-label="Email" />
        <input name="phone" type="tel" className="input" placeholder="Phone (optional, for reminders)" aria-label="Phone" />
        <select name="role_id" className="input" required defaultValue="" aria-label="Role">
          <option value="" disabled>Role…</option>
          {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <button className="btn-gold sm:col-span-2" disabled={add.isPending}>
          {add.isPending ? "Adding…" : "Add member & send login"}
        </button>
      </form>
      {add.isError && <p className="text-xs text-red-600">{(add.error as Error).message}</p>}
      {results.map((r) => (
        <div key={r.email} className={`rounded-md px-3 py-2 text-xs ${r.emailed ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-900"}`}>
          {r.emailed ? (
            <>✓ <b>{r.name}</b> added — sign-in details emailed to {r.email}.</>
          ) : (
            <>
              <b>{r.name}</b> added, but the email wasn&apos;t sent{r.emailError ? ` (${r.emailError})` : ""}. Share this
              temporary password with them securely — it&apos;s shown only once:{" "}
              <code className="rounded bg-white px-1.5 py-0.5 font-mono text-sm text-navy">{r.tempPassword}</code>
              <button type="button" className="ml-2 font-semibold underline"
                onClick={() => navigator.clipboard?.writeText(r.tempPassword || "")}>copy</button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
