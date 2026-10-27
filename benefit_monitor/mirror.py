"""Mirror only the public export into the existing repository's data branch."""
import argparse
import base64
import json
import subprocess
from pathlib import Path


def run(root, repository):
    content = (Path(root) / "delivery/public/briefing.json").read_bytes()
    data=json.loads(content)
    if data.get("status")=="collection_failed":
        from .store import load, save
        restore(root,repository)
        data["operational_state"]=load(Path(root)/"cache/operational_state.json",{})
        data["source_health"]=data["operational_state"].get("sources",{})
        save(Path(root)/"delivery/public/briefing.json",data)
        content=(Path(root)/"delivery/public/briefing.json").read_bytes()
    endpoint = f"repos/{repository}/contents/briefing.json"
    current = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint + "?ref=briefing-data", "--jq", ".sha"],
        check=True, capture_output=True, text=True).stdout.strip()
    payload = dict(message="Update public briefing JSON", branch="briefing-data", sha=current,
                   content=base64.b64encode(content).decode("ascii"))
    subprocess.run(["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
                   input=json.dumps(payload), check=True, capture_output=True, text=True)


def restore(root, repository, now=None):
    from datetime import datetime
    from .briefing import SEOUL
    from .store import load, save
    from .operations import sanitize
    root=Path(root)
    result=subprocess.run(["gh", "api", "--method", "GET",
        f"repos/{repository}/contents/briefing.json?ref=briefing-data"],
        check=True,capture_output=True,text=True)
    envelope=json.loads(result.stdout)
    if envelope.get("encoding")!="base64":raise ValueError("Unexpected mirror encoding")
    remote=json.loads(base64.b64decode(envelope["content"]))
    config=load(root/"sources.yaml",None)
    state=sanitize(remote.get("operational_state",{}),{x["id"] for x in config["sources"]},now or datetime.now(SEOUL))
    save(root/"cache/operational_state.json",state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.restore:
        restore(args.root, args.repository)
        print("Operational metadata restored")
        return
    run(args.root, args.repository)
    print("Public JSON mirror updated")


if __name__ == "__main__":
    main()
