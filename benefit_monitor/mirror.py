"""Mirror only the public export into the existing repository's data branch."""
import argparse
import base64
import json
import subprocess
from pathlib import Path


def run(root, repository):
    content = (Path(root) / "delivery/public/briefing.json").read_bytes()
    json.loads(content)
    endpoint = f"repos/{repository}/contents/briefing.json"
    current = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint + "?ref=briefing-data", "--jq", ".sha"],
        check=True, capture_output=True, text=True).stdout.strip()
    payload = dict(message="Update public briefing JSON", branch="briefing-data", sha=current,
                   content=base64.b64encode(content).decode("ascii"))
    subprocess.run(["gh", "api", "--method", "PUT", endpoint, "--input", "-"],
                   input=json.dumps(payload), check=True, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    run(args.root, args.repository)
    print("Public JSON mirror updated")


if __name__ == "__main__":
    main()
