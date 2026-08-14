"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDate } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type EventT = {
  id: string;
  scope: "personal" | "firm";
  title: string;
  description: string;
  location: string;
  matter_id?: string | null;
  start_at: string;
  end_at?: string | null;
  all_day: boolean;
};

const toISO = (local: string) => (local ? new Date(local).toISOString() : undefined);
const fmtTime = (s: string) =>
  new Date(s).toLocaleTimeString("en-KE", { hour: "2-digit", minute: "2-digit" });

// Reminder presets, expressed as minutes before the event start. The event may
// carry multiple; the backend materializes one event_reminders row per offset.
const REMINDER_OPTIONS: { minutes: number; label: string }[] = [
  { minutes: 1440, label: "1 day before" },
  { minutes: 60, label: "1 hour before" },
  { minutes: 10, label: "10 min before" },
];

export default function CalendarPage() {
  const qc = useQueryClient();
  const { can } = usePermissions();
  const canCreateShared = can("calendar.create_shared");
  const [filter, setFilter] = useState<"all" | "personal" | "firm">("all");
  const [reminders, setReminders] = useState<number[]>([60]);

  function toggleReminder(m: number) {
    setReminders((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));
  }

  const from = useMemo(() => new Date(Date.now() - 7 * 864e5).toISOString(), []);
  const to = useMemo(() => new Date(Date.now() + 60 * 864e5).toISOString(), []);

  const { data } = useQuery({
    queryKey: ["calendar", from, to],
    queryFn: () => api(`/api/v1/calendar/events?from=${from}&to=${to}`),
  });
  const { data: mattersData } = useQuery({ queryKey: ["matters"], queryFn: () => api("/api/v1/matters") });

  const create = useMutation({
    mutationFn: (body: any) => api("/api/v1/calendar/events", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["calendar"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/calendar/events/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const events: EventT[] = (data?.events || []).filter(
    (e: EventT) => filter === "all" || e.scope === filter
  );

  // Group events by calendar day for an agenda view.
  const byDay = useMemo(() => {
    const groups: Record<string, EventT[]> = {};
    for (const e of events) {
      const key = e.start_at.slice(0, 10);
      (groups[key] ||= []).push(e);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [events]);

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="font-display text-3xl font-bold text-navy">Calendar</h2>
        <div className="flex gap-1 rounded-lg bg-navy/5 p-1 text-sm">
          {(["all", "personal", "firm"] as const).map((f) => (
            <button key={f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 capitalize ${filter === f ? "bg-gold text-navy font-semibold" : "text-navy/60"}`}>
              {f === "firm" ? "Firm" : f}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Agenda */}
        <div className="lg:col-span-2 space-y-6">
          {byDay.length === 0 && <p className="card text-sm text-ink/60">No events in this window.</p>}
          {byDay.map(([day, evs]) => (
            <div key={day}>
              <h3 className="mb-2 font-display text-sm font-bold uppercase text-navy/60">{fmtDate(day)}</h3>
              <div className="space-y-2">
                {evs.map((e) => (
                  <div key={e.id} className="card flex items-start justify-between !py-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                          e.scope === "firm" ? "bg-navy text-white" : "bg-gold/20 text-navy"}`}>
                          {e.scope}
                        </span>
                        <span className="font-semibold text-navy">{e.title}</span>
                      </div>
                      <p className="mt-1 text-xs text-ink/60">
                        {e.all_day ? "All day" : fmtTime(e.start_at)}
                        {e.end_at && !e.all_day ? ` – ${fmtTime(e.end_at)}` : ""}
                        {e.location ? ` · ${e.location}` : ""}
                      </p>
                      {e.description && <p className="mt-1 text-xs text-ink/50">{e.description}</p>}
                    </div>
                    <button className="text-xs text-red-600 hover:underline" onClick={() => remove.mutate(e.id)}>
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Create */}
        <form className="card h-fit space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            create.mutate({
              scope: fd.get("scope"),
              title: fd.get("title"),
              description: fd.get("description") || "",
              location: fd.get("location") || "",
              matter_id: fd.get("matter_id") || null,
              start_at: toISO(fd.get("start_at") as string),
              end_at: toISO(fd.get("end_at") as string) || null,
              all_day: fd.get("all_day") === "on",
              reminders: reminders.map((m) => ({ offset_minutes: m })),
            });
            (e.target as HTMLFormElement).reset();
            setReminders([60]);
          }}>
          <h3 className="font-display text-lg font-bold text-navy">New event / meeting</h3>
          <input name="title" className="input" placeholder="Title" required />
          <div className="grid grid-cols-2 gap-2">
            <select name="scope" className="input" defaultValue="personal">
              <option value="personal">Personal</option>
              {/* Shared events need the calendar.create_shared permission. */}
              {canCreateShared && <option value="firm">Firm (shared)</option>}
            </select>
            <select name="matter_id" className="input">
              <option value="">No matter</option>
              {(mattersData?.matters || []).map((m: any) => (
                <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>
              ))}
            </select>
          </div>
          <label className="label">Start</label>
          <input name="start_at" type="datetime-local" className="input" required />
          <label className="label">End (optional)</label>
          <input name="end_at" type="datetime-local" className="input" />
          <label className="label">Reminders</label>
          <div className="flex flex-wrap gap-3 text-xs text-ink/70">
            {REMINDER_OPTIONS.map((o) => (
              <label key={o.minutes} className="flex items-center gap-1.5">
                <input type="checkbox" checked={reminders.includes(o.minutes)} onChange={() => toggleReminder(o.minutes)} />
                {o.label}
              </label>
            ))}
          </div>
          <input name="location" className="input" placeholder="Location (optional)" />
          <textarea name="description" className="input" placeholder="Notes (optional)" rows={2} />
          <label className="flex items-center gap-2 text-sm text-ink/70">
            <input type="checkbox" name="all_day" /> All day
          </label>
          {create.isError && <p className="text-xs text-red-600">{(create.error as Error).message}</p>}
          <button className="btn-gold w-full" disabled={create.isPending}>Add to calendar</button>
        </form>
      </div>
    </div>
  );
}
