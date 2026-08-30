"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { usePermissions } from "@/lib/usePermissions";

type EventT = {
  id: string;
  scope: "personal" | "firm";
  title: string;
  description: string;
  location: string;
  file_id?: string | null;
  start_at: string;
  end_at?: string | null;
  all_day: boolean;
  attendee_user_ids?: string[];
};

type StaffT = { id: string; full_name: string; email: string; client_id?: string | null };

type MatterT = {
  id: string;
  kind: "court_date" | "deadline";
  file_id: string;
  reference: string;
  file_title: string;
  title: string;
  location: string;
  start_at: string;
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const REMINDER_OPTIONS = [
  { minutes: 1440, label: "1 day before" },
  { minutes: 60, label: "1 hour before" },
  { minutes: 10, label: "10 min before" },
];

const pad = (n: number) => String(n).padStart(2, "0");
const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fmtTime = (s: string) =>
  new Date(s).toLocaleTimeString("en-KE", { hour: "2-digit", minute: "2-digit" });
// datetime-local value in the browser's local time.
const localValue = (d: Date, hm = "09:00") =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${hm}`;

export default function CalendarPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const { can } = usePermissions();
  const canCreateShared = can("calendar.create_shared");

  const [cursor, setCursor] = useState(() => {
    const n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), 1);
  });
  const [filter, setFilter] = useState<"all" | "personal" | "firm">("all");
  const [modalDate, setModalDate] = useState<Date | null>(null); // create modal
  const [selected, setSelected] = useState<EventT | null>(null); // detail modal
  const [reminders, setReminders] = useState<number[]>([60]);
  const [attendees, setAttendees] = useState<string[]>([]);

  // Six-week grid starting on the Sunday on/before the 1st of the month.
  const gridStart = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const d = new Date(first);
    d.setDate(1 - first.getDay());
    return d;
  }, [cursor]);
  const cells = useMemo(
    () =>
      Array.from({ length: 42 }, (_, i) => {
        const d = new Date(gridStart);
        d.setDate(gridStart.getDate() + i);
        return d;
      }),
    [gridStart]
  );
  const from = gridStart.toISOString();
  const to = new Date(cells[41].getFullYear(), cells[41].getMonth(), cells[41].getDate() + 1).toISOString();

  const { data } = useQuery({
    queryKey: ["calendar", from, to],
    queryFn: () => api(`/api/v1/calendar/events?from=${from}&to=${to}`),
  });
  const { data: filesData } = useQuery({ queryKey: ["files"], queryFn: () => api("/api/v1/files") });
  // Staff list for the attendee picker — best-effort (needs users.view).
  const { data: usersData } = useQuery({
    queryKey: ["users"],
    queryFn: () => api("/api/v1/users"),
    retry: false,
  });
  const staff: StaffT[] = ((usersData?.users || []) as StaffT[]).filter((u) => !u.client_id);
  const staffName = (id: string) => {
    const u = staff.find((x) => x.id === id);
    return u ? u.full_name || u.email : "member";
  };

  const create = useMutation({
    mutationFn: (body: any) => api("/api/v1/calendar/events", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar"] });
      setModalDate(null);
      setReminders([60]);
      setAttendees([]);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/calendar/events/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar"] });
      setSelected(null);
    },
  });

  // Bucket events + matters by local day.
  const { evByDay, mtByDay } = useMemo(() => {
    const ev: Record<string, EventT[]> = {};
    const mt: Record<string, MatterT[]> = {};
    for (const e of (data?.events || []) as EventT[]) {
      if (filter !== "all" && e.scope !== filter) continue;
      (ev[dayKey(new Date(e.start_at))] ||= []).push(e);
    }
    if (filter !== "personal") {
      for (const m of (data?.matters || []) as MatterT[]) {
        (mt[dayKey(new Date(m.start_at))] ||= []).push(m);
      }
    }
    return { evByDay: ev, mtByDay: mt };
  }, [data, filter]);

  const monthLabel = cursor.toLocaleDateString("en-KE", { month: "long", year: "numeric" });
  const todayKey = dayKey(new Date());
  const stepMonth = (delta: number) =>
    setCursor((c) => new Date(c.getFullYear(), c.getMonth() + delta, 1));

  function toggleReminder(m: number) {
    setReminders((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-3xl font-bold text-navy">{monthLabel}</h2>
          <div className="flex items-center gap-1">
            <button onClick={() => stepMonth(-1)} className="btn-outline !px-2 !py-1" aria-label="Previous month">‹</button>
            <button onClick={() => setCursor(() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1); })} className="btn-outline !py-1">Today</button>
            <button onClick={() => stepMonth(1)} className="btn-outline !px-2 !py-1" aria-label="Next month">›</button>
          </div>
        </div>
        <div className="flex gap-1 rounded-lg bg-navy/5 p-1 text-sm">
          {(["all", "personal", "firm"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1 capitalize ${filter === f ? "bg-gold text-navy font-semibold" : "text-navy/60"}`}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Month grid */}
      <div className="mt-4 overflow-hidden rounded-lg border border-navy/10">
        <div className="grid grid-cols-7 bg-navy/5 text-center text-[11px] font-semibold uppercase tracking-wide text-navy/50">
          {WEEKDAYS.map((w) => <div key={w} className="py-2">{w}</div>)}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((d, i) => {
            const key = dayKey(d);
            const inMonth = d.getMonth() === cursor.getMonth();
            const isToday = key === todayKey;
            const evs = evByDay[key] || [];
            const mts = mtByDay[key] || [];
            const total = evs.length + mts.length;
            return (
              <button
                key={i}
                onClick={() => { setAttendees([]); setModalDate(new Date(d.getFullYear(), d.getMonth(), d.getDate())); }}
                className={`min-h-[92px] border-b border-r border-navy/10 p-1.5 text-left align-top transition hover:bg-gold/5 ${
                  inMonth ? "bg-white" : "bg-navy/[0.02]"
                }`}
              >
                <span className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                  isToday ? "bg-navy font-bold text-white" : inMonth ? "text-ink" : "text-ink/30"
                }`}>
                  {d.getDate()}
                </span>
                <div className="mt-1 space-y-0.5">
                  {mts.slice(0, 2).map((m) => (
                    <div key={m.id} title={`${m.reference} — ${m.title}`}
                      onClick={(e) => { e.stopPropagation(); router.push(`/files/${m.file_id}`); }}
                      className={`truncate rounded px-1 py-0.5 text-[10px] font-medium ${
                        m.kind === "court_date" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
                      }`}>
                      {m.kind === "court_date" ? "⚖ " : "⏰ "}{m.title}
                    </div>
                  ))}
                  {evs.slice(0, Math.max(0, 3 - Math.min(mts.length, 2))).map((e) => (
                    <div key={e.id} title={e.title}
                      onClick={(ev) => { ev.stopPropagation(); setSelected(e); }}
                      className={`truncate rounded px-1 py-0.5 text-[10px] font-medium ${
                        e.scope === "firm" ? "bg-navy text-white" : "bg-gold/25 text-navy"
                      }`}>
                      {e.all_day ? "" : `${fmtTime(e.start_at)} `}{e.title}
                    </div>
                  ))}
                  {total > 3 && <div className="px-1 text-[10px] text-ink/40">+{total - 3} more</div>}
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <p className="mt-2 text-xs text-ink/40">Click a day to add an event or reminder. ⚖ court dates and ⏰ deadlines are pulled from your matters.</p>

      {/* Create modal */}
      {modalDate && (
        <Modal onClose={() => setModalDate(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.currentTarget);
              const startLocal = fd.get("start_at") as string;
              const endLocal = fd.get("end_at") as string;
              create.mutate({
                scope: fd.get("scope"),
                title: fd.get("title"),
                description: fd.get("description") || "",
                location: fd.get("location") || "",
                file_id: fd.get("file_id") || null,
                start_at: new Date(startLocal).toISOString(),
                end_at: endLocal ? new Date(endLocal).toISOString() : null,
                all_day: fd.get("all_day") === "on",
                reminders: reminders.map((m) => ({ offset_minutes: m })),
                attendee_user_ids: attendees,
              });
            }}
            className="space-y-3"
          >
            <h3 className="font-display text-lg font-bold text-navy">
              New event · {modalDate.toLocaleDateString("en-KE", { weekday: "long", day: "numeric", month: "long" })}
            </h3>
            <input name="title" className="input" placeholder="Title" required autoFocus />
            <div className="grid grid-cols-2 gap-2">
              <select name="scope" className="input" defaultValue="personal">
                <option value="personal">Personal</option>
                {canCreateShared && <option value="firm">Firm (shared)</option>}
              </select>
              <select name="file_id" className="input">
                <option value="">No matter</option>
                {(filesData?.files || []).map((m: any) => (
                  <option key={m.id} value={m.id}>{m.reference} — {m.title}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">Start</label>
                <input name="start_at" type="datetime-local" className="input" defaultValue={localValue(modalDate)} required />
              </div>
              <div>
                <label className="label">End (optional)</label>
                <input name="end_at" type="datetime-local" className="input" defaultValue={localValue(modalDate, "10:00")} />
              </div>
            </div>
            <div>
              <label className="label">Reminders</label>
              <div className="flex flex-wrap gap-3 text-xs text-ink/70">
                {REMINDER_OPTIONS.map((o) => (
                  <label key={o.minutes} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={reminders.includes(o.minutes)} onChange={() => toggleReminder(o.minutes)} />
                    {o.label}
                  </label>
                ))}
              </div>
            </div>
            {staff.length > 0 && (
              <div>
                <label className="label">Attendees (reminders go to everyone selected)</label>
                <div className="max-h-28 space-y-1 overflow-y-auto rounded-md border border-navy/15 p-2 text-xs text-ink/70">
                  {staff.map((u) => (
                    <label key={u.id} className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={attendees.includes(u.id)}
                        onChange={() =>
                          setAttendees((prev) =>
                            prev.includes(u.id) ? prev.filter((x) => x !== u.id) : [...prev, u.id]
                          )
                        }
                      />
                      {u.full_name || u.email}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <input name="location" className="input" placeholder="Location (optional)" />
            <textarea name="description" className="input" placeholder="Notes (optional)" rows={2} />
            <label className="flex items-center gap-2 text-sm text-ink/70">
              <input type="checkbox" name="all_day" /> All day
            </label>
            {create.isError && <p className="text-xs text-red-600">{(create.error as Error).message}</p>}
            <div className="flex gap-2">
              <button type="button" className="btn-outline flex-1" onClick={() => setModalDate(null)}>Cancel</button>
              <button className="btn-gold flex-1" disabled={create.isPending}>{create.isPending ? "Saving…" : "Add"}</button>
            </div>
          </form>
        </Modal>
      )}

      {/* Event detail modal */}
      {selected && (
        <Modal onClose={() => setSelected(null)}>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                selected.scope === "firm" ? "bg-navy text-white" : "bg-gold/20 text-navy"}`}>
                {selected.scope}
              </span>
              <h3 className="font-display text-lg font-bold text-navy">{selected.title}</h3>
            </div>
            <p className="text-sm text-ink/70">
              {new Date(selected.start_at).toLocaleString("en-KE", { dateStyle: "full", timeStyle: selected.all_day ? undefined : "short" })}
              {selected.end_at && !selected.all_day ? ` – ${fmtTime(selected.end_at)}` : ""}
            </p>
            {selected.location && <p className="text-sm text-ink/60">📍 {selected.location}</p>}
            {selected.description && <p className="text-sm text-ink/60">{selected.description}</p>}
            {selected.attendee_user_ids && selected.attendee_user_ids.length > 0 && (
              <p className="text-sm text-ink/60">
                👥 {selected.attendee_user_ids.map(staffName).join(", ")}
              </p>
            )}
            <div className="flex gap-2 pt-2">
              <button className="btn-outline flex-1" onClick={() => setSelected(null)}>Close</button>
              <button className="btn-primary flex-1 !bg-red-700" disabled={remove.isPending} onClick={() => remove.mutate(selected.id)}>
                {remove.isPending ? "Deleting…" : "Delete"}
              </button>
            </div>
            {remove.isError && <p className="text-xs text-red-600">{(remove.error as Error).message}</p>}
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:items-center" onClick={onClose}>
      <div className="w-full max-w-lg rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
