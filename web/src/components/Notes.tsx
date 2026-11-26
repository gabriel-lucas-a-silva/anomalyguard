import type { Summary } from "../types";

export function Notes({ summary }: { summary: Summary }) {
  const chips: string[] = [];
  if (summary.replay_of) chips.push(`Reprodução do caso ${summary.replay_of}, com os dados gravados na época`);
  if (summary.grouped_alerts > 1) chips.push(`${summary.grouped_alerts} alertas agrupados`);
  if (summary.resolved_before_analysis) chips.push("O alerta se resolveu antes da análise");
  if (chips.length === 0) return null;
  return (
    <ul className="chips" aria-label="Observações">
      {chips.map((text) => (
        <li key={text}>{text}</li>
      ))}
    </ul>
  );
}
