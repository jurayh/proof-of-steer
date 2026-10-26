"""Op-collection regression (v0.1.4, hermetic).

Fix 1: Edit/Write op collection sits outside the parser's message-id
dedupe, keyed by tool_use id. The false one-shot validation
(../false-oneshot-validation/REPORT.md, mechanism M1) measured 846 of
1,613 ops (52%) lost on trace-commons because block-per-record
transcripts put a message's ops in later records the dedupe steps
over. Fix 3: the coverage block reports ops present in the
transcript vs ops collected, so the loss class is visible on the
receipt itself.

The fixture (session_block_records.jsonl) is hand-built in the
block-per-record shape, one record per content block under a shared
message id, with expectations computed by hand:

  msg_a (segment 0): text record, then a Write record (toolu_w1,
    greeter.py), then a Bash record. Only the Write is an artifact
    op, and it lives in a later block-record.
  msg_b (segment 1): text record, then an Edit record (toolu_e1,
    greeter.py: the return line, introduced by segment 0), then a
    second record re-emitting the SAME Edit block.
  msg_c (segment 1): a normal single-record message with a Write
    (toolu_w2, main.py).

Hand-computed: 3 distinct Edit/Write ops present, 3 collected
(segment 0: the Write; segment 1: the Edit once, then the Write).
Tokens dedupe as before (usage rides on every block-record of a
message and counts once): in 180, out 70. The Bash block in msg_a's
third record is NOT counted (tool counters stay deduped with the
record stream, exactly as before this build). Impact: segment 0
continuation, segment 1 reshaping (span 1 + destroyed 1 = 2
reshaping lines) and a redirect (main.py first touched there).
Mark: Steered. Under the pre-0.1.4 parser the same fixture collects
1 of 3 ops and reads Prompted.

The census test pins collected counts against a raw-transcript
census computed independently in this file, the same census the
validation used (distinct Edit/Write tool_use ids, kept iff the id
appears under its message id at all once collection is keyed by id).

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import json, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import steering_receipt as sr

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BLOCK_RECORDS = FIXTURES / "session_block_records.jsonl"
SINGLE_RECORD = FIXTURES / "session_decisions_basic.jsonl"


def raw_op_census(path):
    """Distinct Edit/Write tool_use ids in the raw transcript,
    counted over every assistant record (the validation's census)."""
    ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") != "assistant":
            continue
        for blk in (r.get("message") or {}).get("content") or []:
            if isinstance(blk, dict) and blk.get("type") == "tool_use" \
                    and blk.get("name") in ("Edit", "Write"):
                ids.add(blk.get("id"))
    return ids


class TestBlockRecordOpCollection(unittest.TestCase):
    def setUp(self):
        self.segments, self.meta = sr.parse_session(str(BLOCK_RECORDS))

    def test_collected_matches_raw_census(self):
        census = raw_op_census(BLOCK_RECORDS)
        self.assertEqual(len(census), 3)  # toolu_w1, toolu_e1, toolu_w2
        self.assertEqual(self.meta["ops_present_in_transcript"], len(census))
        self.assertEqual(self.meta["ops_collected"], len(census))

    def test_ops_attach_to_their_messages_segment(self):
        self.assertEqual(len(self.segments), 2)
        self.assertEqual([op[0] for op in self.segments[0]["ops"]], ["write"])
        self.assertEqual([op[0] for op in self.segments[1]["ops"]],
                         ["edit", "write"])

    def test_reemitted_op_collected_exactly_once(self):
        edits = [op for s in self.segments for op in s["ops"] if op[0] == "edit"]
        self.assertEqual(len(edits), 1)

    def test_tokens_and_tool_counters_stay_deduped(self):
        # usage rides on all 3 msg_a records and both msg_b records;
        # it counts once per message, as before this build
        self.assertEqual(self.meta["tokens_in"], 180)
        self.assertEqual(self.meta["tokens_out"], 70)
        # the Bash block sits in a dedupe-skipped record: its counter
        # stays uncounted, exactly the pre-build behaviour
        self.assertEqual(sum(s["shell_calls"] for s in self.segments), 0)
        self.assertEqual(sum(s["test_bash"] for s in self.segments), 0)


class TestCompletenessFields(unittest.TestCase):
    def test_coverage_block_reports_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(str(BLOCK_RECORDS), "blockrec",
                                recon_dir=Path(tmp) / "recon")
        c = r["mechanistic"]["coverage"]
        self.assertEqual(c["ops_present_in_transcript"], 3)
        self.assertEqual(c["ops_collected"], 3)
        self.assertEqual((c["writes"], c["edits_total"]), (2, 1))
        self.assertEqual(c["edits_applied_on_transcript_base"], 1)
        md = sr.render_md(r)
        self.assertIn("Op collection: 3 of 3 Edit/Write ops present in "
                      "the transcript were collected", md)

    def test_impact_and_mark_see_the_collected_ops(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(str(BLOCK_RECORDS), "blockrec",
                                recon_dir=Path(tmp) / "recon")
        g = r["git_join"]
        self.assertEqual([s["impact_class"] for s in g["per_segment"]],
                         ["continuation", "reshaping"])
        self.assertEqual(g["impact"]["reshaping_lines"], 2)
        self.assertEqual([s["redirect"] for s in g["per_segment"]],
                         [False, True])
        self.assertEqual(r["mark"]["category"], "Steered")

    def test_single_record_shape_unchanged_counts(self):
        # a normal one-record-per-message transcript: present ==
        # collected, and the count matches the raw census
        segments, meta = sr.parse_session(str(SINGLE_RECORD))
        census = raw_op_census(SINGLE_RECORD)
        self.assertEqual(meta["ops_present_in_transcript"], len(census))
        self.assertEqual(meta["ops_collected"], len(census))
        self.assertGreater(len(census), 0)

    def test_codex_receipts_carry_no_cc_completeness_fields(self):
        # the Codex adapter reports its own channel counters; the
        # Claude Code completeness pair stays absent there
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(str(FIXTURES / "session_codex_synthetic.jsonl"),
                                "cx", recon_dir=Path(tmp) / "recon")
        c = r["mechanistic"]["coverage"]
        self.assertNotIn("ops_present_in_transcript", c)
        self.assertIn("patch_calls", c)


if __name__ == "__main__":
    unittest.main()
