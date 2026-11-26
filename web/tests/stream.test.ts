import { describe, expect, it } from "vitest";
import { openStream, type ConnectionStatus } from "../src/stream";

class FakeSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  listeners: Record<string, (event: { data: string }) => void> = {};

  addEventListener(name: string, listener: (event: { data: string }) => void) {
    this.listeners[name] = listener;
  }

  emit(name: string, data: unknown) {
    this.listeners[name]({ data: JSON.stringify(data) });
  }

  close() {
    this.closed = true;
  }
}

function open(handlers: Record<string, (data: unknown) => void>) {
  const source = new FakeSource();
  const statuses: ConnectionStatus[] = [];
  const close = openStream("http://x/events", handlers, (s) => statuses.push(s), () => source as unknown as EventSource);
  return { source, statuses, close };
}

describe("openStream", () => {
  it("reports connecting, then live when the connection opens", () => {
    const { source, statuses } = open({});
    source.onopen?.();
    expect(statuses).toEqual(["connecting", "live"]);
  });

  it("reports reconnecting when the connection drops", () => {
    const { source, statuses } = open({});
    source.onopen?.();
    source.onerror?.();
    expect(statuses).toEqual(["connecting", "live", "reconnecting"]);
  });

  it("parses the JSON of each named event for its handler", () => {
    const received: unknown[] = [];
    const { source } = open({ stage: (data) => received.push(data) });
    source.emit("stage", { state: "collecting", stage: 2 });
    expect(received).toEqual([{ state: "collecting", stage: 2 }]);
  });

  it("ignores an event whose data is not valid JSON", () => {
    const received: unknown[] = [];
    const { source } = open({ log: (data) => received.push(data) });
    source.listeners["log"]({ data: "{quebrado" });
    expect(received).toEqual([]);
  });

  it("closes the connection", () => {
    const { source, close } = open({});
    close();
    expect(source.closed).toBe(true);
  });
});
