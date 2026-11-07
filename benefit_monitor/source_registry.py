"""Per-source definitions: sources/<id>.json holds collection settings and a runbook.

The operational sources.yaml is generated from these files (scripts/generate_sources.py),
so existing readers stay unchanged. Validation uses a small JSON Schema subset with the
standard library only: type, const, enum, pattern, minLength, minItems, minimum, maximum,
required, properties, additionalProperties=false, items and local $ref.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None), "integer": int}


def _check(value, schema, defs, path, errors):
    if "$ref" in schema:
        _check(value, defs[schema["$ref"].rsplit("/", 1)[-1]], defs, path, errors)
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "type" in schema:
        kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(isinstance(value, TYPES[k]) and not (k != "boolean" and isinstance(value, bool)) for k in kinds):
            errors.append(f"{path}: expected {'/'.join(kinds)}")
            return
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            errors.append(f"{path}: {value} out of range")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: empty text")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for index, item in enumerate(value):
            if "items" in schema:
                _check(item, schema["items"], defs, f"{path}[{index}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _check(item, properties[key], defs, f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key {key}")


def validate(definition, schema, filename=None):
    errors = []
    _check(definition, schema, schema.get("$defs", {}), definition.get("id", "?") if isinstance(definition, dict) else "?", errors)
    if errors:
        return errors
    status = definition["status"]
    if status == "active" and "collect" not in definition:
        errors.append(f"{definition['id']}: active source needs collect")
    if status != "active" and ("collect" in definition or "monitoring" in definition or "reason" not in definition):
        errors.append(f"{definition['id']}: {status} source needs reason and no collect or monitoring")
    monitoring = definition.get("monitoring")
    if status == "active" and monitoring is None:
        errors.append(f"{definition['id']}: active source needs monitoring")
    if monitoring and monitoring["expect"] != "working" and not {"since", "reason"} <= set(monitoring):
        errors.append(f"{definition['id']}: {monitoring['expect']} needs since and reason")
    if filename and filename != definition["id"] + ".json":
        errors.append(f"{definition['id']}: file name must be {definition['id']}.json")
    return errors


def load(root=ROOT):
    """Return (settings, definitions in configured order); raise ValueError listing every problem."""
    root = Path(root)
    folder = root / "sources"
    schema = json.loads((root / "schema/source.schema.json").read_text(encoding="utf-8"))
    settings = json.loads((folder / "_config.json").read_text(encoding="utf-8"))
    definitions, errors = {}, []
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        definition = json.loads(path.read_text(encoding="utf-8"))
        problems = validate(definition, schema, path.name)
        errors += problems
        if not problems:
            for code in definition["runbook"]["code"]:
                if not (root / code).exists():
                    errors.append(f"{definition['id']}: runbook code path missing: {code}")
            definitions[definition["id"]] = definition
    order = settings.get("source_order", [])
    active = [key for key, d in definitions.items() if d["status"] == "active"]
    if len(set(order)) != len(order) or sorted(order) != sorted(active):
        errors.append(f"_config.json source_order must list each active source once: missing {sorted(set(active) - set(order))}, extra {sorted(set(order) - set(active))}")
    if errors:
        raise ValueError("\n".join(errors))
    return settings, [definitions[key] for key in order] + [d for key, d in definitions.items() if key not in order]


def build_config(root=ROOT):
    """The operational sources.yaml content, identical in shape to the hand-written file it replaced."""
    settings, definitions = load(root)
    config = {key: value for key, value in settings.items() if key != "source_order"}
    rows = [{"id": d["id"], "name": d["name"], **d["collect"]} for d in definitions if d["status"] == "active"]
    ordered = {}
    for key, value in config.items():
        ordered[key] = value
        if key == "max_age_days":
            ordered["sources"] = rows
    return ordered


def render(root=ROOT):
    return json.dumps(build_config(root), ensure_ascii=False, indent=2) + "\n"


def probe(root, source_id, budget=10):
    """Run one source's collector live under robots and a small HTTP budget, for maintenance."""
    from . import cost_policy
    from .collectors.html import collect as collect_html
    from .collectors.public import collect as collect_public
    from .collectors.rss import collect as collect_rss
    from datetime import datetime
    from zoneinfo import ZoneInfo
    config = build_config(root)
    source = next((s for s in config["sources"] if s["id"] == source_id), None)
    if source is None:
        raise ValueError(f"unknown or inactive source: {source_id}")
    cost_policy.reset(budget)
    if source.get("collector") == "kfes_festivals":
        from .festivals import collect as collect_festivals
        bundle = collect_festivals(source, datetime.now(ZoneInfo(config["timezone"])))
        items = [dict(title=f"{i['name']} ({i['start']}~{i['end']}, {i['region']})", url=i["url"]) for i in bundle["items"]]
    elif source.get("collector"):
        items = collect_public(source, datetime.now(ZoneInfo(config["timezone"])))
    elif source.get("feed_url"):
        items = collect_rss(source)
    elif source.get("html_url"):
        items = collect_html(source)
    else:
        raise ValueError("no automatic collector; see the runbook manual_check")
    return dict(source=source_id, http_requests=cost_policy.budget.used, items=[dict(title=i["title"], url=i["url"]) for i in items])


def main(argv=None):
    parser = argparse.ArgumentParser(description="출처 정의 확인·실측")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="모든 출처 정의를 스키마로 검사")
    shown = sub.add_parser("show", help="출처 하나의 runbook 출력")
    shown.add_argument("source_id")
    probed = sub.add_parser("probe", help="출처 하나를 실제로 수집해 후보 제목 출력(공식 HTTP 사용)")
    probed.add_argument("source_id")
    probed.add_argument("--budget", type=int, default=10)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            _, definitions = load(args.root)
            counts = {}
            for d in definitions:
                counts[d["status"]] = counts.get(d["status"], 0) + 1
            print(json.dumps(dict(status="ok", sources=counts), ensure_ascii=False))
        elif args.command == "show":
            _, definitions = load(args.root)
            match = next((d for d in definitions if d["id"] == args.source_id), None)
            if match is None:
                raise ValueError(f"unknown source: {args.source_id}")
            print(json.dumps(match, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(probe(args.root, args.source_id, args.budget), ensure_ascii=False, indent=2))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
