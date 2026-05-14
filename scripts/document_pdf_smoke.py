from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.document_pdf_smoke import run_pdf_smoke


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a content-safe Engram PDF document-intake smoke check.",
    )
    parser.add_argument("source_path", help="Local PDF path to review.")
    parser.add_argument("--full", action="store_true", help="Review all pages instead of the default bounded window.")
    parser.add_argument("--max-pages", type=int, default=10, help="Page limit for bounded review mode.")
    parser.add_argument("--page-range", help="Optional page range, such as 1-25.")
    parser.add_argument("--resume-token", help="Resume token returned by a previous bounded pass.")
    parser.add_argument("--store-artifact", action="store_true", help="Prepare a daemon artifact-store transaction.")
    parser.add_argument("--accept", action="store_true", help="Accept and store the prepared artifact transaction.")
    parser.add_argument("--daemon-url", default=os.environ.get("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--no-visual-coverage-required", action="store_true")
    parser.add_argument("--no-table-coverage-required", action="store_true")
    parser.add_argument("--no-ocr-coverage-required", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

    summary = run_pdf_smoke(
        args.source_path,
        full=args.full,
        max_pages=args.max_pages,
        store_artifact=args.store_artifact,
        accept=args.accept,
        daemon_url=args.daemon_url,
        timeout=args.timeout,
        require_visual_coverage=not args.no_visual_coverage_required,
        require_table_coverage=not args.no_table_coverage_required,
        require_ocr_coverage=not args.no_ocr_coverage_required,
        page_range=args.page_range,
        resume_token=args.resume_token,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary.get("status") in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
