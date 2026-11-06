"""Dual timeline figure (steering_viz --dual-timeline): one shared
turn axis, two lanes. Top lane: the human, one shape-coded mark per
turn (circle first, square follow-up, triangle correction, diamond
after-error), with a decision dot above the turns where the agent
asked a question. Bottom lane: the artifact, lines present after
each turn as a stepped area from the replay frames.

Both lanes derive only from the shipped tool's own prefix replays
and the receipt's own AskUserQuestion parsing, aligned to turns by
the same segmentation. These tests pin that derivation on small
synthetic sessions, reconcile the shipped flagship figure against
the replay frames and its receipt (the corpus tests skip where the
corpus is absent), and check the emitted page's controls and prose
hygiene.

Run from release/:  python3 -m unittest discover -s tests -v
"""
import json, re, sys, tempfile, unittest
from collections import Counter
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(V1))
import steering_viz
import steering_receipt as sr

CORPUS = (Path.home() / "workspace" / "user" / "corpus" / "public"
          / "trace-commons" / "sessions" / "claude_code")
ICEBERG_SESSION = (CORPUS / "860618e1-0cf6-43c6-81cf-fe67123082ba.jsonl")
ICEBERG_RECEIPT = V1 / "examples" / "code-steered-860618e1.receipt.json"
FIGURE = V1 / "examples" / "dual-timeline.html"

needs_iceberg = unittest.skipUnless(
    ICEBERG_SESSION.exists() and ICEBERG_RECEIPT.exists(),
    "IceBerg corpus session or receipt absent")

TS = "2026-10-21T10:00:00Z"


def _rec(type_, text=None, tool=None, mid=None):
    if type_ == "user":
        return {"type": "user", "timestamp": TS,
                "message": {"content": [{"type": "text", "text": text}]}}
    blk = {"type": "tool_use", "name": tool[0], "input": tool[1]}
    if mid:
        blk["id"] = mid
    return {"type": "assistant", "timestamp": TS,
            "message": {"id": mid or "m", "usage": {"input_tokens": 1,
                                                    "output_tokens": 1},
                        "content": [blk]}}


def _ask(mid, question="Which format should the config use?",
         header="Format"):
    return _rec("assistant", tool=("AskUserQuestion", {
        "questions": [{"question": question, "header": header,
                       "multiSelect": False,
                       "options": [{"label": "JSON (Recommended)",
                                    "description": "the JSON option"},
                                   {"label": "YAML",
                                    "description": "the YAML option"}]}]}),
        mid=mid)


def _answer(mid, chosen="JSON (Recommended)"):
    return {"type": "user", "timestamp": TS,
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": mid,
                "content": ("Your questions have been answered: "
                            "\"Which format should the config use?\"=\""
                            + chosen + "\". You can now continue with "
                            "these answers in mind.")}]}}


SYNTHETIC = [
    _rec("user", "Build it"),
    _rec("assistant", tool=("Write", {"file_path": "a.py",
                                      "content": "alpha\nbeta\ngamma\n"}),
         mid="m1"),
    _rec("user", "Add a choice"),
    _ask("toolu_q"),
    _answer("toolu_q"),
    _rec("assistant", tool=("Write", {"file_path": "b.py",
                                      "content": "one\ntwo\n"}),
         mid="m2"),
    _rec("user", "Change one line"),
    _rec("assistant", tool=("Edit", {"file_path": "a.py",
                                     "old_string": "beta",
                                     "new_string": "beta2\nbeta3"}),
         mid="m3"),
]

NO_DECISIONS = [
    _rec("user", "Build it"),
    _rec("assistant", tool=("Write", {"file_path": "a.py",
                                      "content": "alpha\nbeta\ngamma\n"}),
         mid="m1"),
    _rec("user", "Add another file"),
    _rec("assistant", tool=("Write", {"file_path": "b.py",
                                      "content": "one\ntwo\n"}),
         mid="m2"),
]


def _data(records):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in records),
                     encoding="utf-8")
        return steering_viz.dual_timeline_data(p)


def _figure_data(html):
    m = re.search(r'<script id="dual-data" type="application/json">'
                  r'(.*?)</script>', html, re.S)
    assert m is not None
    return json.loads(m.group(1))


