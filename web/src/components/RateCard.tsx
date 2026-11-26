import { interval, percent } from "../accuracy";
import type { Rate } from "../accuracy";

type Props = {
  label: string;
  hint: string;
  rate: Rate;
  unit: string;
  tone?: "ink" | "ok";
};

export function RateBar({ rate, tone = "ink" }: { rate: Rate; tone?: "ink" | "ok" }) {
  const width = (rate.rate ?? 0) * 100;
  const low = (rate.low ?? 0) * 100;
  const high = (rate.high ?? 0) * 100;
  return (
    <div className="rate-bar" role="img" aria-label={`${percent(rate.rate)}, ${interval(rate)}`}>
      <div className={"rate-fill " + tone} style={{ width: `${width}%` }} />
      {rate.low !== null && <div className="rate-whisker" style={{ left: `${low}%`, width: `${Math.max(high - low, 0.5)}%` }} />}
    </div>
  );
}

export function RateCard({ label, hint, rate, unit, tone = "ink" }: Props) {
  return (
    <section className="rate-card" aria-label={label}>
      <p className="rate-label">{label}</p>
      <p className="rate-hint">{hint}</p>
      <p className="rate-value">
        {rate.rate === null ? "–" : Math.round(rate.rate * 100)}
        {rate.rate !== null && <span className="rate-unit">%</span>}
      </p>
      <RateBar rate={rate} tone={tone} />
      <p className="rate-foot">
        <span>
          {rate.hits} de {rate.of} {unit}
        </span>
        <span className="muted">{interval(rate)}</span>
      </p>
    </section>
  );
}
