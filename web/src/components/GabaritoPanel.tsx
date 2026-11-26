import { verdict } from "../gabarito";
import type { Detail } from "../types";

export function GabaritoPanel({ detail }: { detail: Detail }) {
  if (!detail.gabarito) return null;
  const message = verdict(detail.gabarito);
  if (!message) return null;
  return (
    <section className={"gab " + message.tone} aria-label="Gabarito" role="status">
      <div className="gab-text">
        <strong>{message.title}</strong>
        <span>{message.detail}</span>
      </div>
    </section>
  );
}