class TestDualTimelineSynthetic(unittest.TestCase):
    def test_both_lanes_share_one_turn_axis(self):
        d = _data(SYNTHETIC)
        self.assertEqual(len(d["turns"]), 3)
        xs = [r["x"] for r in d["turns"]]
        self.assertEqual(xs, [steering_viz.dual_x(t, 3) for t in (1, 2, 3)])
        self.assertTrue(all(xs[i] < xs[i + 1] for i in range(2)))
        # The stepped area starts one step before turn 1, at zero lines.
        self.assertAlmostEqual(d["x0"], xs[0] - (xs[1] - xs[0]))

    def test_artifact_series_reconciles(self):
        d = _data(SYNTHETIC)
        rows = {r["turn"]: r for r in d["turns"]}
        self.assertEqual(rows[1]["lines_after"], 3)
        self.assertEqual(rows[1]["files_after"], 1)
        self.assertEqual(rows[2]["lines_after"], 5)
        self.assertEqual(rows[2]["files_after"], 2)
        self.assertEqual(rows[3]["lines_after"], 6)
        self.assertEqual(rows[3]["files_after"], 2)
        self.assertEqual(d["final_lines"], 6)
        self.assertEqual(d["final_files"], 2)
        self.assertEqual(rows[1]["introduced"], 3)
        self.assertEqual(rows[3]["introduced"], 2)
        self.assertEqual(rows[3]["removed"], 1)
        self.assertEqual(rows[1]["removed"], 0)

    def test_decision_marker_lands_on_the_right_turn(self):
        d = _data(SYNTHETIC)
        self.assertEqual(d["total_calls"], 1)
        self.assertEqual(d["total_points"], 1)
        self.assertEqual(d["turns_with_decisions"], [2])
        rows = {r["turn"]: r for r in d["turns"]}
        self.assertEqual(rows[2]["decisions"]["followed"], 1)
        self.assertEqual(rows[2]["decisions"]["points"], 1)
        self.assertEqual(rows[1]["decisions"]["calls"], 0)
        self.assertEqual(rows[3]["decisions"]["calls"], 0)
        # The callout names the turn with the question, computed
        # from the rows, and states the artifact never shrank here.
        self.assertIn("turn 2", d["callout"])
        self.assertIn("never shrank", d["callout"])
        self.assertEqual(d["biggest_drop"]["net"], 1)

    def test_no_decisions_means_no_markers_and_plain_caption(self):
        d = _data(NO_DECISIONS)
        self.assertEqual(d["total_calls"], 0)
        self.assertEqual(d["total_points"], 0)
        self.assertEqual(d["turns_with_decisions"], [])
        self.assertFalse(d["has_decisions"])
        self.assertIn("no questions", d["callout"])
        html = steering_viz.dual_timeline_html(
            d, {"title": "t", "subtitle": "s"})
        self.assertIn("no decision markers", html)
        self.assertNotIn("Decision point (agent asked", html)

    def test_decision_walk_matches_the_receipt_parser(self):
        # The decisions-basic fixture has four calls across three
        # turns: one followed, one diverged (marked), one diverged
        # (unmarked pick), one free text.
        dec = steering_viz.dual_timeline_decisions(
            FIXTURES / "session_decisions_basic.jsonl")
        self.assertEqual(dec["total_calls"], 4)
        self.assertEqual(dec["total_points"], 4)
        self.assertEqual(dec["turns_with_decisions"], [1, 2, 3])
        self.assertEqual(dec["turns"][1]["followed"], 1)
        self.assertEqual(dec["turns"][2]["diverged"], 1)
        self.assertEqual(dec["turns"][3]["diverged"], 1)
        self.assertEqual(dec["turns"][3]["free_text"], 1)

    def test_html_controls_shapes_and_hygiene(self):
        d = _data(SYNTHETIC)
        html = steering_viz.dual_timeline_html(
            d, {"title": "t", "subtitle": "s"})
        for token in ('id="dual"', 'id="panel"', "How to read this",
                      "function drawHuman()", "function drawArtifact()",
                      "function drawShape(", "function showPanel("):
            self.assertIn(token, html)
        # Kind reads by shape as well as colour: all four shapes are
        # drawn, and the legend names each kind with its shape.
        for shape in ("circle", "square", "triangle", "diamond"):
            self.assertIn(f"'{shape}'", html)
        for label in ("First prompt", "Follow-up prompt",
                      "Correction prompt", "Prompt after an error"):
            self.assertIn(label, html)
        self.assertIn("Decision point (agent asked, human answered)", html)
        self.assertNotIn("autoplay", html)
        self.assertEqual(len(re.findall(r'https?://|src="|href="', html)), 0)
        for text in (steering_viz.DUAL_CAPTION,
                     steering_viz.DUAL_CAPTION_NO_DECISIONS,
                     steering_viz.DUAL_METHOD, d["callout"]):
            self.assertNotIn("\u2014", text)
            self.assertNotIn(";", text)
        self.assertIn("do not show who thought of what",
                      steering_viz.DUAL_CAPTION)
        data = _figure_data(html)
        self.assertEqual(len(data["turns"]), 3)
        self.assertEqual([t["turn"] for t in data["turns"]], [1, 2, 3])
        kinds = Counter(t["kind"] for t in data["turns"])
        self.assertEqual([kinds[k] for k in
                          steering_viz.REWORK_LANE_ORDER], [1, 1, 1, 0])

    def test_dual_timeline_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC),
                         encoding="utf-8")
            out = Path(d) / "dual.html"
            steering_viz.dual_timeline_main(
                ["--dual-timeline", str(p), "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn('id="dual-data"', html)
            self.assertEqual(len(re.findall(r'https?://|src="|href="',
                                            html)), 0)


class TestDualTimelineIceBerg(unittest.TestCase):
    @needs_iceberg
    def test_artifact_series_matches_replay_frames(self):
        frames, _ = steering_viz.replay_frames(ICEBERG_SESSION)
        d = steering_viz.dual_timeline_data(ICEBERG_SESSION)
        self.assertEqual(len(d["turns"]), 40)
        self.assertEqual([r["lines_after"] for r in d["turns"]],
                         [f["lines"] for f in frames[1:]])
        self.assertEqual([r["files_after"] for r in d["turns"]],
                         [f["files"] for f in frames[1:]])
        self.assertEqual(d["final_lines"], 3102)
        self.assertEqual(d["final_files"], 28)
        kinds = Counter(r["kind"] for r in d["turns"])
        self.assertEqual([kinds[k] for k in
                          steering_viz.REWORK_LANE_ORDER], [1, 23, 12, 4])

    @needs_iceberg
    def test_decision_markers_match_the_receipt_exactly(self):
        d = steering_viz.dual_timeline_data(ICEBERG_SESSION)
        r = json.loads(ICEBERG_RECEIPT.read_text(encoding="utf-8"))
        dec = r["decisions"]
        self.assertEqual(d["total_points"], dec["decision_points"])
        self.assertEqual(d["total_calls"], 4)
        self.assertEqual(d["turns_with_decisions"], [9, 32, 33, 34])
        rows = {row["turn"]: row for row in d["turns"]}
        self.assertEqual(rows[9]["decisions"]["points"], 2)
        self.assertEqual(rows[9]["decisions"]["diverged"], 2)
        for t in (32, 33, 34):
            self.assertEqual(rows[t]["decisions"]["points"], 1)
            self.assertEqual(rows[t]["decisions"]["diverged"], 1)
        self.assertEqual(sum(row["decisions"]["diverged"]
                             for row in d["turns"]),
                         dec["diverged_to_listed"])
        self.assertEqual(sum(row["decisions"]["followed"]
                             for row in d["turns"]),
                         dec["followed_recommendation"])

    @needs_iceberg
    def test_biggest_drop_is_turn_six(self):
        d = steering_viz.dual_timeline_data(ICEBERG_SESSION)
        self.assertEqual(d["biggest_drop"], {"turn": 6, "net": -40})
        rows = {row["turn"]: row for row in d["turns"]}
        self.assertEqual(rows[6]["kind"], "correction")
        self.assertEqual(rows[6]["removed"], 340)
        self.assertEqual(rows[6]["lines_after"], 977)
        # Turn 14 is the biggest churn turn, not the biggest dip:
        # it introduced 706 while removing 713, a net fall of 7.
        self.assertEqual(rows[14]["removed"], 713)
        self.assertEqual(rows[14]["introduced"], 706)
        self.assertIn("Turn 6 is the biggest dip", d["callout"])
        self.assertIn("turns 9, 32, 33, and 34", d["callout"])

    @needs_iceberg
    def test_shipped_figure_carries_both_lanes(self):
        html = FIGURE.read_text(encoding="utf-8")
        data = _figure_data(html)
        self.assertEqual(len(data["turns"]), 40)
        xs = [t["x"] for t in data["turns"]]
        self.assertTrue(all(xs[i] < xs[i + 1] for i in range(39)))
        self.assertEqual(data["turns"][-1]["lines_after"], 3102)
        self.assertEqual(data["turns"][-1]["files_after"], 28)
        self.assertEqual(data["max_lines"], 3102)
        self.assertEqual(data["ticks"], [0, 1000, 2000, 3000])
        # The same x feeds both lanes: the human marks and the
        # artifact steps read one x per turn.
        self.assertIn("drawShape(D.shapes[t.kind], t.x, TOP_Y, 10)", html)
        self.assertIn("ctx.lineTo(t.x, yLines(prev));", html)
        self.assertIn("ctx.lineTo(t.x, yLines(t.lines_after));", html)
        # The panel data is present for the decision turn and the dip.
        self.assertIn("function showPanel(t)", html)
        self.assertIn("function decisionText(d)", html)


if __name__ == "__main__":
    unittest.main()
