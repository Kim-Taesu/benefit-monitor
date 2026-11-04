"""Robots path matching: most specific agent, longest rule, Allow wins ties."""
import re
from urllib.parse import urlsplit, quote

UNRESERVED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")

def normalize(value):
    value = quote(value, safe="/?:@!$&'()+,;=-._~%*")
    def replace(match):
        char = chr(int(match.group(1), 16))
        return char if char in UNRESERVED else "%" + match.group(1).upper()
    return re.sub(r"%([0-9a-fA-F]{2})", replace, value)

def allowed(text, url, agent="BenefitMonitor/0.1"):
    if "<html" in text.lower() or "<!doctype" in text.lower():
        raise ValueError("HTML returned instead of robots policy")
    groups, agents, rules = [], [], []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((key == "allow", value))
    if agents:
        groups.append((agents, rules))
    agent = agent.lower().split("/", 1)[0]
    selected, specificity = [], -1
    for names, entries in groups:
        matches = [0 if name == "*" else len(name)
                   for name in names if name == "*" or (name and name in agent)]
        if not matches:
            continue
        score = max(matches)
        if score > specificity:
            specificity, selected = score, list(entries)
        elif score == specificity:
            selected.extend(entries)
    parsed = urlsplit(url)
    path = normalize((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
    matches = []
    for allow, value in selected:
        end = value.endswith("$")
        rule = normalize(value[:-1] if end else value)
        regex = "^" + re.escape(rule).replace(r"\*", ".*") + ("$" if end else "")
        if re.search(regex, path):
            matches.append((len(rule.replace("*", "").encode("utf-8")), allow))
    return max(matches)[1] if matches else True
