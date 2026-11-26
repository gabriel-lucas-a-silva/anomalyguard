import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { fetchDemoFaults } from "../api";
import type { DemoFault } from "../types";

type Props = {
  busy: boolean;
  error: string | null;
  onStart: (kind: string) => Promise<boolean>;
  onClose: () => void;
};

export function DemoModal({ busy, error, onStart, onClose }: Props) {
  const [faults, setFaults] = useState<DemoFault[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchDemoFaults()
      .then((list) => {
        if (alive) setFaults(list);
      })
      .catch(() => {
        if (alive) setLoadError(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const begin = async () => {
    if (selected && (await onStart(selected))) onClose();
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <header className="modal-head">
          <h2 id="modal-title">Simular incidente</h2>
          <p>
            Escolha a falha que será ligada <strong>de verdade</strong> no Demo por 7 minutos. O alerta real costuma disparar em cerca de 3 minutos, e a investigação aparece sozinha na lista.
          </p>
        </header>

        {loadError && (
          <p className="modal-note error" role="alert">
            Não foi possível carregar as opções. Confira se o back-end está no ar.
          </p>
        )}
        {!faults && !loadError && <p className="modal-note">Carregando as opções...</p>}

        {faults && (
          <div className="fault-list" role="radiogroup" aria-label="Incidente a simular">
            {faults.map((fault) => (
              <button
                key={fault.kind}
                type="button"
                role="radio"
                aria-checked={selected === fault.kind}
                className={"fault" + (selected === fault.kind ? " selected" : "")}
                onClick={() => setSelected(fault.kind)}
              >
                <span className="fault-radio" aria-hidden="true" />
                <span className="fault-body">
                  <strong>{fault.title}</strong>
                  <span className="fault-desc">{fault.description}</span>
                  <span className="fault-tags">
                    <span>serviço: {fault.affected_service}</span>
                    <span>alerta: {fault.alert}</span>
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}

        <p className="modal-hint">Entre uma simulação e outra, espere uns 15 minutos: antes disso o alerta anterior pode ainda estar ativo e o período "normal" ainda contém a falha anterior.</p>

        {error && (
          <p className="modal-note error" role="alert">
            {error}
          </p>
        )}

        <footer className="modal-actions">
          <button className="link" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button className="btn primary" onClick={() => void begin()} disabled={!selected || busy}>
            {busy ? "Ligando..." : "Ligar a falha"}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
