from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from .models import Benefit

def official(url, domains):
    u = urlsplit(url)
    return u.scheme == "https" and u.hostname in domains and not u.username and not u.password and u.port in (None, 443)

LABEL_CATEGORIES = ("문화·체험", "할인·적립", "생활지원", "교육·강좌", "공모·참여")
LABEL_ACTIONS = ("신청·예약 필요", "미션 참여", "응모", "바로 이용", "결제 시 적용", "구매 후 사용")


def validate(data, sources, now):
    item = Benefit(**data)
    if item.source not in sources or not official(item.url, sources[item.source]["domains"]):
        raise ValueError("Official HTTPS source required")
    if not isinstance(item.payment_terms, dict):
        raise ValueError("payment_terms must be an object")
    if item.payment_terms:
        required={"method","funding_source","excluded_methods","minimum_spend","limit","evidence_url"}
        if set(item.payment_terms)!=required or any(not isinstance(v,str) or not v.strip() for v in item.payment_terms.values()):
            raise ValueError("Payment review requires method, funding, exclusions, minimum spend, limit and evidence; mark unknown explicitly")
        if not official(item.payment_terms["evidence_url"],sources[item.source]["domains"]):
            raise ValueError("Official payment evidence required")
    if not isinstance(item.labels, dict) or not set(item.labels) <= {"category", "audience", "region", "action"}:
        raise ValueError("labels allow only category, audience, region and action")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 40 for v in item.labels.values()):
        raise ValueError("labels must be short non-empty text taken from the official notice")
    if item.labels.get("category", LABEL_CATEGORIES[0]) not in LABEL_CATEGORIES or item.labels.get("action", LABEL_ACTIONS[0]) not in LABEL_ACTIONS:
        raise ValueError("Unknown label category or action")
    if not item.title.strip() or not item.summary.strip():
        raise ValueError("Title and summary required")
    if not isinstance(item.districts, list) or any(not isinstance(d, str) for d in item.districts):
        raise ValueError("districts must be a list of names")
    if item.fee_status not in ("free", "paid", "mixed", "unknown"):
        raise ValueError("Invalid fee status")
    if item.validity_kind not in ("fixed", "ongoing"):
        raise ValueError("Invalid validity kind")
    if item.validity_kind == "ongoing" and (item.valid_until or item.deadline_at):
        raise ValueError("Ongoing services cannot have a fixed ending or deadline")
    if item.deadline_at:
        deadline = datetime.fromisoformat(item.deadline_at)
        if deadline.tzinfo is None:
            raise ValueError("Deadline requires timezone")
        if item.valid_until != deadline.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat():
            raise ValueError("Deadline date must match valid_until in Seoul")
    if item.excluded_reason and not (item.verified_at and item.evidence.strip()):
        raise ValueError("Exclusion requires a verified reason and evidence")
    if type(item.needs_recheck) is not bool:
        raise ValueError("needs_recheck must be boolean")
    for field in ("valid_from", "valid_until", "published_at"):
        if getattr(item, field) is not None:
            date.fromisoformat(getattr(item, field))
    if item.valid_from and item.valid_until and item.valid_from > item.valid_until:
        raise ValueError("Invalid date interval")
    if item.verified_at:
        t = datetime.fromisoformat(item.verified_at)
        if t.tzinfo is None or t > now:
            raise ValueError("Verification time must have timezone and not be future")
    if not item.needs_recheck and not (item.verified_at and item.evidence.strip()):
        raise ValueError("Verified item requires timestamp and evidence")
    return item

