"use client";

import { useEffect, useState } from "react";
import { useEditor, EditorContent, Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Collaboration from "@tiptap/extension-collaboration";
import CollaborationCursor from "@tiptap/extension-collaboration-cursor";
import Placeholder from "@tiptap/extension-placeholder";
import * as Y from "yjs";
import { HocuspocusProvider } from "@hocuspocus/provider";
import { collabUrl, userColor } from "@/lib/collab";
import { currentUser } from "@/lib/api";

// A live collaborator (from Yjs awareness) for the "who's here" strip.
type Peer = { name: string; color: string; clientId: number };

// The editor surface is a child so useEditor() is only constructed once the
// Hocuspocus provider (and its Yjs doc) exist — Collaboration needs both up front.
function Surface({
  provider,
  ydoc,
  onEditor,
}: {
  provider: HocuspocusProvider;
  ydoc: Y.Doc;
  onEditor: (e: Editor | null) => void;
}) {
  const me = currentUser();
  const editor = useEditor({
    // History is disabled: the Collaboration extension supplies shared undo/redo.
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({ history: false }),
      Placeholder.configure({ placeholder: "Start typing — everyone with access sees changes live…" }),
      Collaboration.configure({ document: ydoc }),
      CollaborationCursor.configure({
        provider,
        user: {
          name: me?.full_name || me?.email || "Member",
          color: userColor(me?.id || "me"),
        },
      }),
    ],
    editorProps: { attributes: { class: "tiptap" } },
  });

  useEffect(() => {
    onEditor(editor);
    return () => onEditor(null);
  }, [editor, onEditor]);

  if (!editor) return <p className="text-sm text-navy/40">Loading editor…</p>;
  return <EditorContent editor={editor} />;
}

function Toolbar({ editor }: { editor: Editor | null }) {
  if (!editor) return null;
  const Btn = ({ on, active, label }: { on: () => void; active: boolean; label: string }) => (
    <button
      type="button"
      onMouseDown={(e) => e.preventDefault()}
      onClick={on}
      className={`rounded px-2 py-1 text-xs font-semibold transition ${
        active ? "bg-navy text-white" : "text-navy/70 hover:bg-navy/5"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-navy/10 pb-2">
      <Btn on={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")} label="B" />
      <Btn on={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")} label="i" />
      <Btn on={() => editor.chain().focus().toggleStrike().run()} active={editor.isActive("strike")} label="S" />
      <span className="mx-1 h-4 w-px bg-navy/15" />
      <Btn on={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive("heading", { level: 1 })} label="H1" />
      <Btn on={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive("heading", { level: 2 })} label="H2" />
      <Btn on={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} active={editor.isActive("heading", { level: 3 })} label="H3" />
      <span className="mx-1 h-4 w-px bg-navy/15" />
      <Btn on={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")} label="• List" />
      <Btn on={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")} label="1. List" />
      <Btn on={() => editor.chain().focus().toggleBlockquote().run()} active={editor.isActive("blockquote")} label="❝" />
      <span className="mx-1 h-4 w-px bg-navy/15" />
      <Btn on={() => editor.chain().focus().undo().run()} active={false} label="↶" />
      <Btn on={() => editor.chain().focus().redo().run()} active={false} label="↷" />
    </div>
  );
}

export default function CollabEditor({ docId }: { docId: string }) {
  const [ydoc] = useState(() => new Y.Doc());
  const [provider, setProvider] = useState<HocuspocusProvider | null>(null);
  const [status, setStatus] = useState<"connecting" | "connected" | "unauthorized">("connecting");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [peers, setPeers] = useState<Peer[]>([]);

  useEffect(() => {
    const token =
      typeof localStorage !== "undefined" ? localStorage.getItem("wakili_access") || "" : "";
    const p = new HocuspocusProvider({
      url: collabUrl(),
      name: docId,
      document: ydoc,
      token,
      onStatus: (e: { status: string }) =>
        setStatus(e.status === "connected" ? "connected" : "connecting"),
      onAuthenticationFailed: () => setStatus("unauthorized"),
    });

    // Reflect the awareness state (live peers) for the presence strip.
    const sync = () => {
      const states = Array.from(p.awareness?.getStates()?.entries() || []) as [number, any][];
      setPeers(
        states
          .filter(([, s]) => s?.user)
          .map(([clientId, s]) => ({ clientId, name: s.user.name, color: s.user.color }))
      );
    };
    p.awareness?.on("change", sync);
    setProvider(p);

    return () => {
      p.awareness?.off("change", sync);
      p.destroy();
    };
  }, [docId, ydoc]);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              status === "connected"
                ? "bg-green-500"
                : status === "unauthorized"
                ? "bg-red-500"
                : "bg-amber-400"
            }`}
          />
          <span className="text-navy/60">
            {status === "connected"
              ? "Live — changes sync in real time"
              : status === "unauthorized"
              ? "You don't have access to this document"
              : "Connecting…"}
          </span>
        </div>
        {/* Presence: coloured initials for everyone currently in the doc. */}
        <div className="flex -space-x-1.5">
          {peers.slice(0, 6).map((p) => (
            <span
              key={p.clientId}
              title={p.name}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-white text-[10px] font-bold text-white"
              style={{ backgroundColor: p.color }}
            >
              {(p.name || "?").trim().charAt(0).toUpperCase()}
            </span>
          ))}
        </div>
      </div>
      <div className="flex flex-1 flex-col overflow-hidden rounded-lg border border-navy/10 bg-white">
        <div className="px-4 pt-3">
          <Toolbar editor={editor} />
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {provider ? (
            <Surface provider={provider} ydoc={ydoc} onEditor={setEditor} />
          ) : (
            <p className="text-sm text-navy/40">Loading…</p>
          )}
        </div>
      </div>
    </div>
  );
}
