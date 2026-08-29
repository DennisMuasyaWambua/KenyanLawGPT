"use client";

// Draft export helpers: turn the plain-text draft the AI streams into a real
// .docx (generated in the browser, no backend round-trip) and, optionally, a
// Google Doc. The Google path reuses the same OAuth client used for sign-in
// (NEXT_PUBLIC_GOOGLE_CLIENT_ID) but asks for a narrow Drive scope on demand.

import { Document, HeadingLevel, Packer, Paragraph, TextRun } from "docx";

// Google Identity Services attaches `google` to window. Declared here so this
// module type-checks on its own (merges with any other Window.google decl).
declare global {
  interface Window {
    google?: any;
  }
}

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// The AI streams the draft as Markdown. Rather than dump the raw syntax into
// Word, we parse it so **bold**, *italic*, `code`, # headings, and - lists
// become real .docx formatting.

type Flags = { bold?: boolean; italics?: boolean };

// Parse inline Markdown (bold/italic/code/links) into styled runs. Recurses so
// nested marks compose, e.g. ***x*** -> bold + italic. Underscores are left as
// literals on purpose (they collide with identifiers like files.view_own).
function inlineRuns(text: string, flags: Flags = {}): TextRun[] {
  const runs: TextRun[] = [];
  // Ordered strongest-first: *** before ** before * so triple-star resolves to
  // bold + italic instead of leaving a stray asterisk.
  const RE =
    /\*\*\*([\s\S]+?)\*\*\*|\*\*([\s\S]+?)\*\*|\*([\s\S]+?)\*|`([^`]+?)`|\[([^\]]+?)\]\(([^)]+?)\)/;
  let rest = text;
  while (rest) {
    const m = RE.exec(rest);
    if (!m) {
      runs.push(new TextRun({ text: rest, ...flags }));
      break;
    }
    if (m.index > 0) runs.push(new TextRun({ text: rest.slice(0, m.index), ...flags }));
    if (m[1] !== undefined) runs.push(...inlineRuns(m[1], { ...flags, bold: true, italics: true }));
    else if (m[2] !== undefined) runs.push(...inlineRuns(m[2], { ...flags, bold: true }));
    else if (m[3] !== undefined) runs.push(...inlineRuns(m[3], { ...flags, italics: true }));
    else if (m[4] !== undefined) runs.push(new TextRun({ text: m[4], ...flags, font: "Courier New" }));
    else if (m[5] !== undefined) runs.push(...inlineRuns(m[5], flags)); // link: keep the label text
    rest = rest.slice(m.index + m[0].length);
  }
  return runs;
}

const HEADING_LEVELS = [
  HeadingLevel.HEADING_1,
  HeadingLevel.HEADING_2,
  HeadingLevel.HEADING_3,
  HeadingLevel.HEADING_4,
  HeadingLevel.HEADING_5,
  HeadingLevel.HEADING_6,
];

// A short all-caps line reads as a heading in legal drafts even without a
// leading '#', e.g. "STATEMENT OF CLAIM", "REPUBLIC OF KENYA".
function looksLikeHeading(line: string): boolean {
  const t = line.trim();
  if (!t || t.length > 80) return false;
  const letters = t.replace(/[^A-Za-z]/g, "");
  return letters.length > 0 && t === t.toUpperCase();
}

function blockToParagraph(line: string): Paragraph {
  if (line.trim() === "") return new Paragraph("");

  // Horizontal rule (---, ***, ___) -> just a blank spacer line.
  if (/^\s*([-*_])\1{2,}\s*$/.test(line)) return new Paragraph("");

  // ATX heading: #..###### text
  const heading = line.match(/^(#{1,6})\s+(.*)$/);
  if (heading) {
    return new Paragraph({
      heading: HEADING_LEVELS[heading[1].length - 1],
      spacing: { before: 160, after: 80 },
      children: inlineRuns(heading[2].replace(/\s*#+\s*$/, "")),
    });
  }

  // Unordered list: -, * or + followed by a space.
  const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
  if (bullet) {
    return new Paragraph({
      bullet: { level: 0 },
      spacing: { after: 60 },
      children: inlineRuns(bullet[1]),
    });
  }

  // Ordered list: keep the "1." marker as literal text (avoids wiring a docx
  // numbering instance) but still format the item's inline Markdown.
  const ordered = line.match(/^\s*(\d+[.)])\s+(.*)$/);
  if (ordered) {
    return new Paragraph({
      spacing: { after: 60 },
      indent: { left: 360 },
      children: [new TextRun({ text: ordered[1] + " " }), ...inlineRuns(ordered[2])],
    });
  }

  // Plain paragraph — bold it wholesale if it's an all-caps legal heading.
  return new Paragraph({
    spacing: { after: 120 },
    children: inlineRuns(line, looksLikeHeading(line) ? { bold: true } : {}),
  });
}

function draftToParagraphs(text: string): Paragraph[] {
  return text.split("\n").map(blockToParagraph);
}

// Build a genuine OOXML .docx (a zip of XML), not a Word-flavoured HTML blob.
export async function draftToDocxBlob(text: string): Promise<Blob> {
  const doc = new Document({
    sections: [{ children: draftToParagraphs(text) }],
  });
  return Packer.toBlob(doc);
}

// Trigger a browser download of the draft as <filename>.docx.
export async function downloadDocx(text: string, filename: string): Promise<void> {
  const blob = await draftToDocxBlob(text);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".docx") ? filename : `${filename}.docx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the download has started.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- Google Docs export --------------------------------------------------

