"""Fixture tests for bin/inventory_scheduled_tasks.py. Run: python -m unittest discover nexus-tools/tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "bin" / "inventory_scheduled_tasks.py"
sys.path.insert(0, str(SCRIPT.parent))
import inventory_scheduled_tasks as inv  # noqa: E402
import export_v1_handoffs as ex  # noqa: E402

SAM = """---
name: substack-weekday-drain
---
You are Sam, the sales & marketing coworker at Coworkers.Global.
Read 00_Company/07_Departments/sales-marketing/campaigns/syndication-matrix.md first.
Read """ + "G" + r""":\Shared drives\Nexus\01_Coworkers\Sam\02_Tasks\TASKS.md for open items.
Append one line to `01_Coworkers/Sam/05_Inbox/run-log.md` even on failure.
"""
CLARICE_V2 = """You are running a scheduled job as Clarice.
Read coworkers/clarice/tasks.md and queues/handoffs/. Write coworkers/clarice/journal/<today>.md.
"""
REMINDER = "Remind Charlie to send the draft.\n"


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name, text in (("substack-weekday-drain", SAM), ("clarice-v2-job", CLARICE_V2),
                           ("remind-send", REMINDER)):
            (self.dir / name).mkdir()
            (self.dir / name / "SKILL.md").write_text(text, encoding="utf-8")
        (self.dir / "empty-folder").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--scheduled-dir", str(self.dir), "--json"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return {r["task"]: r for r in json.loads(p.stdout)}

    def test_v1_task_reads_writes_and_risk(self):
        r = self.rows()["substack-weekday-drain"]
        self.assertEqual(r["owner"], "sam")
        self.assertIn("00_Company/07_Departments/sales-marketing/campaigns/syndication-matrix.md", r["v1_reads"])
        self.assertIn("01_Coworkers/Sam/02_Tasks/TASKS.md", r["v1_reads"])
        self.assertEqual(r["v1_writes"], ["01_Coworkers/Sam/05_Inbox/run-log.md"])
        self.assertEqual(r["cutover_risk"], "yes")

    def test_v2_task_is_not_a_cutover_risk(self):
        r = self.rows()["clarice-v2-job"]
        self.assertEqual(r["owner"], "clarice")
        self.assertEqual((r["v1_reads"], r["v1_writes"], r["cutover_risk"]), ([], [], "no"))
        self.assertIn("queues/handoffs/", r["v2_refs"])

    def test_no_identity_and_folder_without_prompt(self):
        rows = self.rows()
        self.assertEqual(rows["remind-send"]["owner"], "")
        self.assertNotIn("empty-folder", rows)

    def test_markdown_table(self):
        md = inv.to_markdown(inv.inventory(self.dir), "pc")
        self.assertIn("| `substack-weekday-drain` | sam |", md)
        self.assertIn("no identity line", md)

    def test_script_passes_os_path_rule(self):
        self.assertEqual(ex.leftover_machine_paths(SCRIPT.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
