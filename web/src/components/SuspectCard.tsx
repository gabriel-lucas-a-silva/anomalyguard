import { formatPercent } from "../format";
import type { Suspect } from "../types";

export function SuspectCard({ suspect }: { suspect: Suspect }) {
  const rank = suspect.rank;
  const percent = formatPercent(suspect.share);
  return (
    <article className={rank === 1 ? "suspect first" : "suspect"}>
      <header>
        <span className="rank">{rank}</span>
        <span className="rank-label">{rank === 1 ? "Mais provável" : rank === 2 ? "Segundo" : "Terceiro"}</span>
      </header>
      <h3>{suspect.service}</h3>
      <div className="share">
        <strong>{percent}</strong>
        <span>%</span>
      </div>
      <div className="meter" role="img" aria-label={`${percent}% da anomalia`}>
        <span style={{ width: Math.min(100, suspect.share * 100) + "%" }} />
      </div>
      <p className="signal">{suspect.signal}</p>
      <p className="detail">{suspect.detail}</p>
    </article>
  );
}

export function SuspectPlaceholder({ rank }: { rank: number }) {
  return (
    <article className="suspect placeholder" aria-hidden="true">
      <header>
        <span className="rank">{rank}</span>
      </header>
      <div className="skeleton wide" />
      <div className="skeleton big" />
      <div className="skeleton" />
    </article>
  );
}
