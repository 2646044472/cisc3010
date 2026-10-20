"""Teaching admission controller; client identities are local demo labels, not auth."""
import collections
from .common import now, TERMINAL


class AdmissionError(RuntimeError):
    def __init__(self, reason, tenant, retry_after=1):
        super().__init__(reason)
        self.code = reason
        self.tenant = tenant
        self.retry_after = max(1, int(retry_after + .999))


class Admission:
    PLANS = {
        "demo": {"rate": 6, "burst": 12, "inflight": 8, "token_budget": 4096},
        "client-a": {"rate": 2, "burst": 6, "inflight": 4, "token_budget": 2048},
        "client-b": {"rate": 2, "burst": 6, "inflight": 4, "token_budget": 2048},
        "benchmark": {"rate": 200, "burst": 200, "inflight": 128, "token_budget": 100000},
    }

    def __init__(self):
        self.buckets = {}
        self.counts = collections.Counter()

    def reset(self):
        self.buckets.clear()
        self.counts.clear()

    def admit(self, tenant, reservation, records, clock=None):
        # Caller holds the gateway lock across quota check and assignment.
        clock = now() if clock is None else clock
        plan = self.PLANS[tenant]
        tokens, previous = self.buckets.get(tenant, (plan["burst"], clock))
        tokens = min(plan["burst"], tokens + max(0, clock - previous) * plan["rate"])
        self.buckets[tenant] = (tokens, clock)
        live = [r for r in records if r.get("tenant") == tenant and r["status"] not in TERMINAL]
        reason = None
        retry = 1
        if tokens < 1:
            reason = "request_rate_limit"
            retry = (1 - tokens) / plan["rate"]
        elif len(live) >= plan["inflight"]:
            reason = "client_concurrency_limit"
        elif sum(r.get("reservation", 0) for r in live) + reservation > plan["token_budget"]:
            reason = "client_token_budget"
        if reason:
            self.counts[reason] += 1
            raise AdmissionError(reason, tenant, retry)
        self.buckets[tenant] = (tokens - 1, clock)
        self.counts["admitted"] += 1

    def snapshot(self, records):
        rows = []
        for tenant, plan in self.PLANS.items():
            if tenant == "benchmark" and tenant not in self.buckets:
                continue
            live = [r for r in records if r.get("tenant") == tenant and r["status"] not in TERMINAL]
            rows.append({"client": tenant, **plan, "active": len(live),
                         "reserved_tokens": sum(r.get("reservation", 0) for r in live)})
        return {"clients": rows, "counts": dict(self.counts)}
