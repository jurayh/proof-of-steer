"""Proof of Steering — decisions adoption suite (stdlib only).

Covers the decisions block (decision-points spike adoption, Oct 2026):
the structured questions the agent asked and the user answered
(AskUserQuestion events) classified by chosen answer, with rejected
calls as their own field and errored / dismissed / input-unparseable /
unparseable coverage always counted.

  - session_decisions_basic.jsonl: one marked followed, one marked
    diverged, one unmarked listed pick, one free-text answer.
  - session_decisions_edges.jsonl: a multi-question call, a
    multi-select pick, a ` user notes:` annotation, a
    ` selected preview:` answer, a rejected call, an errored call.
  - build_decisions unit edges: dismissed calls, unparseable recorded
    input, missing results, double-encoded `questions`, unserialized
    single-question replies.
  - The block never creates segments: fixture turn and segment counts
    are exactly the authored text turns. The demo session and the
    Codex synthetic fixture carry the block as zeros (Codex with the
    interactive-Claude-Code scope label).

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import json, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(V1))
import steering_receipt as sr


def receipt(tmp, fixture):
    return sr.code_receipt(FIXTURES / fixture, fixture,
                           recon_dir=Path(tmp) / "recon")


def counts(d):
    return (d["decision_points"], d["decisions_with_recommendation"],
            d["followed_recommendation"], d["diverged_to_listed"],
            d["free_text_answers"], d["rejected_decision_calls"])


def coverage(d):
    c = d["coverage"]
    return (c["errored_decision_calls"], c["dismissed_decision_calls"],
            c["input_unparseable_decision_calls"], c["unparseable_answers"])


ZERO = (0, 0, 0, 0, 0, 0)


class TestDecisionsBasic(unittest.TestCase):
    def test_classes_and_denominator(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = receipt(tmp, "session_decisions_basic.jsonl")
            d = r["decisions"]
            # A followed (marked), B diverged (marked), C diverged
            # (unmarked listed pick), D free text.
            self.assertEqual(counts(d), (4, 2, 1, 2, 1, 0))
            self.assertEqual(coverage(d), (0, 0, 0, 0))
            self.assertIn("4% of questions in one validated corpus, 40% in "
                          "another", d["scope"])
            self.assertIn("says nothing about steering through ordinary "
                          "turns", d["scope"])

    def test_events_do_not_create_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = receipt(tmp, "session_decisions_basic.jsonl")
            # three authored text turns; the four question calls and
            # their tool-result records add no segments and no turns.
            self.assertEqual(r["mechanistic"]["human_turns"], 3)
            self.assertEqual(
                len([s for s in r["git_join"]["per_segment"] if s["segment"] >= 0]), 3)

    def test_steering_md_renders_decisions_always(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = receipt(tmp, "session_decisions_basic.jsonl")
            md = sr.render_md(r)
            self.assertIn("- Decisions (structured questions the agent asked "
                          "and the user answered): 4 answered questions, of "
                          "which 1 followed the marked recommendation "
                          "(marked on 2 questions)", md)
            self.assertIn("- Decision coverage: 0 errored calls, 0 dismissed "
                          "calls", md)
            self.assertIn("- Decision scope: ", md)


class TestDecisionsEdges(unittest.TestCase):
    def test_edge_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = receipt(tmp, "session_decisions_edges.jsonl")
            d = r["decisions"]
            # multi-question call: followed (marked) + free text;
            # multi-select split pick, user-notes pick, and
            # selected-preview pick all land as listed divergences.
            self.assertEqual(counts(d), (5, 1, 1, 3, 1, 1))
            # one errored call; nothing dismissed, nothing unparseable.
            self.assertEqual(coverage(d), (1, 0, 0, 0))
            self.assertEqual(r["mechanistic"]["human_turns"], 1)
            md = sr.render_md(r)
            self.assertIn("1 question calls were rejected as posed", md)
            self.assertIn("1 errored calls", md)


def question(text, labels, multi=False):
    return {"question": text, "header": "H", "multiSelect": multi,
            "options": [{"label": l, "description": ""} for l in labels]}


class TestBuildDecisionsUnits(unittest.TestCase):
    def test_dismissed_call(self):
        inp = {"questions": [question("Q?", ["A", "B"])]}
        d = sr.build_decisions([(inp, "[user dismissed — no response]", False)])
        self.assertEqual(counts(d), ZERO)
        self.assertEqual(coverage(d), (0, 1, 0, 0))

    def test_input_unparseable(self):
        d = sr.build_decisions([({"no_questions_here": 1}, "anything", False),
                                ("a raw string input", "anything", False)])
        self.assertEqual(counts(d), ZERO)
        self.assertEqual(coverage(d), (0, 0, 2, 0))

    def test_missing_result_counts_unparseable_answers(self):
        inp = {"questions": [question("Q?", ["A", "B"]),
                             question("R?", ["C", "D"])]}
        d = sr.build_decisions([(inp, None, False)])
        self.assertEqual(d["decision_points"], 2)
        self.assertEqual(coverage(d), (0, 0, 0, 2))

    def test_double_encoded_questions_input(self):
        qs = [question("Q?", ["A (Recommended)", "B"])]
        inp = {"questions": json.dumps(qs)}
        res = 'Your questions have been answered: "Q?"="B". You can now continue.'
        d = sr.build_decisions([(inp, res, False)])
        self.assertEqual(counts(d), (1, 1, 0, 1, 0, 0))

    def test_unserialized_single_question_reply(self):
        inp = {"questions": [question("Q?", ["A", "B"])]}
        d = sr.build_decisions([(inp, "Just do the simple thing", False)])
        self.assertEqual(counts(d), (1, 0, 0, 0, 1, 0))

    def test_errored_beats_rejected_wording(self):
        # an errored result is the question never reaching the user,
        # even if its text happens to mention proceeding.
        inp = {"questions": [question("Q?", ["A", "B"])]}
        d = sr.build_decisions(
            [(inp, "The user doesn't want to proceed with this tool use", True)])
        self.assertEqual(counts(d), ZERO)
        self.assertEqual(coverage(d), (1, 0, 0, 0))


class TestDecisionsZeros(unittest.TestCase):
    def test_demo_session_decisions_zero(self):
        import demo as demo_mod
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "demo.jsonl"
            p.write_text(demo_mod.SAMPLE_SESSION_JSONL, encoding="utf-8")
            r = sr.code_receipt(p, "demo-zero", recon_dir=Path(tmp) / "recon")
            self.assertEqual(counts(r["decisions"]), ZERO)
            self.assertEqual(coverage(r["decisions"]), (0, 0, 0, 0))
            self.assertEqual(r["mechanistic"]["human_turns"], 7)

    def test_codex_block_zero_with_scope_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = receipt(tmp, "session_codex_synthetic.jsonl")
            self.assertEqual(r["harness"], "codex")
            d = r["decisions"]
            self.assertEqual(counts(d), ZERO)
            self.assertEqual(coverage(d), (0, 0, 0, 0))
            self.assertIn("interactive Claude Code phenomenon", d["scope"])
            md = sr.render_md(r)
            self.assertIn("0 answered questions", md)


if __name__ == "__main__":
    unittest.main()
