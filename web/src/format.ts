import type { State } from "./types";

const dateTime = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const clock = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const hourMinute = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

export const STAGES = ["Alerta", "Espera", "Coleta", "Preparo", "Análise", "Relatório", "Concluída"];

export function parseInstant(value: string): Date {
  return new Date(value.replace(/(\.\d{3})\d+/, "$1"));
}

export function formatDateTime(value: string): string {
  return dateTime.format(parseInstant(value)).replace(".", "");
}

export function formatClock(value: string): string {
  return clock.format(parseInstant(value));
}

export function formatHourMinute(value: string): string {
  return hourMinute.format(parseInstant(value));
}

export function formatPercent(share: number): string {
  const percent = share * 100;
  if (percent > 0 && percent < 1) return "<1";
  return String(Math.round(percent));
}

export function isTerminal(state: State): boolean {
  return state === "completed" || state === "failed";
}

export function isRunning(state: State): boolean {
  return !isTerminal(state);
}

export type TextPart = { type: "text"; value: string } | { type: "cite"; value: number };

export function splitCitations(text: string, writing = false): TextPart[] {
  const visible = writing ? text.replace(/\[\d*$/, "") : text;
  return visible
    .split(/(\[\d+\])/g)
    .filter((part) => part !== "")
    .map((part): TextPart => {
      const match = part.match(/^\[(\d+)\]$/);
      return match ? { type: "cite", value: Number(match[1]) } : { type: "text", value: part };
    });
}
