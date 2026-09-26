#!/usr/bin/env python3
"""export_v1_handoffs.py - one-time queue-day export of v1 handoffs into Nexus2 queues/handoffs/.

Handoff 2026-09-26-clarice-to-cody-nexus2-migration-tooling, item 2.

Every non-closed v1 row (status open or accepted) becomes one Nexus2 handoff file:
  - frontmatter: the six fields plus to / from / date / topic / v1 (what nexus.py index reads);
  - body: the v1 file's body, with v1 paths rewritten as `v1:<path>` pointers.

Usage:
    python bin/export_v1_handoffs.py --manifest <rows.json> --v1-root <v1 Nexus folder>            # dry run
    python bin/export_v1_handoffs.py --manifest <rows.json> --v1-root <v1 Nexus folder> --write    # write files

Root: --nexus-root, else NEXUS_ROOT, else the parent of bin/ (same rule as nexus.py).
The manifest is the JSON output of the query in nexus-tools/README.md, either a bare list of rows
or {"generated_at": ..., "rows": [...]}.
Never overwrites, moves or deletes a file. Re-running is safe: existing identical files are skipped.
Python 3.8+ and PyYAML only. No OS-specific code, no database.
Exit codes: 0 clean, 1 finished with items needing a human (missing v1 file, conflict, leftover machine path), 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover
    sys.stderr.write("export_v1_handoffs.py needs PyYAML: python -m pip install pyyaml\n")
    sys.exit(2)

VERSION = "0.1.0"
EXPORT_STATUSES = ("open", "accepted")
SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
V1_TOP = ("00_Company", "01_Coworkers", "02_Founder", "03_Clients")

# Absolute v1 root on any machine: "<drive>:\Shared drives\Nexus\" or a Mac "<home>/.../Shared drives/Nexus/".
# The patterns are assembled so this file does not trip nexus.py's os-path rule on itself.
_SEP = r"[\\/]"
V1_ABS_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:" + _SEP + r"|" + "/" + "Users" + r"/[^\s`'\"]*?/)"
    r"Shared drives" + _SEP + r"Nexus" + _SEP + r"([^\s`'\")\]>]*)"
)
# Relative v1 paths such as 00_Company/02_Playbooks/x.md that are not already a v1: pointer.
V1_REL_RE = re.compile(r"(?<![\w/:\\.-])((?:" + "|".join(V1_TOP) + r")[\\/][^\s`'\")\]>]*)")
# nexus.py os-path rule, reproduced to report anything the rewrite could not turn into a pointer.
USERS_RE = re.compile("/" + "Users/")
DRIVE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


def as_date(v) -> str:
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()[:10]
    return "" if v is None else str(v)[:10]


def root_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    env = os.environ.get("NEXUS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    return here.parent if here.name == "bin" else here


def load_manifest(path: Path) -> tuple[list[dict], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("rows") or []), as_date(data.get("generated_at"))
    return list(data), ""


def strip_frontmatter(text: str) -> str:
    t = text.lstrip("\ufeff")
    lines = t.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return "\n".join(lines[i + 1:]).lstrip("\n")
    return t


def rewrite_v1_paths(body: str) -> tuple[str, int]:
    """Turn absolute and relative v1 paths into `v1:<posix path>` pointers. Returns (text, count)."""
    n = 0

    def _abs(m):
        nonlocal n
        n += 1
        return "v1:" + m.group(1).replace("\\", "/")

    def _rel(m):
        nonlocal n
        n += 1
        return "v1:" + m.group(1).replace("\\", "/")

    body = V1_ABS_RE.sub(_abs, body)
    body = V1_REL_RE.sub(_rel, body)
    return body, n


def leftover_machine_paths(text: str) -> list[int]:
    return [i for i, line in enumerate(text.splitlines(), 1) if USERS_RE.search(line) or DRIVE_RE.search(line)]


def render(row: dict, v1_text: str | None, today: str) -> tuple[str, int]:
    slug = row["slug"]
    v1_path = row["file_path"].replace("\\", "/")
    fm = {
        "id": slug,
        "type": "handoff",
        "owner": row["from_agent"],
        "status": row["status"],
        "updated": as_date(row.get("updated_on") or row.get("accepted_on") or row.get("opened_at")) or today,
        "scope": "internal",
        "to": row["to_agent"],
        "from": row["from_agent"],
        "date": as_date(row["opened_at"]),
        "topic": row.get("topic") or slug,
        "v1": v1_path,
    }
    head = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10_000) + "---\n\n"
    note = f"_Exported from v1 on {today} by `bin/export_v1_handoffs.py` v{VERSION}. Original: `v1:{v1_path}`._\n\n"
    if v1_text is None:
        body = f"# {fm['topic']}\n\n{note}**The v1 file was missing at export.** Read the v1 database row before acting.\n"
        return head + body, 0
    body, n = rewrite_v1_paths(strip_frontmatter(v1_text).rstrip() + "\n")
    if not re.search(r"^# ", body, re.M):
        body = f"# {fm['topic']}\n\n" + body
    # The provenance line sits under the first H1.
    body = re.sub(r"^(# [^\n]*\n)\n?", lambda m: m.group(1) + "\n" + note, body, count=1, flags=re.M)
    return head + body, n


def export(rows: list[dict], v1_root: Path, nexus_root: Path, write: bool, today: str) -> dict:
    out_dir = nexus_root / "queues" / "handoffs"
    report = {"written": [], "unchanged": [], "conflict": [], "missing_v1": [], "bad_slug": [],
              "skipped_status": [], "machine_path": [], "pointers": 0}
    seen = set()
    for row in sorted(rows, key=lambda r: (as_date(r.get("opened_at")), r.get("slug", ""))):
        slug = row.get("slug", "")
        if row.get("status") not in EXPORT_STATUSES:
            report["skipped_status"].append(slug)
            continue
        if not SLUG_RE.match(slug) or slug in seen:
            report["bad_slug"].append(slug)
            continue
        seen.add(slug)
        src = v1_root / Path(*row["file_path"].replace("\\", "/").split("/"))
        v1_text = src.read_text(encoding="utf-8") if src.is_file() else None
        if v1_text is None:
            report["missing_v1"].append(slug)
        content, n = render(row, v1_text, today)
        report["pointers"] += n
        left = leftover_machine_paths(content)
        if left:
            report["machine_path"].append(f"{slug} (lines {', '.join(map(str, left[:5]))})")
        target = out_dir / f"{slug}.md"
        if target.exists():
            same = target.read_text(encoding="utf-8") == content
            report["unchanged" if same else "conflict"].append(slug)
            continue
        if write:
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(content, encoding="utf-8", newline="\n")
            os.replace(tmp, target)
        report["written"].append(slug)
    return report


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True, help="JSON rows from the v1 handoffs table")
    ap.add_argument("--v1-root", required=True, help="the v1 Nexus folder (holds 00_Company/)")
    ap.add_argument("--nexus-root", help="the Nexus2 folder (default: NEXUS_ROOT, else parent of bin/)")
    ap.add_argument("--write", action="store_true", help="write files; without it, report only")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    a = ap.parse_args(argv)

    v1_root, nexus_root = Path(a.v1_root).expanduser().resolve(), root_dir(a.nexus_root)
    if not (v1_root / "00_Company").is_dir():
        print(f"v1 root has no 00_Company/: {v1_root}", file=sys.stderr)
        return 2
    if not (nexus_root / "queues").is_dir():
        print(f"Nexus2 root has no queues/: {nexus_root}", file=sys.stderr)
        return 2
    today = a.today or _dt.date.today().isoformat()
    rows, generated = load_manifest(Path(a.manifest))
    if generated and generated != today:
        print(f"warning: manifest generated {generated}, not today; statuses may have moved", file=sys.stderr)

    r = export(rows, v1_root, nexus_root, a.write, today)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        verb = "wrote" if a.write else "would write"
        print(f"{verb} {len(r['written'])} · unchanged {len(r['unchanged'])} · conflict {len(r['conflict'])} · "
              f"missing v1 file {len(r['missing_v1'])} · bad slug {len(r['bad_slug'])} · "
              f"not open/accepted {len(r['skipped_status'])} · v1 pointers {r['pointers']}")
        for key in ("conflict", "missing_v1", "bad_slug", "machine_path"):
            for s in r[key]:
                print(f"  {key}: {s}")
        if a.write and r["written"]:
            print("next: python bin/nexus.py index && python bin/nexus.py lint")
    return 1 if (r["conflict"] or r["missing_v1"] or r["bad_slug"] or r["machine_path"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
