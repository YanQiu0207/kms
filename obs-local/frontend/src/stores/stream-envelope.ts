import type { StreamBatchItem, StreamBatchPayload, StreamEnvelope } from "../types/observability";

export interface IncomingStreamMessage {
  event: string;
  data: unknown;
}

function isObjectPayload(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function isStreamEnvelope(value: unknown): value is StreamEnvelope {
  if (!isObjectPayload(value)) {
    return false;
  }
  return (
    typeof value.topic === "string"
    && isObjectPayload(value.scope)
    && "payload" in value
  );
}

function isStreamBatchPayload(value: unknown): value is StreamBatchPayload {
  if (!isObjectPayload(value)) {
    return false;
  }
  return Array.isArray(value.items) && Array.isArray(value.topics) && typeof value.count === "number";
}

function normalizeBatchItem(item: StreamBatchItem): StreamEnvelope | null {
  if (!isStreamEnvelope(item?.data)) {
    return null;
  }
  return item.data;
}

export function extractStreamEnvelopes(message: IncomingStreamMessage): StreamEnvelope[] {
  if (message.event === "stream.batch") {
    if (!isStreamBatchPayload(message.data)) {
      return [];
    }
    return message.data.items
      .map(normalizeBatchItem)
      .filter((item): item is StreamEnvelope => item !== null);
  }
  if (!isStreamEnvelope(message.data)) {
    return [];
  }
  return [message.data];
}
