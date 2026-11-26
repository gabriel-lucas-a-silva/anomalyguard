import { STAGES } from "../format";
import type { Summary } from "../types";

export function StatusPill({ summary }: { summary: Summary }) {
  const label = summary.state === "completed" ? "Concluída" : summary.state === "failed" ? "Falhou" : STAGES[summary.stage];
  const kind = summary.state === "completed" ? "done" : summary.state === "failed" ? "failed" : "running";
  return (
    <span className={"pill " + kind}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
}
