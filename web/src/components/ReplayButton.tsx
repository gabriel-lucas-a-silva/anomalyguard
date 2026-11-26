import { useState } from "react";
import { startReplay } from "../api";
import { ReplayIcon } from "./Icons";

export function ReplayButton({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await startReplay(id);
      window.location.hash = "#/i/" + created.id;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível falar com o back-end.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="menu-wrap">
      <button className="btn" onClick={() => void run()} disabled={busy} title="Roda a análise de novo sobre os dados gravados deste caso, sem esperar o alerta nem usar o Demo">
        <ReplayIcon />
        <span>{busy ? "Reproduzindo..." : "Reproduzir este caso"}</span>
      </button>
      {error && (
        <span className="toolbar-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
