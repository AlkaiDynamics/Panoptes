# Native inference seam

Reference: [`zhenrez/Interception` PR #4](https://github.com/zhenrez/Interception/pull/4), branch `sandbox/ui-scope-correction`, commit `a7bf0d5df64c4696a081404771c146233c3bce37`. In particular, `interception/server.py`, `interception/bridge.py`, `interception/contracts.py`, and `plugin/README.md` define the current boundary.

Panoptes builds a request and stable key, calls the asynchronous client, and keeps the returned ID in its **existing scheduler node checkpoint**. On a later scheduler run, it polls the same ID; a `None` result means the node stays waiting and other ready work can proceed. Interception owns SQLite, CATCH/RETURN, idempotency, transport, validation, and the caller continuation facility.

```python
from panoptes.inference import InterceptionBackend, inference_key

backend = InterceptionBackend.from_connection(".inference_bridge/connection.json")
checkpoint = {"run_id": run_id, "node": step_id, "iteration": iteration}
key = inference_key(run_id, agent_id, step_id, iteration)
request_id = await backend.submit(
    {"model": "manual", "messages": [{"role": "user", "content": prompt}]},
    key=key, metadata={"caller": {"agent": agent_id, "step": step_id}},
    checkpoint=checkpoint,
)
# Existing workflow state stores (request_id, checkpoint), then yields this node.
# On a later run:
response = await backend.result(request_id, checkpoint=checkpoint)
if response is None:
    pass  # Keep this node waiting; schedule other ready work.
else:
    pass  # Apply response through this node's normal checkpoint/evidence gate.
```

Retrying a submission uses the exact same key, request, metadata, and checkpoint. Interception rejects a changed payload under the same key. A completed response is returned only with the expected request ID and checkpoint; this client does not consume or acknowledge it. The scheduler must commit its own node progress once through its existing state transition. There is **no autonomous scheduler caller yet**, so this is an operational client seam, not an unattended Panoptes inference loop.

The OpenAI-compatible `/v1/chat/completions` endpoint is for third-party frameworks that require it. Panoptes-native work uses the durable API above.
