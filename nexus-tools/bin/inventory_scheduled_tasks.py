#!/usr/bin/env python3
"""inventory_scheduled_tasks.py - list every scheduled task's Nexus paths before the Nexus2 cutover.

Handoff 2026-09-26-clarice-to-cody-nexus2-migration-tooling, item 3. A task that still points at a v1 path
after its coworker migrates fails silently. This reads each task's local prompt file and reports the
paths it reads and writes.

Usage:
    python bin/inventory_scheduled_tasks.py --scheduled-dir <folder holding one <taskId>/SKILL.md per task>
    python bin/inventory_scheduled_tasks.py --scheduled-dir <...> --json

The scheduled-task folder location per machine is in hosts/machines.md (v1: 00_Company/02_Playbooks/seat-platforms.md).
Read and write are a guess from the words on the same line; the table says so. Python 3.8+ only, no PyYAML.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERSION = "0.1.0"
V1_TOP = ("00_Company", "01_Coworkers", "02_Founder", "03_Clients")
V2_TOP = ("charter", "coworkers", "clients", "queues", "skills", "doctrine", "dossiers", "hosts", "_generated", "bin")
_SEP = r"[\\/]"
_TAIL = r"[^\s`'\")\]>,;]*"
V1_ABS_RE = re.compile(r"Shared drives" + _SEP + r"Nexus" + _SEP + r"(" + _TAIL + r")")
V1_REL_RE = re.compile(r"(?<![\w/:\\.-])(?:v1:)?((?:" + "|".join(V1_TOP) + r"|<HOME>)" + _SEP + _TAIL + r")")
V2_REL_RE = re.compile(r"(?<![\w/:\\.-])((?:" + "|".join(V2_TOP) + r")/" + _TAIL + r")")
IDENTITY_RE = re.compile(r"\bYou are (?:running [^.]*? as )?([A-Z][a-z]+)\b")
WRITE_RE = re.compile(r"\b(writes?|append|appends|create|creates|edit|edits|update|updates|save|saves|log|logs|"
                      r"tick|ticks|move|moves|insert|record|records|set)\b", re.IGNORECASE)
NOT_NAMES = {"The", "This", "A", "An", "Running", "Not", "Now"}


def norm(p: str) -> str:
    return p.replace("\\", "/").rstrip(".:")


def scan_prompt(text: str) -> dict:
    owner = ""
    for m in IDENTITY_RE.finditer(text):
        if m.group(1) not in NOT_NAMES:
            owner = m.group(1).lower()
            break
    reads, writes, v2 = set(), set(), set()
    for line in text.splitlines():
        found = [norm(m.group(1)) for m in V1_ABS_RE.finditer(line)]
        found += [norm(m.group(1)) for m in V1_REL_RE.finditer(line)]
        (writes if WRITE_RE.search(line) else reads).update(found)
        v2.update(norm(m.group(1)) for m in V2_REL_RE.finditer(line))
    reads -= writes
    return {"owner": owner, "v1_reads": sorted(reads), "v1_writes": sorted(writes), "v2_refs": sorted(v2)}


def inventory(sched: Path) -> list[dict]:
    rows = []
    for d in sorted(p for p in sched.iterdir() if p.is_dir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        r = {"task": d.name, **scan_prompt(text)}
        r["cutover_risk"] = "yes" if (r["v1_reads"] or r["v1_writes"]) else "no"
        rows.append(r)
    return rows


def cell(items: list[str]) -> str:
    return "<br>".join(f"`{x}`" for x in items) if items else "none"


def to_markdown(rows: list[dict], machine: str) -> str:
    out = [f"Scanned {len(rows)} task prompt(s) on {machine or 'this machine'}. "
           "Read and write are a guess from the words on each line: check before repointing.", "",
           "| task | owner (identity line) | v1 reads | v1 writes | Nexus2 refs | cutover risk | edited by |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| `{r['task']}` | {r['owner'] or 'no identity line'} | {cell(r['v1_reads'])} | "
                   f"{cell(r['v1_writes'])} | {cell(r['v2_refs'])} | {r['cutover_risk']} | Charlie (desktop task) |")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scheduled-dir", required=True)
    ap.add_argument("--machine", default="", help="label for the report, e.g. pc or mac")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sched = Path(a.scheduled_dir).expanduser()
    if not sched.is_dir():
        print(f"not a folder: {sched}", file=sys.stderr)
        return 2
    rows = inventory(sched)
    print(json.dumps(rows, indent=2) if a.json else to_markdown(rows, a.machine))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