let gisPromise: Promise<void> | null = null;
function loadGis(): Promise<void> {
  if (gisPromise) return gisPromise;
  gisPromise = new Promise((resolve, reject) => {
    if (typeof document === "undefined") return resolve();
    if (window.google?.accounts?.oauth2) return resolve();
    const existing = document.querySelector<HTMLScriptElement>(
      'script[src="https://accounts.google.com/gsi/client"]'
    );
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () =>
        reject(new Error("failed to load Google Identity Services"))
      );
      return;
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("failed to load Google Identity Services"));
    document.head.appendChild(s);
  });
  return gisPromise;
}

export function googleDocsConfigured(): boolean {
  return !!CLIENT_ID;
}

// Prompt for a short-lived Drive access token. `drive.file` is least-privilege:
// it only grants access to files this app creates, not the user's whole Drive.
async function getDriveAccessToken(): Promise<string> {
  await loadGis();
  const oauth2 = window.google?.accounts?.oauth2;
  if (!oauth2) throw new Error("Google Identity Services unavailable");
  return new Promise<string>((resolve, reject) => {
    const client = oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: "https://www.googleapis.com/auth/drive.file",
      callback: (resp: { access_token?: string; error?: string }) => {
        if (resp.error || !resp.access_token) {
          reject(new Error(resp.error || "Google authorization was cancelled"));
          return;
        }
        resolve(resp.access_token);
      },
      error_callback: (err: { message?: string }) =>
        reject(new Error(err?.message || "Google authorization failed")),
    });
    client.requestAccessToken();
  });
}

// Upload the draft as a .docx to Drive, asking Drive to convert it into a
// native Google Doc on the way in. Returns the doc's editable URL.
export async function exportToGoogleDocs(text: string, title: string): Promise<string> {
  if (!CLIENT_ID) throw new Error("Google is not configured for this deployment");
  const token = await getDriveAccessToken();
  const blob = await draftToDocxBlob(text);

  const metadata = {
    name: title,
    mimeType: "application/vnd.google-apps.document", // convert docx -> Google Doc
  };
  const form = new FormData();
  form.append(
    "metadata",
    new Blob([JSON.stringify(metadata)], { type: "application/json" })
  );
  form.append("file", new Blob([blob], { type: DOCX_MIME }));

  const res = await fetch(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink",
    { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form }
  );
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as any));
    throw new Error(body?.error?.message || `Google Drive upload failed (${res.status})`);
  }
  const data = await res.json();
  return data.webViewLink || `https://docs.google.com/document/d/${data.id}/edit`;
}
