# TokenFlow — English functional demonstration

Use the real-model application at **http://127.0.0.1:8800/**. Prepare architecture and experiment figures in the slide deck; the application is a functional demonstration, not a slide replacement.

## Before presenting

Run `scripts/start-llm.ps1` in a terminal. Download the model before presentation day; startup must not depend on a large live download. Confirm both workers are online and the application identifies Qwen2.5-0.5B-Instruct. Open a new chat. Keep output limits at 64–128 tokens for short examples. CPU responses can take several seconds, especially with concurrent requests.

## Demonstration sequence

| Step | Action | Suggested explanation |
| --- | --- | --- |
| 1. Real inference | Ask: “In two short sentences, explain why an inference service uses more than one worker.” | “This is a local neural model. The response is generated token by token, rather than retrieved from a prepared answer.” |
| 2. Context | Follow up: “What happens if one of those workers stops? Answer briefly.” | “The application sends the selected conversation as context. Each request has its own model state.” |
| 3. Cancellation | Ask for a longer numbered explanation and click **Stop generating** after several tokens. | “Cancellation releases the worker slot, the KV reservation, and the gateway's outstanding count.” |
| 4. Request lifecycle | Open **Service status** and select a request in the table. | “Admission happens before routing. Inside the worker, the request can wait, process its prompt, and then stream generated tokens.” |
| 5. Concurrent generation | Send a small request group, for example 12 requests at 3 requests/second. | “Both independent processes handle requests. Least-outstanding routing counts queued and running work.” |
| 6. Overload | In Test settings select **Traffic surge + admission limits** and send the preset group. | “The gateway rejects work beyond the client budget with HTTP 429. A bounded service protects its workers instead of accepting unlimited backlog.” |
| 7. Multiple clients | Select **Multiple clients + quotas**. | “Client A and Client B have independent admission budgets. They still share compute capacity; quotas alone do not guarantee latency isolation.” |
| 8. Failure and recovery | After the group finishes, stop Worker 1, wait for offline status, then send a new chat request. Restart Worker 1 afterwards. | “New requests go to the surviving worker. An interrupted response can fail; this Demo does not silently replay partial output.” |

Complete the functional portion in about 5–7 minutes, adjusting the number of live requests to the machine's observed response time. Use saved traces if a live CPU run is slow. Show performance comparisons and their variation in the PPT rather than running all repeated trials during presentation.

## Claims to explain accurately

- Two workers are two complete model replicas, serving different requests. This is data-parallel serving, not tensor-parallel model execution.
- Real-model generation now shares projections and MLP computation across requests, while each request has independent Attention and KV state. Continuous admission can replace completed requests at iteration boundaries. The independent-forward path is available as a control in Test settings; simulator results remain separately labelled.
- CPU arithmetic is pinned to FP32. Native BF16 changed greedy tie-breaking under different batch shapes during development; FP32 numerical and generation comparisons were rechecked before the final experiments.
- Client labels are local Demo identities; authentication, paid billing, multi-region deployments and millions of concurrent users are outside the implementation.
- Gateway token budgets use an input-length estimate plus maximum output. The worker uses actual tokenizer input length for its own KV reservation. Neither is an OpenAI billing measurement.
- OpenAI publicly documents rate limits, prompt reuse/routing considerations and SSE streaming. Our quota algorithm and scheduler are educational implementations, not a reconstruction of its private engine.
- Report measured failures, rejected requests and uncertainty. Do not turn a synthetic load result into a claim of production-scale capacity.

## Useful commands

```powershell
.\scripts\start-llm.ps1
.\.venv\Scripts\python.exe -m llm_lab health
.\.venv\Scripts\python.exe -m llm_lab demo --scenario surge --count 100 --rate 100
.\.venv\Scripts\python.exe -m llm_lab demo --scenario multi_tenant --count 24 --rate 12
.\.venv\Scripts\python.exe -m llm_lab demo --scenario fault --count 16 --rate 6
```

These scenarios use actual Qwen inference for admitted requests. Rejected requests do not execute the model. The public-source discussion and raw results are documented in `LLM_README.md` and `LLM_VALIDATION.md`.
