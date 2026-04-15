import test from "node:test";
import assert from "node:assert/strict";

import { extractStreamEnvelopes } from "../.tmp-tests/stores/stream-envelope.js";

test("extractStreamEnvelopes keeps direct updates unchanged", () => {
  const envelopes = extractStreamEnvelopes({
    event: "requests.updated",
    data: {
      topic: "requests.updated",
      scope: { project_id: "mykms", source_id: "main" },
      generated_at: "2026-04-15T22:46:44.280+08:00",
      payload: [{ request_id: "req-direct" }],
    },
  });

  assert.equal(envelopes.length, 1);
  assert.equal(envelopes[0].topic, "requests.updated");
  assert.deepEqual(envelopes[0].payload, [{ request_id: "req-direct" }]);
});

test("extractStreamEnvelopes unwraps real stream.batch wire payload", () => {
  const envelopes = extractStreamEnvelopes({
    event: "stream.batch",
    data: {
      count: 2,
      topics: ["overview.updated", "requests.updated"],
      items: [
        {
          event: "overview.updated",
          topic: "overview.updated",
          data: {
            topic: "overview.updated",
            scope: { project_id: "mykms", source_id: "main" },
            generated_at: "2026-04-15T22:46:44.280+08:00",
            payload: { request_count: 9 },
          },
        },
        {
          event: "requests.updated",
          topic: "requests.updated",
          data: {
            topic: "requests.updated",
            scope: { project_id: "mykms", source_id: "main" },
            generated_at: "2026-04-15T22:46:44.280+08:00",
            payload: [{ request_id: "req-batch" }],
          },
        },
      ],
    },
  });

  assert.equal(envelopes.length, 2);
  assert.equal(envelopes[0].topic, "overview.updated");
  assert.deepEqual(envelopes[0].payload, { request_count: 9 });
  assert.equal(envelopes[1].topic, "requests.updated");
  assert.deepEqual(envelopes[1].payload, [{ request_id: "req-batch" }]);
});
