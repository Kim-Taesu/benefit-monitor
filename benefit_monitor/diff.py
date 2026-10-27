from datetime import date, datetime

def classify(old, current, now, days=7, max_age=7):
    result = {k: [] for k in ("new", "changed", "expiring", "still_valid", "needs_recheck", "expired", "upcoming", "excluded")}
    for key, item in sorted(current.items()):
        end = date.fromisoformat(item.valid_until) if item.valid_until else None
        start = date.fromisoformat(item.valid_from) if item.valid_from else None
        verified = datetime.fromisoformat(item.verified_at) if item.verified_at else None
        deadline = datetime.fromisoformat(item.deadline_at) if item.deadline_at else None
        if item.excluded_reason:
            bucket = "excluded"
        elif (deadline and now >= deadline) or (end and end < now.date()):
            bucket = "expired"
        elif item.needs_recheck or (not end and item.validity_kind != "ongoing") or not verified or (now-verified).total_seconds() > max_age*86400:
            bucket = "needs_recheck"
        elif start and start > now.date():
            bucket = "upcoming"
        elif key not in old:
            bucket = "new"
        elif old[key].content() != item.content():
            bucket = "changed"
        else:
            bucket = "still_valid"
        result[bucket].append(item.data())
        if end and 0 <= (end-now.date()).days <= days and bucket not in ("needs_recheck", "upcoming", "excluded", "expired"):
            result["expiring"].append(item.data())
    return result
