import { STAGES } from "../format";
import type { Summary } from "../types";

export function Stepper({ summary }: { summary: Summary }) {
  return (
    <ol className="stepper" aria-label="Etapas da investigação">
      {STAGES.map((label, index) => {
        const finished = summary.state === "completed" || index < summary.stage;
        const current = index === summary.stage;
        const state = finished ? "finished" : current ? (summary.state === "failed" ? "failed" : "active") : "todo";
        return (
          <li key={label} className={state}>
            <span className="bar" />
            <span className="label">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
