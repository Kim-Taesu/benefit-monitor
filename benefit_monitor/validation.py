from datetime import date, datetime
from decimal import Decimal
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from .models import Benefit

def official(url, domains):
    u = urlsplit(url)
    return u.scheme == "https" and u.hostname in domains and not u.username and not u.password and u.port in (None, 443)

LABEL_CATEGORIES = ("문화·체험", "할인·적립", "생활지원", "교육·강좌", "공모·참여")
LABEL_ACTIONS = ("신청·예약 필요", "미션 참여", "응모", "바로 이용", "결제 시 적용", "구매 후 사용")



VALUE_LABELS = {"discount_rate": "% 할인", "discount_amount": "원 할인", "grant_amount": "원 지원",
                "refund_amount": "원 환급", "reward_points": "포인트 적립"}


def validate_benefit_value(item, domains):
    claim = item.benefit_value
    if not isinstance(claim, dict):
        raise ValueError("benefit_value must be an object")
    if not claim:
        return
    required = {"kind", "value", "qualifier", "conditions", "evidence_url", "evidence_quote"}
    if set(claim) != required or not isinstance(claim.get("kind"), str) or claim.get("kind") not in VALUE_LABELS or claim.get("qualifier") not in ("exact", "up_to"):
        raise ValueError("Unknown or incomplete benefit_value")
    amount = claim["value"]
    rate = claim["kind"] == "discount_rate"
    if type(amount) not in (int, float) or not 0 < amount <= (100 if rate else 999_999_999_999):
        raise ValueError("A positive finite benefit value is required")
    if rate and Decimal(str(amount)).as_tuple().exponent < -2 or not rate and type(amount) is not int:
        raise ValueError("Rates allow two decimal places; KRW and points require integers")
    for key, limit in (("conditions", 1000), ("evidence_quote", 500), ("evidence_url", 4096)):
        if not isinstance(claim[key], str) or not claim[key].strip() or len(claim[key]) > limit:
            raise ValueError("Benefit value requires bounded conditions and official evidence")
    target = item.payment_terms.get("evidence_url", item.url)
    if not official(claim["evidence_url"], domains) or claim["evidence_url"] != target:
        raise ValueError("Value evidence must use the already observed official body URL")
    if not item.verified_at or not isinstance(item.evidence, str) or claim["evidence_quote"] not in item.evidence:
        raise ValueError("Value quote must be part of the human verification evidence")
    # Check the supplied figure against a literal quote; never extract or calculate a new value.
    numbers = {format(amount, f",.{digits}f") for digits in range(3)
               if Decimal(format(amount, f".{digits}f")) == Decimal(str(amount))}
    numbers |= {n.replace(",", "") for n in numbers}
    unit = "%" if rate else "포인트" if claim["kind"] == "reward_points" else "원"
    literal = "(?:" + "|".join(re.escape(n + unit) for n in numbers) + ")"
    quote = re.sub(r"\s", "", claim["evidence_quote"])
    if VALUE_LABELS[claim["kind"]].split()[-1] not in quote or not re.search(r"(?<![0-9.,])" + literal + r"(?![0-9.])", quote) or ("최대" in quote) != (claim["qualifier"] == "up_to"):
        raise ValueError("Supplied number, unit and maximum qualifier must match the literal quote")


def benefit_value_label(claim):
    if not claim:
        return ""
    amount = f"{claim['value']:,.2f}".rstrip("0").rstrip(".")
    return ("최대 " if claim["qualifier"] == "up_to" else "") + amount + VALUE_LABELS[claim["kind"]]


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
    validate_benefit_value(item, sources[item.source]["domains"])
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

