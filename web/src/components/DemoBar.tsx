import { useEffect, useState } from "react";
import { countdown, describeIncident, remainingSeconds, shouldShow } from "../demo";
import { formatHourMinute } from "../format";
import type { DemoControl } from "../hooks";

const KEY = "anomalyguard.dismissed-demo-incident";

function readDismissed(): number | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === null ? null : Number(value);
  } catch {
    return null;
  }
}

function saveDismissed(id: number) {
  try {
    window.localStorage.setItem(KEY, String(id));
  } catch {
    return;
  }
}

export function DemoBar({ demo }: { demo: DemoControl }) {
  const [now, setNow] = useState(() => Date.now());
  const [dismissed, setDismissed] = useState<number | null>(() => readDismissed());
  const incident = demo.incident;

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!demo.enabled || !incident || !shouldShow(incident, now, dismissed)) return null;

  const message = describeIncident(incident, now);
  const active = incident.state === "active";

  return (
    <div className={"demo-bar " + message.tone} role="status">
      <div className="demo-bar-inner">
        <div className="demo-text">
          <strong>{message.title}</strong>
          <span>{message.detail}</span>
          {active && (
            <span className="demo-times">
              Ligada às {formatHourMinute(incident.started_at)} · desliga às {formatHourMinute(incident.ends_at)}
            </span>
          )}
        </div>
        <div className="demo-actions">
          {active && <span className="demo-count">{countdown(remainingSeconds(incident, now))}</span>}
          {incident.investigation_id && (
            <a className="btn" href={"#/i/" + incident.investigation_id}>
              Ver {incident.investigation_id}
            </a>
          )}
          {active && (
            <button className="btn" onClick={() => void demo.stop()} disabled={demo.busy}>
              Parar agora
            </button>
          )}
          {!active && incident.state !== "failed" && (
            <button
              className="link"
              onClick={() => {
                saveDismissed(incident.id);
                setDismissed(incident.id);
              }}
            >
              Fechar
            </button>
          )}
        </div>
      </div>
      {demo.error && (
        <p className="demo-error" role="alert">
          {demo.error}
        </p>
      )}
    </div>
  );
}
