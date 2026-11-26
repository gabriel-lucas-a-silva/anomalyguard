import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { TrashIcon } from "./Icons";

type Props = {
  label: string;
  iconOnly?: boolean;
  disabled?: boolean;
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
};

export function ConfirmDelete({ label, iconOnly = false, disabled = false, title, message, confirmLabel, onConfirm }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível falar com o back-end.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="menu-wrap" ref={wrap}>
      <button
        className={"btn ghost danger" + (iconOnly ? " icon" : "")}
        disabled={disabled}
        aria-label={label}
        aria-expanded={open}
        title={label}
        onClick={() => {
          setError(null);
          setOpen((current) => !current);
        }}
      >
        <TrashIcon />
        {!iconOnly && <span>{label}</span>}
      </button>
      {open && (
        <div className="popover" role="alertdialog" aria-label={title}>
          <p>
            <strong>{title}</strong>
          </p>
          <p>{message}</p>
          <div className="popover-actions">
            <button className="btn solid-danger" onClick={() => void run()} disabled={busy}>
              {busy ? "Apagando..." : confirmLabel}
            </button>
            <button className="link" onClick={() => setOpen(false)} disabled={busy}>
              Cancelar
            </button>
          </div>
          {error && (
            <p className="popover-error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
