import { useEffect, useRef, useState } from 'react';
import {
  listAudio,
  listCases,
  transcribeAudio,
  uploadAudio,
  type AudioUpload,
  type Case,
} from '../lib/gateway';
import { ApiError } from '../lib/api';

// Common languages for client conversations; blank = auto-detect (multilingual).
const LANGUAGES = [
  { code: '', label: 'Auto-detect (multilingual)' },
  { code: 'en', label: 'English' },
  { code: 'sw', label: 'Swahili' },
  { code: 'fr', label: 'French' },
  { code: 'ar', label: 'Arabic' },
  { code: 'so', label: 'Somali' },
];

export function TranscriberPage() {
  const [cases, setCases] = useState<Case[]>([]);
  const [caseId, setCaseId] = useState('');
  const [language, setLanguage] = useState('');
  const [uploads, setUploads] = useState<AudioUpload[]>([]);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => listAudio().then(setUploads).catch(() => {});
  useEffect(() => {
    listCases().then(setCases).catch(() => {});
    refresh();
  }, []);

  // Upload a blob via the presigned flow, then kick off transcription.
  const process = async (blob: Blob, filename: string) => {
    setError('');
    setStatus('Uploading…');
    try {
      const audio = await uploadAudio(blob, { filename, language, caseId: caseId || undefined });
      setStatus('Transcribing… this can take a moment.');
      await transcribeAudio(audio.id);
      setStatus('Done.');
      refresh();
    } catch (err) {
      setStatus('');
      setError(err instanceof ApiError ? err.message : 'Transcription failed.');
    }
  };

  const onFile = (files: FileList | null) => {
    if (!files || !files[0]) return;
    process(files[0], files[0].name);
    if (fileRef.current) fileRef.current.value = '';
  };

  const startRecording = async () => {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        process(blob, `recording-${Date.now()}.webm`);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setError('Microphone access was denied.');
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    setRecording(false);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 className="page-title">Transcribe</h1>
          <p className="page-sub">Multilingual speech-to-text for client conversations — feeds legal research.</p>
        </div>
      </div>

      <section className="card">
        <h2 className="card-title">New recording</h2>
        <div className="grid-form">
          <label>Language<select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select></label>
          <label>Attach to case<select value={caseId} onChange={(e) => setCaseId(e.target.value)}>
            <option value="">None</option>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select></label>
        </div>

        <div className="record-row">
          {recording ? (
            <button className="btn btn-danger" onClick={stopRecording}>■ Stop recording</button>
          ) : (
            <button className="btn btn-primary" onClick={startRecording}>● Record</button>
          )}
          <span className="muted">or</span>
          <input ref={fileRef} type="file" accept="audio/*" onChange={(e) => onFile(e.target.files)} />
        </div>
        {status && <div className="status-line">{status}</div>}
        {error && <div className="auth-error">{error}</div>}
      </section>

      <section className="card">
        <h2 className="card-title">Transcripts</h2>
        {uploads.length === 0 ? (
          <p className="muted">No transcripts yet.</p>
        ) : (
          <ul className="transcript-list">
            {uploads.map((u) => (
              <li key={u.id} className="transcript">
                <div className="transcript-head">
                  <span className="transcript-file">{u.filename}</span>
                  <span className={`status-dot status-${u.status}`} />
                  <span className="muted">{u.status}</span>
                  {u.transcript?.detected_language && <span className="tag">{u.transcript.detected_language}</span>}
                </div>
                {u.transcript?.text ? <p className="transcript-text">{u.transcript.text}</p> : null}
                {u.error && <div className="doc-error">{u.error}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
