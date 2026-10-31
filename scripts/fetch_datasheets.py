"""Download the declared manufacturer PDFs, recording hashes; optionally ingest."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true", help="Also add PDFs to the local app library")
    parser.add_argument("--reindex", action="store_true", help="Re-extract existing sample PDFs; implies --ingest")
    args = parser.parse_args()
    args.ingest = args.ingest or args.reindex
    manifest = json.loads((ROOT / "evaluation" / "datasheets.json").read_text())
    target = ROOT / "data" / "samples"
    target.mkdir(parents=True, exist_ok=True)
    records, failed = [], False
    if args.ingest:
        from spec_check.app import ingest
        from spec_check.store import initialize
        initialize()
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for item in manifest:
            path = target / item["file"]
            try:
                if path.exists():
                    content = path.read_bytes()
                else:
                    response = client.get(item["url"])
                    response.raise_for_status()
                    content = response.content
                    if not content.startswith(b"%PDF-"):
                        raise ValueError("Manufacturer returned a non-PDF response")
                    path.write_bytes(content)
                record = {**item, "sha256": hashlib.sha256(content).hexdigest()}
                if args.ingest:
                    record["ingest"] = ingest(content, item["file"], reindex=args.reindex)
                records.append(record)
                print(f"Ready: {item['file']}")
            except Exception as exc:
                failed = True
                print(f"Failed: {item['file']}: {exc}", file=sys.stderr)
    (target / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
