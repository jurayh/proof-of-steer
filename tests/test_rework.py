"""Rework web figure (steering_viz --rework): timeline arc diagram by
default, 3D spiral behind a toggle.

The graph derives only from the shipped tool's own prefix replays, the
same snapshots the artifact replay uses: for each frame transition,
lines of an earlier turn present before the turn but absent after it
become one directed edge from the later turn to the earlier turn,
weighted by the count. These tests pin that derivation on a small
synthetic session, reconcile the shipped flagship figure against the
replay frames and its receipt (the corpus tests skip where the corpus
is absent), and check the emitted page's controls, default view, and
prose hygiene.

Run from release/:  python3 -m unittest discover -s tests -v
"""
import json, re, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import steering_viz
import steering_receipt as sr

CORPUS = (Path.home() / "workspace" / "user" / "corpus" / "public"
          / "trace-commons" / "sessions" / "claude_code")
ICEBERG_SESSION = (CORPUS / "860618e1-0cf6-43c6-81cf-fe67123082ba.jsonl")
ICEBERG_RECEIPT = V1 / "examples" / "code-steered-860618e1.receipt.json"
FIGURE = V1 / "examples" / "rework-web-3d.html"

needs_iceberg = unittest.skipUnless(
    ICEBERG_SESSION.exists() and ICEBERG_RECEIPT.exists(),
    "IceBerg corpus session or receipt absent")


def _rec(type_, text=None, tool=None, ts="2026-10-21T10:00:00Z", mid=None):
    if type_ == "user":
        return {"type": "user", "timestamp": ts,
                "message": {"content": [{"type": "text", "text": text}]}}
    blk = {"type": "tool_use", "name": tool[0], "input": tool[1]}
    if mid:
        blk["id"] = mid
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid or "m", "usage": {"input_tokens": 1,
                                                    "output_tokens": 1},
                        "content": [blk]}}


SYNTHETIC = [
    _rec("user", "Build it"),
    _rec("assistant", tool=("Write", {"file_path": "a.py",
                                      "content": "alpha\nbeta\ngamma\n"}),
         mid="m1"),
    _rec("user", "Just thinking"),
    _rec("user", "Change one line"),
    _rec("assistant", tool=("Edit", {"file_path": "a.py",
                                     "old_string": "beta",
                                     "new_string": "beta2\nbeta3"}),
         mid="m2"),
    _rec("user", "Add another file"),
    _rec("assistant", tool=("Write", {"file_path": "b.py",
                                      "content": "one\ntwo\n"}),
         mid="m3"),
]


def _synthetic_graph():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC),
                     encoding="utf-8")
        return steering_viz.rework_graph(p)


