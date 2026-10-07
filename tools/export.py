#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export your Indus LMS data to web/data.js for offline use (no server needed).

Requires induslms-agent (`pip install induslms-agent`) and a token from
`induslms login you@school.example`.

    python3 tools/export.py                # write web/data.js
    python3 tools/export.py --files        # also download shared files to web/files/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))

try:
    import lms
except ImportError:
    sys.exit("induslms-agent is not installed. Run: pip install induslms-agent")

from openlms.data import build, clean_name, flatten, resource_tree  # noqa: E402


def session() -> tuple[str, str]:
    token = lms.load_token()
    if not token or not token.get("access"):
        sys.exit("No LMS token. Run: induslms login you@school.example")
    roles = (token.get("user") or {}).get("roles") or []
    tenant = (roles[0].get("tenant_id") if roles else None) or os.environ.get("INDUSLMS_TENANT")
    if not tenant:
        sys.exit("No tenant ID. Set INDUSLMS_TENANT or log in again.")
    return token["access"], tenant


def download(tok: str, tid: str, files: list[dict], dest: Path) -> None:
    ok = failed = 0
    for f in files:
        out = dest.joinpath(*f["dir"])
        existing = out / clean_name(f["name"])
        try:
            path = existing if existing.exists() else Path(
                lms.download_resource_file(tok, tid, f["id"], f["file_id"], out_dir=str(out))["path"])
            f["path"] = path.relative_to(WEB).as_posix()
            ok += 1
        except Exception as e:  # 403 = restricted by the teacher or another class
            failed += 1
            print(f"  skipped {f['title']}: {str(e)[:60]}", file=sys.stderr)
    print(f"files: {ok} downloaded, {failed} unavailable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", action="store_true", help="download shared files to web/files/")
    ap.add_argument("--out", default=str(WEB / "data.js"), help="output path (default: web/data.js)")
    args = ap.parse_args()

    tok, tid = session()
    files = flatten(resource_tree(tok, tid))
    if args.files:
        download(tok, tid, files, WEB / "files")
    data = build(tok, tid, files)
    Path(args.out).write_text("window.LMS = " + json.dumps(data, default=str) + ";\n")
    print(f"wrote {args.out}: {len(data['courses'])} classes, "
          f"{len(data['eol']) + len(data['assessments'])} assignments, {len(files)} files")


if __name__ == "__main__":
    main()
