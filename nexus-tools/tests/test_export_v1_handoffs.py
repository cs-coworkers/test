"""Fixture tests for bin/export_v1_handoffs.py. Run: python -m unittest discover nexus-tools/tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "bin" / "export_v1_handoffs.py"
sys.path.insert(0, str(SCRIPT.parent))
import export_v1_handoffs as ex  # noqa: E402

TODAY = "2026-09-28"
HDIR = "00_Company/02_Playbooks/handoffs"
# nexus.py lint requirements for a handoff file.
REQUIRED = ("id", "type", "owner", "status", "updated", "scope")


def row(slug, status="accepted", **kw):
    frm, to = slug[11:].split("-to-")[0], slug[11:].split("-to-")[1].split("-")[0]
    r = {"slug": slug, "from_agent": frm, "to_agent": to, "opened_at": slug[:10], "topic": f"topic of {slug}",
         "status": status, "accepted_on": None, "updated_on": "2026-09-20", "file_path": f"{HDIR}/{slug}.md"}
    r.update(kw)
    return r


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.v1, self.n2 = base / "v1", base / "n2"
        (self.v1 / HDIR).mkdir(parents=True)
        (self.n2 / "queues" / "handoffs").mkdir(parents=True)
        self.manifest = base / "rows.json"

    def tearDown(self):
        self.tmp.cleanup()

    def v1file(self, slug, text):
        (self.v1 / HDIR / f"{slug}.md").write_text(text, encoding="utf-8")

    def run_cli(self, rows, *extra):
        self.manifest.write_text(json.dumps({"generated_at": TODAY, "rows": rows}), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--manifest", str(self.manifest), "--v1-root", str(self.v1),
             "--nexus-root", str(self.n2), "--today", TODAY, "--json", *extra],
            capture_output=True, text=True)

    def out(self, slug):
        return (self.n2 / "queues" / "handoffs" / f"{slug}.md").read_text(encoding="utf-8")

    def test_writes_lint_shaped_file_with_pointers(self):
        s = "2026-09-26-clarice-to-cody-nexus2-migration-tooling"
        drive = "G" + ":\\Shared drives\\Nexus\\01_Coworkers\\Cody\\04_Outputs\\x.md"
        self.v1file(s, "---\nfrom: clarice\nto: cody\n---\n\n- [x] cody: accept\n\n**Where:** PRD "
                       "`00_Company/00_Projects/nexus-v2/PRD.md` and " + drive + " and `v1:00_Company/y.md`\n")
        p = self.run_cli([row(s)], "--write")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        text = self.out(s)
        fm = yaml.safe_load(text.split("---\n")[1])
        for k in REQUIRED:
            self.assertTrue(fm.get(k), k)
        self.assertEqual((fm["type"], fm["to"], fm["from"], fm["status"]), ("handoff", "cody", "clarice", "accepted"))
        self.assertEqual(fm["date"], "2026-09-26")
        self.assertIn("`v1:00_Company/00_Projects/nexus-v2/PRD.md`", text)
        self.assertIn("v1:01_Coworkers/Cody/04_Outputs/x.md", text)
        self.assertIn("`v1:00_Company/y.md`", text)          # existing pointer untouched
        self.assertNotIn("v1:v1:", text)
        self.assertEqual(ex.leftover_machine_paths(text), [])
        self.assertTrue(text.split("---\n", 2)[2].lstrip().startswith("# topic of"))
        self.assertIn("Original: `v1:" + HDIR, text)

    def test_dry_run_writes_nothing(self):
        s = "2026-09-20-sam-to-cody-x"
        self.v1file(s, "body\n")
        p = self.run_cli([row(s)])
        self.assertEqual(json.loads(p.stdout)["written"], [s])
        self.assertFalse((self.n2 / "queues" / "handoffs" / f"{s}.md").exists())

    def test_rerun_is_idempotent_and_never_overwrites(self):
        s = "2026-09-20-sam-to-cody-x"
        self.v1file(s, "body\n")
        self.run_cli([row(s)], "--write")
        first = self.out(s)
        r2 = json.loads(self.run_cli([row(s)], "--write").stdout)
        self.assertEqual((r2["written"], r2["unchanged"]), ([], [s]))
        self.v1file(s, "changed body\n")
        p3 = self.run_cli([row(s)], "--write")
        self.assertEqual(json.loads(p3.stdout)["conflict"], [s])
        self.assertEqual(p3.returncode, 1)
        self.assertEqual(self.out(s), first)

    def test_skips_closed_and_flags_missing_and_bad(self):
        rows = [row("2026-09-01-sam-to-cody-done", status="done"),
                row("2026-09-02-sam-to-cody-gone"),
                row("2026-09-03-Sam-to-cody-caps")]
        r = json.loads(self.run_cli(rows, "--write").stdout)
        self.assertEqual(r["skipped_status"], ["2026-09-01-sam-to-cody-done"])
        self.assertEqual(r["missing_v1"], ["2026-09-02-sam-to-cody-gone"])
        self.assertEqual(r["bad_slug"], ["2026-09-03-Sam-to-cody-caps"])
        self.assertIn("v1 file was missing", self.out("2026-09-02-sam-to-cody-gone"))

    def test_unknown_machine_path_is_reported(self):
        s = "2026-09-20-sam-to-cody-x"
        self.v1file(s, "see " + "C" + ":\\Temp\\notes.txt\n")
        p = self.run_cli([row(s)], "--write")
        self.assertEqual(p.returncode, 1)
        self.assertTrue(json.loads(p.stdout)["machine_path"])

    def test_script_passes_its_own_os_path_rule(self):
        self.assertEqual(ex.leftover_machine_paths(SCRIPT.read_text(encoding="utf-8")), [])

    def test_topic_with_yaml_specials_round_trips(self):
        s = "2026-09-20-sam-to-cody-x"
        self.v1file(s, "b\n")
        t = 'x: "quoted" #hash | pipe'
        self.run_cli([row(s, topic=t)], "--write")
        self.assertEqual(yaml.safe_load(self.out(s).split("---\n")[1])["topic"], t)


if __name__ == "__main__":
    unittest.main()
