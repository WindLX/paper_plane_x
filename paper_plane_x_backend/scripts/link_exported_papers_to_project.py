import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib import error, request


def load_paper_ids(json_path: Path) -> list[str]:
    with open(json_path, "r", encoding="utf-8") as f:
        data: Any = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list of paper objects")

    paper_ids: list[str] = []
    seen: set[str] = set()

    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Item at index {idx} is not an object")

        paper_id = item.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id.strip():
            raise ValueError(f"Item at index {idx} has invalid paper_id")

        if paper_id not in seen:
            seen.add(paper_id)
            paper_ids.append(paper_id)

    return paper_ids


def post_project_paper(
    base_url: str, project_id: str, paper_id: str, timeout: int
) -> tuple[int, str]:
    url = f"{base_url.rstrip('/')}/api/v1/projects/{project_id}/papers/{paper_id}"
    req = request.Request(url=url, method="POST")

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
        return e.code, body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Link exported papers to a target project via backend API"
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Target project ID",
    )
    parser.add_argument(
        "--json",
        default="export/landscape_zd_data.json",
        help="Path to exported JSON file",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print URLs, do not send requests",
    )
    parser.add_argument(
        "--treat-conflict-as-success",
        action="store_true",
        help="Treat HTTP 409 as success (already linked)",
    )

    args = parser.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"[ERROR] JSON file not found: {json_path}")
        return 1

    try:
        paper_ids = load_paper_ids(json_path)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"[ERROR] Invalid JSON content: {e}")
        return 1

    if not paper_ids:
        print("[WARN] No paper_id found in JSON, nothing to do")
        return 0

    print(f"[INFO] project_id={args.project_id}")
    print(f"[INFO] papers_to_link={len(paper_ids)}")
    print(f"[INFO] base_url={args.base_url}")

    success = 0
    failed: list[tuple[str, int, str]] = []

    for paper_id in paper_ids:
        url = (
            f"{args.base_url.rstrip('/')}/api/v1/projects/"
            f"{args.project_id}/papers/{paper_id}"
        )

        if args.dry_run:
            print(f"[DRY-RUN] POST {url}")
            continue

        status, body = post_project_paper(
            base_url=args.base_url,
            project_id=args.project_id,
            paper_id=paper_id,
            timeout=args.timeout,
        )

        if 200 <= status < 300 or (args.treat_conflict_as_success and status == 409):
            success += 1
            print(f"[OK] paper_id={paper_id} status={status}")
        else:
            failed.append((paper_id, status, body))
            print(f"[FAIL] paper_id={paper_id} status={status}")

    if args.dry_run:
        print("[DONE] Dry-run finished")
        return 0

    print(f"[SUMMARY] success={success}, failed={len(failed)}")

    if failed:
        print("[DETAIL] Failed requests:")
        for paper_id, status, body in failed:
            body_preview = body.strip().replace("\n", " ")[:200]
            print(f"- paper_id={paper_id} status={status} body={body_preview}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
