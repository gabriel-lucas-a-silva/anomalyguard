import { useEffect, useRef } from "react";
import { formatClock } from "../format";
import type { LogLine } from "../types";

export function LogView({ lines, running, height }: { lines: LogLine[]; running: boolean; height?: number }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (running && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length, running]);

  return (
    <div className="log" ref={box} style={height ? { maxHeight: height } : undefined} role="log" aria-live="polite">
      {lines.map((line, index) => (
        <div className="log-line" key={index}>
          <time>{formatClock(line.at)}</time>
          <span className={"tag tag-" + line.tag}>{line.tag}</span>
          <span className="msg">{line.message}</span>
        </div>
      ))}
      {running && (
        <div className="log-line">
          <time />
          <span className="tag" />
          <span className="cursor" />
        </div>
      )}
    </div>
  );
}
