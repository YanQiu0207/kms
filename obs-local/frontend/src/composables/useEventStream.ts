import { ref } from "vue";

import type { TransportState } from "@/types/observability";

const STREAM_EVENT_NAMES = [
  "live",
  "health.updated",
  "overview.updated",
  "requests.updated",
  "errors.updated",
  "stages.updated",
  "replay.progress",
  "stream.batch",
] as const;

export interface StreamMessage {
  event: string;
  data: unknown;
}

export interface EventStreamController {
  state: Readonly<{ value: TransportState }>;
  lastMessageAt: Readonly<{ value: string | null }>;
  connect: () => void;
  pause: () => void;
  resume: () => void;
  dispose: () => void;
}

export function useEventStream(options: {
  url: () => string;
  onMessage: (message: StreamMessage) => void;
  onStatusChange?: (status: TransportState) => void;
}): EventStreamController {
  const state = ref<TransportState>("idle");
  const lastMessageAt = ref<string | null>(null);

  let source: EventSource | null = null;
  let paused = false;

  const applyStatus = (next: TransportState) => {
    state.value = next;
    options.onStatusChange?.(next);
  };

  const closeSource = () => {
    if (source) {
      source.close();
      source = null;
    }
  };

  const handleMessage = (event: MessageEvent<string>) => {
    lastMessageAt.value = new Date().toISOString();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(event.data);
    } catch {
      parsed = null;
    }
    options.onMessage({
      event: event.type,
      data: parsed,
    });
  };

  const connect = () => {
    if (paused || source) {
      return;
    }
    applyStatus(state.value === "idle" ? "connecting" : "reconnecting");
    source = new EventSource(options.url());
    source.onopen = () => {
      applyStatus("live");
    };
    source.onerror = () => {
      if (paused) {
        return;
      }
      applyStatus("reconnecting");
    };
    for (const eventName of STREAM_EVENT_NAMES) {
      source.addEventListener(eventName, handleMessage as EventListener);
    }
  };

  const pause = () => {
    paused = true;
    closeSource();
    applyStatus("paused");
  };

  const resume = () => {
    if (!paused) {
      return;
    }
    paused = false;
    connect();
  };

  const dispose = () => {
    paused = true;
    closeSource();
    applyStatus("idle");
  };

  return {
    state,
    lastMessageAt,
    connect,
    pause,
    resume,
    dispose,
  };
}
