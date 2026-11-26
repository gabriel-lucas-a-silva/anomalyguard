import { useState } from "react";
import type { DemoControl } from "../hooks";
import { DemoModal } from "./DemoModal";

export function Topbar({ demo }: { demo: DemoControl }) {
  const [open, setOpen] = useState(false);
  const active = demo.incident?.state === "active";

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <a className="brand" href="#/">
          <span className="mark" aria-hidden="true" />
          AnomalyGuard
        </a>
        {demo.enabled && (
          <div className="simulate">
            <button
              className="btn"
              disabled={active || demo.busy}
              aria-haspopup="dialog"
              onClick={() => {
                demo.clearError();
                setOpen(true);
              }}
            >
              Simular incidente
            </button>
          </div>
        )}
      </div>
      {open && !active && <DemoModal busy={demo.busy} error={demo.error} onStart={demo.start} onClose={() => setOpen(false)} />}
    </header>
  );
}
