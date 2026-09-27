"""Load a local document folder through DecisionGraph's governed S3 upload API.

Only successful uploads are remembered. In --watch mode, new and modified files
are discovered on the next scan without granting AWS keys to this script.
"""

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"}
MAX_BYTES = 20 * 1024 * 1024
DEFAULT_STATE = ".decisiongraph-cloud-loader.json"


def request(url, *, method="GET", body=None, headers=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        # In particular, never echo presigned URLs or AWS response bodies.
        raise RuntimeError(f"{method} failed (HTTP {exc.code})") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} failed (network error: {exc.reason})") from exc


def save_state(path, state):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def load_state(path):
    if not path.exists():
        return {}
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("Loader state must be a JSON object")
    return content


def upload(path, args, key):
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    base = args.url.rstrip("/")
    auth = {"X-API-Key": args.api_key} if args.api_key else {}
    headers = {"Content-Type": "application/json", **auth}
    prepared = json.loads(request(
        f"{base}/v1/cloud/uploads", method="POST",
        body={"tenant_id": args.tenant, "owner_id": args.user,
              "access_scope": args.scope, "filename": path.name,
              "content_type": content_type, "size_bytes": len(content),
              "checksum_sha256": checksum}, headers=headers,
    ))
    # urllib's Request sends data bytes directly; do not JSON-encode the file.
    put = Request(prepared["upload_url"], data=content,
                  headers=prepared["headers"], method="PUT")
    try:
        with urlopen(put, timeout=180) as response:
            response.read()
    except HTTPError as exc:
        # Only surface S3's short error code, never its response body (which
        # can include a presigned URL or other sensitive request details).
        s3_code = ""
        try:
            root = ET.fromstring(exc.read(8192))
            value = root.findtext("Code")
            if value and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,49}", value):
                s3_code = f", S3 code: {value}"
        except (ET.ParseError, UnicodeError, ValueError):
            pass
        raise RuntimeError(f"S3 upload failed (HTTP {exc.code}{s3_code})") from exc
    except URLError as exc:
        raise RuntimeError(f"S3 upload failed (network error: {exc.reason})") from exc
    result = json.loads(request(
        f"{base}/v1/cloud/uploads/{prepared['upload_id']}/complete", method="POST",
        body={"tenant_id": args.tenant, "owner_id": args.user,
              "enrich_graph": args.enrich_graph}, headers=headers,
    ))
    if result.get("status") != "indexed":
        raise RuntimeError("API did not confirm indexing")
    return {"sha256": checksum, "document_id": result["document_id"],
            "indexed_at": int(time.time()), "path": key}


def scan(args, state):
    files = sorted(p for p in args.folder.rglob("*")
                   if p.is_file() and not p.is_symlink()
                   and p.suffix.lower() in EXTENSIONS)
    counts = {"indexed": 0, "unchanged": 0, "failed": 0}
    names = {}
    for path in files:
        names.setdefault(path.name, []).append(path)
    for path in files:
        relative = path.relative_to(args.folder).as_posix()
        key = f"{args.url.rstrip('/')}|{args.tenant}|{args.user}|{args.scope}|{relative}"
        if len(names[path.name]) > 1:
            print(f"{relative}: skipped: duplicate filename across folders", flush=True)
            counts["failed"] += 1
            continue
        try:
            size = path.stat().st_size
            if not 0 < size <= MAX_BYTES:
                raise ValueError("file must be between 1 byte and 20 MB")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if state.get(key, {}).get("sha256") == checksum:
                counts["unchanged"] += 1
                continue
            result = upload(path, args, key)
            state[key] = result
            save_state(args.state, state)
            counts["indexed"] += 1
            print(f"{relative}: indexed (document {result['document_id']})", flush=True)
        except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            counts["failed"] += 1
            print(f"{relative}: failed: {exc}", file=sys.stderr, flush=True)
    print(" ".join(f"{name}={count}" for name, count in counts.items()), flush=True)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Local folder containing documents")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--user", default="sujal")
    parser.add_argument("--scope", choices=("team", "company", "private"), default="team")
    parser.add_argument("--enrich-graph", action="store_true", help="Uses extra model calls")
    parser.add_argument("--watch", action="store_true", help="Keep loading new or changed files")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--state", type=Path, help="JSON record of successfully indexed files")
    parser.add_argument("--api-key", default=os.environ.get("DECISIONGRAPH_API_KEY", ""))
    args = parser.parse_args()
    args.folder = args.folder.expanduser().resolve()
    if not args.folder.is_dir():
        parser.error("folder must exist and be a directory")
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")
    args.state = args.state or (args.folder / DEFAULT_STATE)
    state = load_state(args.state)
    while True:
        counts = scan(args, state)
        if not args.watch:
            return 1 if counts["failed"] else 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Stopped watching.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
