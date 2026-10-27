from dataclasses import dataclass, asdict, field
from hashlib import sha256

@dataclass(frozen=True)
class Benefit:
    source: str
    url: str
    title: str
    summary: str
    valid_until: str | None = None
    verified_at: str | None = None
    needs_recheck: bool = True
    valid_from: str | None = None
    published_at: str | None = None
    conditions: str = ""
    evidence: str = ""
    districts: list[str] = field(default_factory=list)
    review_notes: str = ""
    fee_status: str = "unknown"
    validity_kind: str = "fixed"
    deadline_at: str | None = None
    excluded_reason: str = ""

    @property
    def id(self):
        return sha256((self.source + "\n" + self.url).encode()).hexdigest()[:24]

    def data(self):
        return asdict(self)

    def content(self):
        return {k: v for k, v in self.data().items() if k not in ("verified_at", "needs_recheck")}
