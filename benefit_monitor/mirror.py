"""Mirror only the public export into the existing repository's data branch."""
import argparse
import base64
import json
import subprocess
from pathlib import Path


def lease(repository, env=None):
    """Current sha of the public briefing.json on briefing-data."""
    return subprocess.run(
        ["gh", "api", "--method", "GET", f"repos/{repository}/contents/briefing.json?ref=briefing-data", "--jq", ".sha"],
        check=True, capture_output=True, text=True, env=env).stdout.strip()


def run(root, repository, env=None, content=None, expected_sha=None):
    content = content if content is not None else (Path(root) / "delivery/public/briefing.json").read_bytes()
    data=json.loads(content)
    if data.get("status")=="collection_failed":
        from .store import load, save
        restore(root,repository,env=env)
        data["operational_state"]=load(Path(root)/"cache/operational_state.json",{})
        data["source_health"]=data["operational_state"].get("sources",{})
        save(Path(root)/"delivery/public/briefing.json",data)
        content=(Path(root)/"delivery/public/briefing.json").read_bytes()
    endpoint = f"repos/{repository}/contents/briefing.json"
    current = lease(repository, env)
    if expected_sha is not None and current!=expected_sha:
        raise ValueError('public snapshot changed during AI run; preserve the newer export')
    payload = dict(message="Update public briefing JSON", branch="briefing-data", sha=current,
                   content=base64.b64encode(content).decode("ascii"))
    result=subprocess.run(["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
                   input=json.dumps(payload), check=True, capture_output=True, text=True, env=env)
    return json.loads(result.stdout).get("commit",{}).get("sha")


def restore(root, repository, now=None, env=None):
    from datetime import datetime
    from .briefing import SEOUL
    from .store import load, save
    from .operations import sanitize
    root=Path(root)
    result=subprocess.run(["gh", "api", "--method", "GET",
        f"repos/{repository}/contents/briefing.json?ref=briefing-data"],
        check=True,capture_output=True,text=True,env=env)
    envelope=json.loads(result.stdout)
    if envelope.get("encoding")!="base64":raise ValueError("Unexpected mirror encoding")
    remote=json.loads(base64.b64decode(envelope["content"]))
    config=load(root/"sources.yaml",None)
    now=now or datetime.now(SEOUL)
    ids={x['id'] for x in config['sources']}
    state=sanitize(remote.get("operational_state",{}),ids,now)
    local=sanitize(load(root/'cache/operational_state.json',{}),ids,now)
    # A mirror restore must not undo a body/title change observed locally.
    for key,row in local['items'].items():
        old=state['items'].get(key,{})
        if row.get('hold_at') and (not old.get('hold_at') or datetime.fromisoformat(row['hold_at'])>datetime.fromisoformat(old['hold_at'])):
            state['items'][key]=row
    save(root/"cache/operational_state.json",state)
    return envelope.get("sha")


AI_FILES = {"ai-approved.json": "cache/ai_publish/approved.json", "ai-takedowns.json": "cache/ai_publish/takedowns.json",
            "ai-status.json": "cache/ai_daily/status.json"}
# Remote copy and sha lease of ai-approved.json from the last restore; required before any save.
AI_BASE = "cache/ai_publish/remote.json"


def _get(repository, name, env=None):
    """(value, sha) of a briefing-data file; (None, None) when it does not exist yet."""
    result = subprocess.run(["gh", "api", "--method", "GET", f"repos/{repository}/contents/{name}?ref=briefing-data"],
                            capture_output=True, text=True, env=env)
    if result.returncode != 0:
        if "HTTP 404" in result.stderr:
            return None, None
        raise RuntimeError("briefing-data read failed: " + name)
    envelope = json.loads(result.stdout)
    if envelope.get("encoding") != "base64":
        raise ValueError("Unexpected mirror encoding")
    return json.loads(base64.b64decode(envelope["content"])), envelope.get("sha")


def _put(repository, name, value, sha, env=None):
    """True on success, False on a stale sha (write conflict)."""
    body = dict(message="Update " + name, branch="briefing-data",
                content=base64.b64encode((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()).decode("ascii"))
    if sha:
        body["sha"] = sha
    result = subprocess.run(["gh", "api", "--method", "PUT", f"repos/{repository}/contents/{name}", "--input", "-"],
                            input=json.dumps(body), capture_output=True, text=True, env=env)
    if result.returncode == 0:
        return True
    if "HTTP 409" in result.stderr or "does not match" in result.stderr:
        return False
    raise RuntimeError("briefing-data write failed: " + name)


def restore_ai(root, repository, env=None):
    """Fetch the AI approval list, takedowns and run status. Any failure hides every auto record."""
    from .auto_release import public_record
    from .store import save
    root = Path(root)
    base = root / AI_BASE
    try:
        approved, sha = _get(repository, "ai-approved.json", env)
        takedowns, _ = _get(repository, "ai-takedowns.json", env)
        status, _ = _get(repository, "ai-status.json", env)
        approved = {} if approved is None else approved
        takedowns = [] if takedowns is None else takedowns
        if not isinstance(approved, dict) or not isinstance(takedowns, list):
            raise ValueError("Invalid AI approval files")
    except Exception:
        save(root / AI_FILES["ai-approved.json"], {})
        save(root / AI_FILES["ai-takedowns.json"], [])
        base.unlink(missing_ok=True)
        return False
    approved = {cid: public_record(r) for cid, r in approved.items() if isinstance(r, dict)}
    save(root / AI_FILES["ai-approved.json"], approved)
    save(root / AI_FILES["ai-takedowns.json"], [t for t in takedowns if isinstance(t, dict)])
    if status is not None:
        save(root / AI_FILES["ai-status.json"], status)
    save(base, {"sha": sha, "approved": approved})
    return True


def save_ai(root, repository, env=None):
    """Write the local approval list back with the restored sha lease; on conflict re-read once and merge."""
    from .auto_release import merge_approved, public_record
    from .store import load, save
    root = Path(root)
    lease = load(root / AI_BASE, None)
    if not isinstance(lease, dict) or not isinstance(lease.get("approved"), dict):
        raise ValueError("AI approval restore required before saving")
    # Read the file itself, never the fail-closed reader: an unreadable list must not upload {}.
    approved = load(root / AI_FILES["ai-approved.json"], None)
    if not isinstance(approved, dict):
        raise ValueError("Local AI approval list missing or not an object")
    ours = {cid: public_record(r) for cid, r in approved.items() if isinstance(r, dict)}
    if _put(repository, "ai-approved.json", ours, lease.get("sha"), env):
        return ours
    theirs, sha = _get(repository, "ai-approved.json", env)
    if not isinstance(theirs, dict):
        raise RuntimeError("AI approval list changed into an unreadable file")
    merged = merge_approved(lease["approved"], ours, {k: public_record(v) for k, v in theirs.items() if isinstance(v, dict)})
    if not _put(repository, "ai-approved.json", merged, sha, env):
        raise RuntimeError("AI approval list changed twice during save")
    save(root / AI_FILES["ai-approved.json"], merged)
    return merged


def apply_takedowns_remote(root, repository, env=None):
    """Takedown-only deploy: filter the current public briefing; no collection and no snapshot gate."""
    from .auto_release import apply_takedowns
    from .publish import write_export
    data, sha = _get(repository, "briefing.json", env)
    takedowns, _ = _get(repository, "ai-takedowns.json", env)
    if not isinstance(data, dict) or not isinstance(takedowns, list):
        raise ValueError("Current briefing and a valid takedown list are required")
    clean = apply_takedowns(data, [t for t in takedowns if isinstance(t, dict)])
    write_export(root, clean)
    if clean != data:
        run(root, repository, env=env, expected_sha=sha)
    return clean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--save-ai", action="store_true")
    mode.add_argument("--apply-takedowns", action="store_true")
    args = parser.parse_args()
    if args.restore:
        restore(args.root, args.repository)
        restored = restore_ai(args.root, args.repository)
        print("Operational metadata restored; AI approvals", "restored" if restored else "unavailable (auto items hidden)")
        return
    if args.save_ai:
        save_ai(args.root, args.repository)
        print("AI approval list saved")
        return
    if args.apply_takedowns:
        data = apply_takedowns_remote(args.root, args.repository)
        print("Takedowns applied; public items", len(data["items"]))
        return
    run(args.root, args.repository)
    print("Public JSON mirror updated")


if __name__ == "__main__":
    main()
