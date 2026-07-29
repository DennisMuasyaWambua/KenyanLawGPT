export interface ToastData {
  kind: 'success' | 'error';
  text: string;
}

export function Toast({ toast, onDismiss }: { toast: ToastData | null; onDismiss: () => void }) {
  if (!toast) return null;
  return (
    <div className={`toast toast-${toast.kind}`} role="status">
      <span>{toast.text}</span>
      <button className="icon-btn" onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}
