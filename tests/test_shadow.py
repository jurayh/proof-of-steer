"""Counterfactual shadow figure (steering_viz --shadow).

The figure lights only the lines the first prompt introduced that survive
to the final artifact. These tests pin that semantics exactly: the replay
derivation on a small synthetic session, the strip widths the HTML builder
emits for fixed rows, the document rows taken from a receipt's own revision
maps, and the shipped example figure against the two receipts it was drawn
from (plus the findings-draft doc receipt).

Run from release/:  python3 -m unittest discover -s tests -v
"""
import json, re, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import steering_viz
import steering_receipt as sr

EXAMPLE = V1 / "examples" / "counterfactual-shadow.html"
STEERED = V1 / "examples" / "code-steered-860618e1.receipt.json"
CONTROL = V1 / "examples" / "code-oneprompt-4130c9a7.receipt.json"
FINDINGS = V1 / "examples" / "doc-steered-findings-draft.receipt.json"


def _session_record(type_, text=None, tool=None, ts="2026-10-21T10:00:00Z", mid=None):
    if type_ == "user":
        return {"type": "user", "timestamp": ts,
                "message": {"content": [{"type": "text", "text": text}]}}
    blk = {"type": "tool_use", "name": tool[0], "input": tool[1]}
    if mid:
        blk["id"] = mid
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid or "m", "usage": {"input_tokens": 1, "output_tokens": 1},
                        "content": [blk]}}


SYNTHETIC = [
    _session_record("user", "Build it"),
    _session_record("assistant", tool=("Write", {"file_path": "a.py", "content": "alpha\nbeta\ngamma\n"}), mid="m1"),
    _session_record("assistant", tool=("Write", {"file_path": "b.py", "content": "one\ntwo\n"}), mid="m2"),
    _session_record("user", "Change one line"),
    _session_record("assistant", tool=("Edit", {"file_path": "a.py", "old_string": "beta", "new_string": "beta2\nbeta3"}), mid="m3"),
]


class TestShadowRows(unittest.TestCase):
    def test_replay_derivation_on_synthetic_session(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC), encoding="utf-8")
            rows, summary = steering_viz.shadow_replay_session(p)
        by_file = {r["file"]: r for r in rows}
        # a.py: alpha, beta2, beta3, gamma; lit = alpha, gamma (origin segment 0)
        self.assertEqual(by_file["a.py"]["final_lines"], 4)
        self.assertEqual(by_file["a.py"]["lit_lines"], 2)
        # b.py untouched since segment 0: fully lit
        self.assertEqual(by_file["b.py"]["final_lines"], 2)
        self.assertEqual(by_file["b.py"]["lit_lines"], 2)
        self.assertEqual(summary["turns"], 2)
        self.assertEqual(summary["final_lines"], 6)
        self.assertEqual(summary["lit_lines"], 4)

    def test_doc_rows_from_receipt_revision_maps(self):
        r = json.loads(FINDINGS.read_text(encoding="utf-8"))
        rows = steering_viz.shadow_doc_rows(r)
        self.assertEqual(len(rows), 18)
        self.assertEqual(sum(x["final_lines"] for x in rows), 242)
        # Lit lines are exactly the revision-1 introductions; total must
        # equal the receipt's own 36.0% floor, not an estimate from it.
        self.assertEqual(sum(x["lit_lines"] for x in rows), 87)
        by_section = {x["section"]: x for x in rows}
        self.assertEqual(by_section["Rented-GPU cost estimate (checked 2026-10-17, secondary pricing pages)"]["lit_lines"], 0)
        self.assertEqual(by_section["What was built and verified (executed, not assumed)"]["lit_lines"], 10)


class TestShadowHtml(unittest.TestCase):
    def test_strip_widths_and_totals_for_fixed_rows(self):
        steered = {"title": "S", "turns": 3, "final_lines": 150, "lit_lines": 30,
                   "rows": [{"file": "a.py", "final_lines": 100, "lit_lines": 30},
                            {"file": "b.py", "final_lines": 50, "lit_lines": 0}]}
        control = {"title": "C", "turns": 1, "final_lines": 80, "lit_lines": 80,
                   "rows": [{"file": "c.py", "final_lines": 80, "lit_lines": 80}]}
        html = steering_viz.shadow_html(steered, control)
        # Shared scale: max file is 100 lines, so a.py spans 100%,
        # b.py 50%, c.py 80%; lit widths are within-file shares.
        self.assertIn('width:100.00%', html)
        self.assertIn('width:50.00%', html)
        self.assertIn('width:80.00%', html)
        self.assertIn('width:30.0%', html)
        self.assertIn('width:0.0%', html)
        self.assertIn('30</b> of <b>150</b> lines lit', html)
        self.assertIn('80</b> of <b>80</b> lines lit', html)

    def test_shipped_example_matches_receipts(self):
        html = EXAMPLE.read_text(encoding="utf-8")
        steered = json.loads(STEERED.read_text(encoding="utf-8"))
        control = json.loads(CONTROL.read_text(encoding="utf-8"))
        g = steered["git_join"]
        # Headline numbers from the receipts themselves.
        self.assertEqual(g["headline_fields"]["post_first_prompt_share_pct"], 87.2)
        self.assertEqual(g["final_nonblank_lines"], 3102)
        self.assertEqual(control["git_join"]["headline_fields"]["post_first_prompt_share_pct"], 0.0)
        self.assertEqual(control["git_join"]["final_nonblank_lines"], 3547)
        # The figure must carry those exact numbers: lit = 100 - post-first.
        for needle in ["398", "3,102", "12.8%", "3,547"]:
            self.assertIn(needle, html)
        # The three files that hold lit lines, with exact counts, in the note.
        for needle in ["IceBerg/style.css (380)", "IceBerg/main.js (15)", "IceBerg/index.html (3)"]:
            self.assertIn(needle, html)
        # Document analogue totals from the findings receipt.
        self.assertIn("87", html)
        self.assertIn("242", html)
        self.assertIn("36.0%", html)
        # Captions: short human prose, no em-dashes, no semicolons.
        for cap in re.findall(r'<p class="sh-caption">(.*?)</p>', html, re.S):
            text = re.sub(r"<[^>]+>", "", cap)
            self.assertNotIn("\u2014", text)
            self.assertNotIn(";", text)
        # Self-contained: no external assets.
        self.assertNotIn("<link", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)


if __name__ == "__main__":
    unittest.main()