class TestReworkGraph(unittest.TestCase):
    def test_synthetic_edge_semantics(self):
        g = _synthetic_graph()
        self.assertEqual(g["turns"], 4)
        nodes = {n["turn"]: n for n in g["nodes"]}
        # Turn 1 writes 3 lines. Turn 2 is procedural, no change.
        self.assertEqual(nodes[1]["kind"], "first")
        self.assertEqual(nodes[1]["introduced"], 3)
        self.assertEqual(nodes[1]["removed_from_earlier"], 0)
        self.assertEqual(nodes[2]["introduced"], 0)
        # Turn 3 rewrites beta into beta2, beta3: one edge, weight 1.
        self.assertEqual(nodes[3]["kind"], "correction")
        self.assertEqual(nodes[3]["introduced"], 2)
        self.assertEqual(nodes[3]["removed_from_earlier"], 1)
        self.assertEqual(nodes[3]["removed_by_later"], 0)
        self.assertEqual(nodes[3]["surviving"], 2)
        # Turn 1 loses exactly the beta line to turn 3, keeps the rest.
        self.assertEqual(nodes[1]["removed_by_later"], 1)
        self.assertEqual(nodes[1]["surviving"], 2)
        # Turn 4 adds a second file and touches nothing earlier.
        self.assertEqual(nodes[4]["introduced"], 2)
        self.assertEqual(nodes[4]["removed_from_earlier"], 0)
        self.assertEqual(g["edges"], [{"from": 3, "to": 1, "weight": 1,
                                       "span": 2}])
        self.assertEqual(g["total_weight"], 1)
        self.assertEqual(g["final_lines"], 6)

    def test_edges_run_forward_in_time_only(self):
        g = _synthetic_graph()
        for e in g["edges"]:
            self.assertGreater(e["from"], e["to"])
            self.assertEqual(e["span"], e["from"] - e["to"])

    def test_layout_is_deterministic(self):
        g1 = _synthetic_graph()
        g2 = _synthetic_graph()
        self.assertEqual(g1, g2)

    def test_rework_html_controls_and_hygiene(self):
        g = _synthetic_graph()
        html = steering_viz.rework_html(g, {"title": "t",
                                            "subtitle": "s"})
        for token in ('id="web"', 'id="panel"', 'id="reset"',
                      "Drag to orbit", "Reset view"):
            self.assertIn(token, html)
        self.assertNotIn("autoplay", html)
        self.assertNotIn("auto-rotate", html)
        self.assertNotIn("autorotate", html)
        self.assertEqual(len(re.findall(r'https?://|src="|href="', html)), 0)
        # Caption and method prose carry no em-dash and no semicolon.
        for text in (steering_viz.REWORK_CAPTION,
                     steering_viz.REWORK_METHOD):
            self.assertNotIn("\u2014", text)
            self.assertNotIn(";", text)
        # The caption states the edge definition in plain words.
        self.assertIn("removed lines the earlier turn introduced",
                      steering_viz.REWORK_CAPTION)
        self.assertIn("not a claim", steering_viz.REWORK_CAPTION)
        # The page carries the graph data and nothing else from outside.
        m = re.search(r'<script id="rework-data" type="application/json">'
                      r'(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        self.assertEqual(len(data["nodes"]), 4)
        self.assertEqual(len(data["edges"]), 1)

    def test_timeline_is_the_default_view(self):
        g = _synthetic_graph()
        html = steering_viz.rework_html(g, {"title": "t",
                                            "subtitle": "s"})
        # The timeline view is the default on load, the spiral sits
        # behind a toggle, and both views share one detail panel.
        self.assertIn("let view = 'timeline'", html)
        self.assertIn('id="view-timeline"', html)
        self.assertIn('id="view-spiral"', html)
        self.assertIn('class="viewbtn active">Timeline', html)
        self.assertIn("function drawTimeline()", html)
        self.assertIn("function drawSpiral()", html)
        # Timeline arcs come from the same edge list the spiral uses,
        # filtered only when the heavy-edges toggle is on.
        self.assertIn("visibleEdges().forEach", html)
        self.assertIn('id="heavy"', html)
        self.assertIn("Heavy edges only (at least "
                      f"{steering_viz.REWORK_HEAVY_THRESHOLD} lines each)",
                      html)
        # Reading aids: how-to line, size legend entry, callouts.
        self.assertIn("How to read this", html)
        self.assertIn("Bigger node: more lines introduced", html)
        self.assertIn("Look first at turn 3", html)
        # Node order in the embedded data follows turn order.
        m = re.search(r'<script id="rework-data" type="application/json">'
                      r'(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual([n["turn"] for n in data["nodes"]],
                         [1, 2, 3, 4])

    def test_rework_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC),
                         encoding="utf-8")
            out = Path(d) / "rework.html"
            steering_viz.rework_main(["--rework", str(p),
                                      "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn('id="rework-data"', html)
            self.assertEqual(len(re.findall(r'https?://|src="|href="',
                                            html)), 0)


class TestReworkIceBerg(unittest.TestCase):
    @needs_iceberg
    def test_edge_weights_sum_to_replay_discards(self):
        # The total is established from the frames here, not assumed.
        frames, _ = steering_viz.replay_frames(ICEBERG_SESSION)
        dnow_by_frame = [sum(r["dnow"] for r in f["rows"])
                         for f in frames]
        g = steering_viz.rework_graph(ICEBERG_SESSION)
        edge_by_frame = [0] * len(frames)
        for e in g["edges"]:
            edge_by_frame[e["from"]] += e["weight"]
        # Per-transition edge totals match the replay's own discard
        # counts frame by frame, and the sums agree three ways.
        self.assertEqual(edge_by_frame, dnow_by_frame)
        self.assertEqual(g["total_weight"], sum(dnow_by_frame))
        introduced = sum(f["introduced"] for f in frames)
        self.assertEqual(g["total_weight"],
                         introduced - frames[-1]["lines"])
        self.assertEqual(g["turns"], 40)
        self.assertEqual(frames[-1]["lines"], 3102)

    @needs_iceberg
    def test_nodes_reconcile_with_receipt_rows(self):
        g = steering_viz.rework_graph(ICEBERG_SESSION)
        r = json.loads(ICEBERG_RECEIPT.read_text(encoding="utf-8"))
        rows = {row["segment"]: row
                for row in r["git_join"]["per_segment"]
                if row["segment"] >= 0}
        nodes = {n["turn"]: n for n in g["nodes"]}
        self.assertEqual(len(nodes), len(rows))
        for turn, node in nodes.items():
            row = rows[node["segment"]]
            self.assertEqual(node["introduced"],
                             row["lines_introduced_gross"])
            self.assertEqual(node["surviving"],
                             row["lines_surviving_to_head"])

    @needs_iceberg
    def test_shipped_figure_matches_fresh_graph(self):
        self.assertTrue(FIGURE.exists())
        html = FIGURE.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'https?://|src="|href="', html)), 0)
        m = re.search(r'<script id="rework-data" type="application/json">'
                      r'(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1))
        fresh = steering_viz.rework_graph(ICEBERG_SESSION)
        self.assertEqual(data["nodes"], fresh["nodes"])
        self.assertEqual(data["edges"], fresh["edges"])
        # Visible prose carries no em-dash and no semicolon.
        vis = re.sub(r'<script.*?</script>', '', html, flags=re.S)
        vis = re.sub(r'<style.*?</style>', '', vis, flags=re.S)
        vis = re.sub(r'<[^>]+>', ' ', vis)
        self.assertNotIn("\u2014", vis)
        self.assertNotIn(";", vis)

    @needs_iceberg
    def test_shipped_figure_timeline_default_and_callouts(self):
        html = FIGURE.read_text(encoding="utf-8")
        # The timeline view is the default on load.
        self.assertIn("let view = 'timeline'", html)
        self.assertIn('id="view-timeline"', html)
        self.assertIn('id="view-spiral"', html)
        self.assertIn('class="viewbtn active">Timeline', html)
        # The timeline arc count equals the edge count, and node order
        # follows turn order.
        m = re.search(r'<script id="rework-data" type="application/json">'
                      r'(.*?)</script>', html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual([n["turn"] for n in data["nodes"]],
                         list(range(1, 41)))
        self.assertEqual(len(data["edges"]), 41)
        self.assertEqual(sum(e["weight"] for e in data["edges"]), 1256)
        heaviest = max(data["edges"], key=lambda e: e["weight"])
        self.assertEqual((heaviest["from"], heaviest["to"],
                          heaviest["weight"]), (6, 4, 340))
        # The callouts name the heaviest edge and the biggest reworker.
        self.assertIn("Look first at turn 6", html)
        self.assertIn("Turn 14 removed 713", html)
        # The heavy threshold sits in the gap between the small
        # cleanups and the real rewrites, not on a knife edge.
        threshold = steering_viz.REWORK_HEAVY_THRESHOLD
        weights = sorted(e["weight"] for e in data["edges"])
        heavy = [w for w in weights if w >= threshold]
        light = [w for w in weights if w < threshold]
        self.assertEqual(threshold, 50)
        self.assertEqual(len(heavy), 5)
        self.assertEqual(sum(heavy), 1123)
        self.assertLess(max(light), threshold)
        self.assertGreater(min(heavy), threshold)
        self.assertIn("Heavy edges only (at least 50 lines each)", html)


if __name__ == "__main__":
    unittest.main()
