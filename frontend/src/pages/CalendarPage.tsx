import { useEffect, useState } from 'react';
import {
  createEvent,
  deleteEvent,
  listEvents,
  type CalendarEvent,
} from '../lib/gateway';
import { ApiError } from '../lib/api';

type Scope = 'all' | 'personal' | 'shared';

const fmt = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export function CalendarPage() {
  const [scope, setScope] = useState<Scope>('all');
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [error, setError] = useState('');

  // New-event form
  const [title, setTitle] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [location, setLocation] = useState('');
  const [shared, setShared] = useState(false);
  const [remind, setRemind] = useState(30);

  const refresh = (s: Scope = scope) => {
    listEvents(s).then(setEvents).catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load.'));
  };

  useEffect(() => refresh(scope), [scope]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await createEvent({
        title,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        location,
        is_shared: shared,
        reminders: remind > 0 ? [{ minutes_before: remind, method: 'app' }] : [],
      });
      setTitle('');
      setStart('');
      setEnd('');
      setLocation('');
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create event.');
    }
  };

  const remove = async (id: string) => {
    await deleteEvent(id).catch(() => {});
    refresh();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Calendar</h1>
          <p className="page-sub">Your personal schedule and the shared firm calendar.</p>
        </div>
        <div className="segmented">
          {(['all', 'personal', 'shared'] as Scope[]).map((s) => (
            <button key={s} className={`seg${scope === s ? ' active' : ''}`} onClick={() => setScope(s)}>
              {s[0].toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">Schedule a meeting or reminder</h2>
        <form className="grid-form" onSubmit={add}>
          <label className="span2">Title<input value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
          <label>Starts<input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required /></label>
          <label>Ends<input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} required /></label>
          <label>Location<input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Optional" /></label>
          <label>Remind me<select value={remind} onChange={(e) => setRemind(Number(e.target.value))}>
            <option value={0}>No reminder</option>
            <option value={10}>10 min before</option>
            <option value={30}>30 min before</option>
            <option value={60}>1 hour before</option>
            <option value={1440}>1 day before</option>
          </select></label>
          <label className="checkbox span2">
            <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
            Share with the whole firm
          </label>
          <button className="btn btn-primary span2">Add to calendar</button>
        </form>
        {error && <div className="auth-error">{error}</div>}
      </section>

      <section className="card">
        <h2 className="card-title">Upcoming</h2>
        {events.length === 0 ? (
          <p className="muted">No events yet.</p>
        ) : (
          <ul className="event-list">
            {events.map((ev) => (
              <li key={ev.id} className="event-row">
                <div>
                  <div className="event-title">
                    {ev.title}
                    {ev.is_shared ? <span className="tag tag-shared">Firm</span> : <span className="tag">Personal</span>}
                  </div>
                  <div className="event-meta">
                    {fmt(ev.start)} → {fmt(ev.end)}
                    {ev.location && ` · ${ev.location}`}
                    {ev.reminders.length > 0 && ` · 🔔 ${ev.reminders[0].minutes_before}m before`}
                  </div>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => remove(ev.id)}>Delete</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
