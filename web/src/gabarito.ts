import type { Gabarito } from "./types";

export type Verdict = {
  tone: "ok" | "error";
  title: string;
  detail: string;
};

export function ordinal(position: number): string {
  return `${position}º`;
}

function where(gabarito: Gabarito): string {
  if (gabarito.rank === null) return "nem apareceu no ranking";
  return `ficou em ${ordinal(gabarito.rank)} lugar${gabarito.top3 ? " (dentro do Top 3)" : ", fora do Top 3"}`;
}

export function verdict(gabarito: Gabarito): Verdict | null {
  if (gabarito.status !== "evaluated") return null;
  const cause = gabarito.root_cause_service;
  if (gabarito.top1) {
    return { tone: "ok", title: "Acertou", detail: `O TORAI apontou ${cause} em 1º lugar, e essa era a causa real.` };
  }
  const picked = gabarito.top_service ? `O TORAI apontou ${gabarito.top_service} em 1º, mas` : "O TORAI errou:";
  return { tone: "error", title: `Errou · a causa real era ${cause}`, detail: `${picked} a causa real era ${cause}, que ${where(gabarito)}.` };
}
