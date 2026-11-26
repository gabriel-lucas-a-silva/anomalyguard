import type { ConnectionStatus } from "../stream";

const LABELS: Record<ConnectionStatus, string> = {
  live: "Ao vivo",
  connecting: "Conectando…",
  reconnecting: "Reconectando…",
};

export function LiveBadge({ status }: { status: ConnectionStatus }) {
  return (
    <span className={"live " + status} role="status">
      <span className="dot" aria-hidden="true" />
      {LABELS[status]}
    </span>
  );
}
