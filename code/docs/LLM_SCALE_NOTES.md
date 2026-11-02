# Explaining scale in the presentation

“Millions of users” is not the same as “millions of concurrent generations.” Registered users, daily active users, request arrival rate, simultaneously open streams, and generated tokens/second describe different loads.

Use this **hypothetical** example to explain the distinction, not as a statement about OpenAI traffic:

```text
10 million daily active users × 10 requests/day = 100 million requests/day
Average arrival rate = 100,000,000 / 86,400 ≈ 1,157 requests/second
Assumed peak = 5 × average ≈ 5,787 requests/second
Assumed mean time in service = 10 seconds
Stable-system mean in-service concurrency ≈ 5,787 × 10 ≈ 57,870 requests
```

Little's law requires a stable system and consistent measurement boundaries. During overload, queues can grow or requests can be rejected; the simple calculation is not a latency guarantee. Input/output length distributions, token throughput, batching, cache reuse and memory limits also matter. Capacity planning must use measurements for the actual model, hardware and service objective.

At greater scale, the corresponding design concerns include multiple admission gateways, many model-replica groups, load and cache locality, bounded queues, scheduling within each group, and monitoring/failure handling. A model-replica group may itself use model parallelism if one accelerator cannot hold the model. These are general systems design considerations; the fetched public OpenAI documents do not establish its complete internal deployment topology.

TokenFlow demonstrates a limited version of those concerns:

| Concern | Demonstrated locally | Larger-system consideration |
| --- | --- | --- |
| Entry pressure | Client rate/concurrency/token budgets; HTTP 429 and Retry-After. | Shared quota coordination and separate regional/project limits. |
| Request distribution | Load-aware routing between two independent full-model replicas. | Many replica groups, health feedback, cache-aware placement. |
| Worker execution | Real CPU selective batching, request-local Attention/KV state, bounded real prefill; separate controlled simulator. | Accelerator-specific kernels, paged cache allocation and model parallelism. |
| Streaming | Incremental SSE, cancellation and explicit failure. | Connection capacity, backpressure, end-to-end deadlines. |
| Availability | One worker stops; new requests use the survivor. | Redundant gateways, regions, orchestration and capacity reserves. |

Do not multiply this laptop's measured request rate into a claimed OpenAI server count. The production model/hardware, workload and policies are different. The project verifies mechanisms and records small-scale measurements; it does not validate million-user capacity.

Public references: [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits), [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), [OpenAI SSE streaming](https://developers.openai.com/api/docs/guides/streaming-responses), [Orca](https://www.usenix.org/conference/osdi22/presentation/yu), and [vLLM optimization](https://docs.vllm.ai/en/stable/configuration/optimization/).
