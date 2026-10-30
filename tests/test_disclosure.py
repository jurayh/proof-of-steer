"""Document disclosure rendering (steering_viz --disclosure).

The disclosure block is generated from a document receipt JSON only: every
number in it is read from the receipt, never recomputed, so the block
cannot drift from the receipt it describes. These tests assert the
rendered block against hand-checked expectations for two real receipts,
plus parity between the shipped sample in examples/document-disclosure.md
and the renderer's output for the same receipt.

Run from release/:  python3 -m unittest discover -s tests -v
"""
import json, re, subprocess, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import steering_viz

FINDINGS = V1 / "examples" / "doc-steered-findings-draft.receipt.json"
LAUNCH = Path.home() / "workspace" / "proof-of-steering" / "announcement-receipt" / "receipts-out" / "launch-post.receipt.json"
CODE = V1 / "examples" / "code-steered-860618e1.receipt.json"
DOC_FILE = V1 / "examples" / "document-disclosure.md"

needs_launch = unittest.skipUnless(LAUNCH.exists(),
                                    "launch-post receipt not present in workspace")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def group_lines(block, heading):
    """Bullet lines under one group heading, or [] when the group is absent."""
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if line == heading:
            out = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("  - "):
                    out.append(nxt[4:])
                elif nxt.startswith("- ") or nxt == "":
                    break
            return out
    return None


class DisclosureFindingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = load(FINDINGS)
        cls.block = steering_viz.disclosure_md(cls.receipt)

    def test_mark_and_floor_match_receipt(self):
        self.assertIn("- Steering mark: Closely steered, 3 revisions", self.block)
        self.assertIn("at least 36.0% of the final text survives verbatim", self.block)
        self.assertIn("38.3% of final sentences", self.block)

    def test_unchanged_group_is_exact(self):
        self.assertEqual(group_lines(self.block, "- Sections unchanged since the first version:"),
                         ["What was built and verified (executed, not assumed)",
                          "The one honest caveat that governs everything below",
                          "Instrument results (scripted models, seed 0, n=200/category)",
                          "Calibration findings (the useful phase-1 output)",
                          "Verdict against the kill criteria (phase 1)"])

    def test_arrived_group_names_and_revisions(self):
        arrived = group_lines(self.block, "- Sections that arrived in later revisions:")
        self.assertEqual(len(arrived), 11)
        self.assertIn("Rented-GPU cost estimate (checked 2026-10-17, secondary pricing pages) (revision 2)", arrived)
        self.assertIn("Still stubbed, and why (revision 3)", arrived)
        self.assertTrue(all("(revision 3)" in a for a in arrived if "Rented-GPU" not in a))

    def test_reshaped_uses_receipt_count_not_gained_lines(self):
        # The edge the receipt itself documents: 2 sections gained lines
        # later, but the mark counts 1 as reshaped, because its rule
        # requires the section heading to survive unchanged and the title
        # section's heading text changed. The block must reproduce the
        # receipt's count, never the larger number.
        self.assertIn("- Sections reshaped after first appearing: 1 of 18 sections.", self.block)
        self.assertIn("Note: 2 sections gained lines in later revisions, but the mark counts 1 as reshaped.", self.block)
        self.assertIsNone(group_lines(self.block, "- Sections reshaped after first appearing:"))

    def test_history_and_standing_lines(self):
        self.assertIn("- History: complete, 3 revisions from git", self.block)
        self.assertIn("- Full section map: see the STEERING.md that travels with this receipt.", self.block)
        self.assertIn("Descriptive evidence, never a certified grade.", self.block)
        self.assertIn("a lower bound on interaction.", self.block)
        self.assertIn("Delete this section if no agent was involved.", self.block)

    def test_block_prose_has_no_emdash_or_semicolon(self):
        # Section titles are quoted verbatim from the receipt and may
        # contain either character as data; the block's own prose must not.
        prose = [l for l in self.block.splitlines() if not l.startswith("  - ")]
        for line in prose:
            self.assertNotIn("\u2014", line, line)
            self.assertNotIn(";", line, line)


@needs_launch
class DisclosureLaunchPostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = load(LAUNCH)
        cls.block = steering_viz.disclosure_md(cls.receipt)

    def test_mark_floor_and_groups(self):
        self.assertIn("- Steering mark: Closely steered, 3 revisions", self.block)
        self.assertIn("at least 77.8% of the final text survives verbatim", self.block)
        self.assertIn("78.3% of final sentences", self.block)
        self.assertEqual(group_lines(self.block, "- Sections unchanged since the first version:"),
                         ["proof-of-steer launch post"])
        # Every section has first-version lines, so no arrived group.
        self.assertIsNone(group_lines(self.block, "- Sections that arrived in later revisions:"))

    def test_reshaped_lists_names_when_counts_agree(self):
        # Here the sections that gained lines (2) equal the mark's
        # reshaped count (2), so names are listed, with later-line detail.
        self.assertEqual(group_lines(self.block, "- Sections reshaped after first appearing:"),
                         ["Short version (social post) (1 line added in revision 2)",
                          "Long version (Show HN / forum) (5 lines added in revisions 2 and 3)"])
        self.assertNotIn("Note:", self.block)

    def test_history(self):
        self.assertIn("- History: complete, 3 revisions from git", self.block)


class DisclosureFileParityTest(unittest.TestCase):
    def test_shipped_sample_equals_renderer_output(self):
        text = DOC_FILE.read_text(encoding="utf-8")
        fences = re.findall(r"```markdown\n(.*?)\n```", text, re.DOTALL)
        self.assertEqual(len(fences), 1, "expected exactly one filled-sample fence")
        self.assertEqual(fences[0], steering_viz.disclosure_md(load(FINDINGS)).rstrip("\n"))


class DisclosureCliTest(unittest.TestCase):
    def test_cli_writes_same_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "disclosure.md"
            proc = subprocess.run([sys.executable, str(V1 / "steering_viz.py"),
                                   str(FINDINGS), "--disclosure", "-o", str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(out.read_text(encoding="utf-8"),
                             steering_viz.disclosure_md(load(FINDINGS)))

    def test_cli_rejects_code_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(V1 / "steering_viz.py"),
                                   str(CODE), "--disclosure",
                                   "-o", str(Path(tmp) / "d.md")],
                                  capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("document receipt", proc.stderr)


class DisclosureTruncatedTest(unittest.TestCase):
    def test_truncated_history_flags_baseline(self):
        receipt = {
            "kind": "document",
            "mark": {"category": "Prompted", "reshaped_sections": 0, "sections": 2},
            "revision_count": 2,
            "overall_pct_unchanged_from_first_version": 60.0,
            "history_complete": False,
            "provider": "folder",
            "per_section": [
                {"section": "Intro", "final_lines": 6,
                 "pct_unchanged_from_first_version": 100.0,
                 "introduced_by_revision": {"rev1 (aaa)": 6}},
                {"section": "Later", "final_lines": 4,
                 "pct_unchanged_from_first_version": 0.0,
                 "introduced_by_revision": {"rev2 (bbb)": 4}},
            ],
        }
        block = steering_viz.disclosure_md(receipt)
        self.assertIn("- History: truncated at the first available revision, 2 revisions observed.", block)
        self.assertIn("Anything before that baseline is unmeasured", block)
        self.assertIsNone(group_lines(block, "- Sections reshaped after first appearing:"))


if __name__ == "__main__":
    unittest.main()
