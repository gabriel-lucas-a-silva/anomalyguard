import type { DemoIncident } from "./types";

export const FINISHED_VISIBLE_MS = 15 * 60 * 1000;

export type Tone = "active" | "done" | "error";

export type Message = {
  tone: Tone;
  title: string;
  detail: string;
};

export function remainingSeconds(incident: DemoIncident, nowMs: number): number {
  return Math.max(0, Math.round((Date.parse(incident.ends_at) - nowMs) / 1000));
}

export function countdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export const ALERT_LATE_MS = 5 * 60 * 1000;

export function describeIncident(incident: DemoIncident, nowMs: number = Date.parse(incident.started_at)): Message {
  switch (incident.state) {
    case "active":
      if (incident.investigation_id) {
        return { tone: "active", title: "Simulação em andamento", detail: "O alerta real disparou e a investigação foi aberta." };
      }
      if (nowMs - Date.parse(incident.started_at) > ALERT_LATE_MS) {
        return {
          tone: "active",
          title: "Simulação em andamento",
          detail: "Passaram mais de 5 minutos e o alerta não abriu uma investigação. Se uma simulação terminou há pouco, o alerta anterior ainda pode estar ativo: espere o alerta resolver e tente de novo, de preferência com uns 15 minutos de intervalo.",
        };
      }
      return { tone: "active", title: "Simulação em andamento", detail: `${incident.title ?? "A falha"} está ligada no Demo. Aguardando o alerta real, que costuma disparar em cerca de 3 minutos.` };
    case "finished":
      return { tone: "done", title: "Simulação encerrada", detail: "A falha desligou sozinha no horário previsto." };
    case "stopped":
      return { tone: "done", title: "Simulação interrompida", detail: "A falha foi desligada antes do fim." };
    default:
      return {
        tone: "error",
        title: "A falha pode ter ficado ligada",
        detail: `${incident.failure_reason ?? "Não foi possível desligá-la."} Desligue a falha no Demo.`,
      };
  }
}

export function shouldShow(incident: DemoIncident | null, nowMs: number, dismissedId: number | null): boolean {
  if (!incident) return false;
  if (incident.state === "active" || incident.state === "failed") return true;
  if (dismissedId === incident.id) return false;
  const finishedAt = incident.finished_at ? Date.parse(incident.finished_at) : Date.parse(incident.ends_at);
  return nowMs - finishedAt < FINISHED_VISIBLE_MS;
}
