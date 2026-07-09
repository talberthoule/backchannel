import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

// One small primitive for the app's destructive-action guard: an accessible
// confirm dialog (Promise-based) plus a lightweight feedback toast. Wrap the
// app once in <ConfirmProvider>; call useConfirm() anywhere.

interface ConfirmOptions {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "default";
}

interface ToastItem {
  id: number;
  message: string;
}

interface ConfirmContextValue {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
  toast: (message: string) => void;
}

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function useConfirm(): ConfirmContextValue {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}

type PendingDialog = ConfirmOptions & { resolve: (value: boolean) => void };

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [dialog, setDialog] = useState<PendingDialog | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  const confirm = useCallback(
    (opts: ConfirmOptions) => new Promise<boolean>((resolve) => setDialog({ ...opts, resolve })),
    [],
  );

  const toast = useCallback((message: string) => {
    const id = ++nextId.current;
    setToasts((prev) => [...prev, { id, message }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const settle = useCallback((value: boolean) => {
    setDialog((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);

  // Focus the confirm button and wire Escape when a dialog opens.
  useEffect(() => {
    if (!dialog) return;
    confirmBtnRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") settle(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dialog, settle]);

  const danger = dialog?.tone !== "default";

  return (
    <ConfirmContext.Provider value={{ confirm, toast }}>
      {children}

      {dialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
          onClick={() => settle(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl border border-brand-light-gray-1 bg-surface p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="confirm-title" className="font-display text-base font-semibold text-brand-dark-gray">
              {dialog.title ?? "Are you sure?"}
            </h2>
            <p className="mt-1.5 font-body text-sm text-brand-gray">{dialog.message}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => settle(false)}
                className="rounded-lg px-3 py-1.5 font-body text-sm font-medium text-brand-gray transition-colors hover:bg-brand-light-gray-2"
              >
                {dialog.cancelLabel ?? "Cancel"}
              </button>
              <button
                ref={confirmBtnRef}
                onClick={() => settle(true)}
                className={`rounded-lg px-3 py-1.5 font-body text-sm font-semibold text-white transition-colors ${
                  danger ? "bg-red-600 hover:bg-red-700" : "bg-brand-teal hover:bg-brand-teal-dark"
                }`}
              >
                {dialog.confirmLabel ?? "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}

      {toasts.length > 0 && (
        <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              className="animate-slide-in-right rounded-lg bg-slate-800 px-4 py-2 font-body text-sm text-white shadow-lg"
              role="status"
            >
              {t.message}
            </div>
          ))}
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
