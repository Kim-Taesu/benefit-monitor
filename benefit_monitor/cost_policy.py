"""No paid integrations. Bound anonymous public HTTP traffic."""
from threading import Lock

class RequestBudget:
    def __init__(self, limit=60):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Request budget must be 1..100")
        self.limit, self.used, self.lock = limit, 0, Lock()
    def consume(self):
        with self.lock:
            if self.used >= self.limit:
                raise RuntimeError("Public HTTP request budget exhausted; stop until next run")
            self.used += 1

budget = RequestBudget()

def reset(limit=60):
    global budget
    budget = RequestBudget(limit)

def require_free(config):
    policy = config.get("cost_policy", {})
    if policy and (policy.get("mode") != "free_public_only" or policy.get("paid_services_allowed") is not False):
        raise ValueError("Only free public sources are supported; paid integrations forbidden")

def telemetry():
    return dict(mode="free_public_only", paid_services_used=False,
                public_http_requests=budget.used, request_limit=budget.limit,
                platform_billing="outside_project_control")
