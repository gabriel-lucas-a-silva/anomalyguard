export type ConnectionStatus = "connecting" | "live" | "reconnecting";

export type Handlers = Record<string, (data: unknown) => void>;

export type SourceFactory = (url: string) => EventSource;

const defaultFactory: SourceFactory = (url) => new EventSource(url);

export function openStream(url: string, handlers: Handlers, onStatus: (status: ConnectionStatus) => void, factory: SourceFactory = defaultFactory): () => void {
  const source = factory(url);
  onStatus("connecting");
  source.onopen = () => onStatus("live");
  source.onerror = () => onStatus("reconnecting");
  for (const [name, handler] of Object.entries(handlers)) {
    source.addEventListener(name, (event) => {
      try {
        handler(JSON.parse((event as MessageEvent).data));
      } catch {
        return;
      }
    });
  }
  return () => source.close();
}
