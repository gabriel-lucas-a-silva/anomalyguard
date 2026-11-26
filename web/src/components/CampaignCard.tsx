import { useState } from "react";
import { SIZES, duration } from "../accuracy";
import type { Campaign } from "../accuracy";

type Props = {
  campaign: Campaign | null;
  faultCount: number;
  busy: boolean;
  error: string | null;
  onStart: (perFault: number) => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
};

const PHASES = { calm_wait: "Esperando o Demo ficar calmo", fault_on: "Falha ligada", analyzing: "Analisando" };

export function CampaignCard({ campaign, faultCount, busy, error, onStart, onPause, onResume, onStop }: Props) {
  const [size, setSize] = useState<number>(12);
  const [fresh, setFresh] = useState(false);
  const live = campaign && (campaign.state === "running" || campaign.state === "paused");

  if (live) {
    const percent = (campaign.done / campaign.total) * 100;
    const paused = campaign.state === "paused";
    return (
      <section className="campaign" aria-label="Campanha em andamento">
        <div className="campaign-top">
          <div>
            <h2>{paused ? "Campanha pausada" : "Campanha em andamento"}</h2>
            <p className="muted">
              {campaign.done} de {campaign.total} casos
              {campaign.eta_s !== null && !paused && ` · faltam cerca de ${duration(campaign.eta_s)}`}
            </p>
          </div>
          <div className="campaign-actions">
            {paused ? (
              <button className="btn primary" onClick={onResume} disabled={busy}>
                Retomar
              </button>
            ) : (
              <button className="btn" onClick={onPause} disabled={busy}>
                Pausar
              </button>
            )}
            <button className="btn ghost danger" onClick={onStop} disabled={busy}>
              Parar
            </button>
          </div>
        </div>
        <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={campaign.total} aria-valuenow={campaign.done}>
          <div className="progress-fill" style={{ width: `${percent}%` }} />
        </div>
        {paused && campaign.pause_reason && (
          <p className="campaign-reason" role="alert">
            {campaign.pause_reason}
          </p>
        )}
        {error && (
          <p className="campaign-reason" role="alert">
            {error}
          </p>
        )}
        {campaign.current && !paused && (
          <p className="campaign-now">
            <span className="pulse-dot" aria-hidden="true" />
            <strong>{PHASES[campaign.current.phase]}</strong>
            <span className="muted">
              {campaign.current.title} · {campaign.current.detail}
            </span>
          </p>
        )}
      </section>
    );
  }

  const finished = campaign && !fresh;
  if (finished) {
    return (
      <section className="campaign" aria-label="Campanha">
        <div className="campaign-top">
          <div>
            <h2>{campaign.state === "finished" ? "Campanha concluída" : "Campanha interrompida"}</h2>
            <p className="muted">
              {campaign.done} de {campaign.total} casos rodados. Os números abaixo já incluem todos eles.
            </p>
          </div>
          <button className="btn" onClick={() => setFresh(true)}>
            Nova campanha
          </button>
        </div>
      </section>
    );
  }

  const total = size * faultCount;
  const hours = Math.round((total * 20) / 60);
  return (
    <section className="campaign" aria-label="Nova campanha">
      <div className="campaign-top">
        <div>
          <h2>Rodar campanha</h2>
          <p className="muted">Roda os incidentes em sequência, sozinha, e atualiza os números abaixo a cada caso.</p>
        </div>
      </div>
      <div className="campaign-form">
        <div className="segmented" role="radiogroup" aria-label="Tamanho da campanha">
          {SIZES.map((option) => (
            <button key={option.key} role="radio" aria-checked={size === option.key} aria-selected={size === option.key} onClick={() => setSize(option.key)}>
              {option.label}
              <span className="count">{option.key}</span>
            </button>
          ))}
        </div>
        <p className="campaign-plan">
          <strong>{total} casos</strong>
          <span className="muted">
            {faultCount} falhas × {size} · cerca de {hours} h
          </span>
        </p>
        <button
          className="btn primary"
          disabled={busy}
          onClick={() => {
            setFresh(false);
            onStart(size);
          }}
        >
          Iniciar campanha
        </button>
      </div>
      {error && (
        <p className="campaign-reason" role="alert">
          {error}
        </p>
      )}
      <ul className="campaign-notes">
        <li>As falhas entram em ordem embaralhada.</li>
        <li>Entre um caso e outro, espera o Demo ficar calmo, sem alertas nem erros.</li>
        <li>Não gera a explicação do Gemini, só o ranking.</li>
        <li>Deixe o computador ligado e sem suspender.</li>
      </ul>
    </section>
  );
}
