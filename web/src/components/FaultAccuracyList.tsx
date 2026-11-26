import { percent } from "../accuracy";
import type { FaultAccuracy } from "../accuracy";
import { RateBar } from "./RateCard";

export function FaultAccuracyList({ faults }: { faults: FaultAccuracy[] }) {
  return (
    <ul className="fault-acc">
      {faults.map((fault) => (
        <li key={fault.kind}>
          <div className="fault-acc-name">
            <strong>{fault.title}</strong>
            <span className="muted">
              {fault.evaluated} avaliados de {fault.planned}
              {fault.no_alert > 0 && ` · ${fault.no_alert} sem alerta`}
            </span>
          </div>
          <div className="fault-acc-bars">
            <div className="fault-acc-bar">
              <span className="muted">Top 1</span>
              <RateBar rate={fault.top1} />
              <span className="fault-acc-pct">{percent(fault.top1.rate)}</span>
            </div>
            <div className="fault-acc-bar">
              <span className="muted">Top 3</span>
              <RateBar rate={fault.top3} tone="ok" />
              <span className="fault-acc-pct">{percent(fault.top3.rate)}</span>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
