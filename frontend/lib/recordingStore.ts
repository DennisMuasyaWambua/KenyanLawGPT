"use client";

// On-device safety net for meeting recordings. Every few seconds the recorder's
// audio is appended here (IndexedDB), so a recording survives the tab being
// killed, the device locking, the session expiring or the upload failing. Once
// the audio is safely in cloud storage the local copy is deleted.
//
// Entries are tagged with the firm and user who recorded them: on a shared
// device, one advocate's unsent recording is never shown to — or uploaded
// under — someone else's account.

export type LocalRecording = {
  id: string;
  tenant: string;
  userId: string;
  startedAt: number;
  /** Last time audio was appended; doubles as a heartbeat while recording. */
  updatedAt: number;
  mimeType: string;
  fileId: string;
  numSpeakers: number;
  durationSeconds: number;
  /** "recording": capture never finished (tab closed, crash, device locked);
   *  "pending": stopped normally, waiting to be uploaded. */
  state: "recording" | "pending";
  /** Server row already created for this audio (lets a retry reuse it). */
  serverId?: string;
  error?: string;
};

const DB_NAME = "advocatus-recordings";
const SESSIONS = "sessions";
const CHUNKS = "chunks";

let dbPromise: Promise<IDBDatabase> | null = null;

function db(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") return reject(new Error("IndexedDB unavailable"));
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const d = req.result;
        d.createObjectStore(SESSIONS, { keyPath: "id" });
        d.createObjectStore(CHUNKS, { autoIncrement: true }).createIndex("session", "session");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    dbPromise.catch(() => { dbPromise = null; });
  }
  return dbPromise;
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("transaction aborted"));
  });
}

function result<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function saveSession(rec: LocalRecording): Promise<void> {
  const tx = (await db()).transaction(SESSIONS, "readwrite");
  tx.objectStore(SESSIONS).put(rec);
  await done(tx);
  // Ask the browser not to evict our storage under pressure (best-effort).
  navigator.storage?.persist?.().catch(() => {});
}

export async function updateSession(id: string, patch: Partial<LocalRecording>): Promise<void> {
  const tx = (await db()).transaction(SESSIONS, "readwrite");
  const store = tx.objectStore(SESSIONS);
  const cur = await result(store.get(id) as IDBRequest<LocalRecording | undefined>);
  if (cur) store.put({ ...cur, ...patch });
  await done(tx);
}

/** Append one recorder chunk and bump the session heartbeat, atomically. */
export async function appendChunk(id: string, blob: Blob, durationSeconds: number): Promise<void> {
  const tx = (await db()).transaction([SESSIONS, CHUNKS], "readwrite");
  tx.objectStore(CHUNKS).add({ session: id, blob });
  const sessions = tx.objectStore(SESSIONS);
  const cur = await result(sessions.get(id) as IDBRequest<LocalRecording | undefined>);
  if (cur) sessions.put({ ...cur, updatedAt: Date.now(), durationSeconds });
  await done(tx);
}

export async function listSessions(tenant: string, userId: string): Promise<LocalRecording[]> {
  const tx = (await db()).transaction(SESSIONS, "readonly");
  const all = await result(tx.objectStore(SESSIONS).getAll() as IDBRequest<LocalRecording[]>);
  return all
    .filter((r) => r.tenant === tenant && r.userId === userId)
    .sort((a, b) => a.startedAt - b.startedAt);
}

/** The recording's audio: its chunks, in the order they were captured. */
export async function loadAudio(rec: LocalRecording): Promise<Blob> {
  const tx = (await db()).transaction(CHUNKS, "readonly");
  const chunks = await result(
    tx.objectStore(CHUNKS).index("session").getAll(IDBKeyRange.only(rec.id)) as IDBRequest<{ blob: Blob }[]>
  );
  return new Blob(chunks.map((c) => c.blob), { type: rec.mimeType || "audio/webm" });
}

export async function deleteSession(id: string): Promise<void> {
  const tx = (await db()).transaction([SESSIONS, CHUNKS], "readwrite");
  tx.objectStore(SESSIONS).delete(id);
  const keys = await result(tx.objectStore(CHUNKS).index("session").getAllKeys(IDBKeyRange.only(id)));
  for (const k of keys) tx.objectStore(CHUNKS).delete(k);
  await done(tx);
}
