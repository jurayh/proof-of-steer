"""Bundled demo suite (stdlib only, hermetic: runs anywhere git does).

The demo's sample session is hand-authored, and its expected receipt
below was HAND-COMPUTED from the session design before the pipeline
ever ran on it (the full computation is recorded in BUILD-NOTES.md,
section "Demo subcommand"). The design, per segment:

  0  Write reading_list.py, 17 non-blank lines, all unique   continuation
  1  "continue", assistant answers in prose, no tool calls   procedural
  2  Write test_reading_list.py, 11 lines, a new file        continuation (redirect)
  3  Edit: show() dashed -> numbered (2 lines of segment 0)  reshaping, overlap 4
  4  Write: whole file again plus one header line            continuation, introduces 1
  5  Edit: header line removed again                         reshaping, overlap 3
  6  Edit: the "added:" line reworded; then pytest runs      reshaping, overlap 2

Overlap follows the tracked replay definition exactly: the non-blank
earlier-segment lines inside an edit's replaced span, plus the
earlier-segment lines the provenance merge destroys. Segment 3: span
2 + destroyed 2 = 4. Segment 5: the span covers the header line
(segment 4) and the for-line (segment 3) = 2, plus the destroyed
header line = 3. Segment 6: span 1 + destroyed 1 = 2. Total
reshaping lines 4 + 3 + 2 = 9.

Final artifact: reading_list.py 17 lines (origins: segment 0 x14,
segment 3 x2, segment 6 x1, segment 4 x0 because its only line was
discarded by segment 5) plus the test file's 11 lines (segment 2):
28 non-blank lines. Post-first share = (11 + 2 + 1) / 28 = 50.0%.
First-segment survival = 14 of its 17 lines = 82.4%. Mark: 3
reshaping turns of 7 is 42.9%, at or over the 20% threshold, so
Closely steered.

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import contextlib, io, json, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import demo as demo_mod

EXPECTED_CLASSES = ["continuation", "procedural", "continuation", "reshaping",
                    "continuation", "reshaping", "reshaping"]
EXPECTED_OVERLAP = [0, 0, 0, 4, 0, 3, 2]
EXPECTED_INTRODUCED = [17, 0, 11, 2, 1, 0, 1]
EXPECTED_SURVIVING = [14, 0, 11, 2, 0, 0, 1]

def run_demo(tmp):
    out = Path(tmp) / "demo-out"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = demo_mod.run_demo(out)
    return out, buf.getvalue(), rc

class TestDemoReceipt(unittest.TestCase):
    def test_receipt_matches_hand_computation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _stdout, rc = run_demo(tmp)
            self.assertEqual(rc, 0)
            r = json.loads((out / "demo.receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(r["schema"], "proof-of-steering/receipt@1.0")
            self.assertEqual(r["kind"], "code")
            self.assertEqual(r["harness"], "claude-code")
            m, g = r["mechanistic"], r["git_join"]
            self.assertEqual(m["human_turns"], 7)
            self.assertEqual(m["correction_keyword_prompts"], 3)
            self.assertEqual(m["rubber_stamp_prompts"], 1)
            self.assertEqual(m["prompts_after_error"], 0)
            self.assertEqual(m["injected_user_records_filtered"], 0)
            self.assertEqual(m["verification_lanes"]["test_like_shell"], 1)
            self.assertEqual(m["verification_lanes"]["shell_total"], 1)
            c = m["coverage"]
            self.assertEqual((c["writes"], c["edits_total"]), (3, 3))
            self.assertEqual(c["edits_applied_on_transcript_base"], 3)
            self.assertEqual(c["edits_unapplied_no_base"], 0)
            self.assertEqual(c["edits_unapplied_no_match"], 0)
            self.assertEqual(g["files_at_head"], 2)
            self.assertEqual(g["final_nonblank_lines"], 28)
            self.assertEqual(g["headline_fields"]["post_first_prompt_share_pct"], 50.0)
            self.assertEqual(g["headline_fields"]["preexisting_share_pct"], 0.0)
            self.assertEqual(g["context_fields"]["first_segment_survival_pct"], 82.4)
            self.assertEqual(g["supporting_fields"]["correction_segment_share_pct"], 10.7)
            self.assertEqual(g["blame_vs_memory_provenance_agreement_pct"], 100.0)
            im = g["impact"]
            # Segment 0 is itself a continuation (an applied Write with
            # no earlier lines to touch), so the continuation count is
            # 3, not 2: segments 0, 2, and 4.
            self.assertEqual(im["procedural_turns"], 1)
            self.assertEqual(im["continuation_turns"], 3)
            self.assertEqual(im["reshaping_turns"], 3)
            self.assertEqual(im["unmeasured_segments"], 0)
            self.assertEqual(im["reshaping_share_pct"], 42.9)
            self.assertEqual(im["reshaping_lines"], 9)
            self.assertEqual(im["redirect_segments"], 1)
            segs = g["per_segment"]
            self.assertEqual([s["impact_class"] for s in segs], EXPECTED_CLASSES)
            self.assertEqual([s["overlap_earlier_lines"] for s in segs], EXPECTED_OVERLAP)
            self.assertEqual([s["lines_introduced_gross"] for s in segs], EXPECTED_INTRODUCED)
            self.assertEqual([s["lines_surviving_to_head"] for s in segs], EXPECTED_SURVIVING)
            self.assertEqual([s["redirect"] for s in segs],
                             [False, False, True, False, False, False, False])
            self.assertEqual(r["mark"]["category"], "Closely steered")
            self.assertEqual(r["mark"]["basis"],
                             "7 human turns; 3 of them reshaped earlier work "
                             "(42.9% of turns, 9 earlier lines rewritten)")
            # receipts never carry raw prompt text
            blob = json.dumps(r)
            self.assertNotIn("keeps a list of books", blob)
            self.assertNotIn("cleaner without it", blob)

    def test_outputs_and_guided_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, stdout, rc = run_demo(tmp)
            self.assertEqual(rc, 0)
            for name in ("demo.receipt.json", "demo.STEERING.md",
                         "demo.badge.svg", "demo.steerprint.html"):
                self.assertTrue((out / name).exists(), name)
            badge = ET.fromstring((out / "demo.badge.svg").read_text(encoding="utf-8"))
            self.assertEqual(badge.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertIn("CLOSELY STEERED", (out / "demo.badge.svg").read_text(encoding="utf-8"))
            html = (out / "demo.steerprint.html").read_text(encoding="utf-8")
            self.assertIn("Collaboration Maps", html)
            md = (out / "demo.STEERING.md").read_text(encoding="utf-8")
            self.assertIn("Closely steered", md)
            # the summary is honest about what the sample is, states the
            # mark and headline, and ends by inviting a real session
            self.assertIn("synthetic", stdout)
            self.assertIn("not a real session", stdout)
            self.assertIn("Steering mark: Closely steered", stdout)
            self.assertIn("50.0%", stdout)
            self.assertIn("proof-of-steer code path/to/session.jsonl --label my-session", stdout)

    def test_demo_cli_from_another_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "elsewhere" / "demo-out"
            run = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"),
                                  "demo", "--out", str(out)],
                                 capture_output=True, text=True, cwd=tmp)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("proof-of-steer demo", run.stdout)
            self.assertTrue((out / "demo.receipt.json").exists())
            self.assertTrue((out / "demo.badge.svg").exists())
            self.assertTrue((out / "demo.steerprint.html").exists())

if __name__ == "__main__":
    unittest.main()
