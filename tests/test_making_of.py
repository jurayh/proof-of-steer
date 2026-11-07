"""Making-of figure (steering_viz --making-of): a hand-built record
of how the dual timeline was made, in this chat, by one human and
two AIs. It is NOT computed from a transcript. The JSON lists the
steps Levko verified against the side-chat transcript (chat id
d21a060e-2f3f-4fea-9b85-cf241d25e90e): each step cites the message
that records it, and only steps found in the transcript are shown.

These tests pin the shipped JSON (actors, order, times, the two
Yuriy gates, the unfinished final step) and the render (three
lanes, gate diamonds, handoff arrows, the open final node, the
hand-built caption, prose hygiene).

Run from release/:  python3 -m unittest discover -s tests -v
"""
import json, re, sys, tempfile, unittest
from datetime import datetime
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V1))
import steering_viz

DATA = V1 / "examples" / "making-of-dual-timeline.json"
FIGURE = V1 / "examples" / "making-of-dual-timeline.html"


def _visible_text(html):
    text = re.sub(r'<script.*?</script>', '', html, flags=re.S)
    text = re.sub(r'<style.*?</style>', '', text, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'&[a-z#0-9]+;', ' ', text)


class TestMakingOfData(unittest.TestCase):
    def test_shipped_json_shape(self):
        steps = json.loads(DATA.read_text(encoding="utf-8"))
        self.assertEqual(len(steps), 9)
        for s in steps:
            self.assertIn(s["actor"], steering_viz.MAKING_ACTORS)
            self.assertTrue(s["action"])
            self.assertTrue(s["evidence"])
            self.assertIn("gate", s)
            self.assertIn("unfinished", s)
        # Finished steps carry times, in order, inside Nov 5 to 6.
        times = [datetime.fromisoformat(s["time"]) for s in steps
                 if not s["unfinished"]]
        self.assertEqual(len(times), 8)
        self.assertTrue(all(times[i] < times[i + 1]
                            for i in range(len(times) - 1)))
        for t in times:
            self.assertEqual((t.year, t.month), (2026, 11))
            self.assertIn(t.day, (5, 6))

    def test_chain_matches_the_transcript(self):
        steps = json.loads(DATA.read_text(encoding="utf-8"))
        self.assertEqual(steps[0]["actor"], "Yuriy")
        self.assertEqual(steps[0]["time"], "2026-11-05T11:06:39-08:00")
        self.assertEqual(steps[1]["action"], "Picks the dual timeline")
        self.assertEqual(steps[1]["time"], "2026-11-05T11:10:18-08:00")
        self.assertEqual(steps[3]["time"], "2026-11-05T11:12:08-08:00")
        self.assertEqual(steps[4]["time"], "2026-11-05T11:26:02-08:00")
        self.assertIn("134 OK", steps[4]["evidence"])
        self.assertIn("turn 6, net minus 40", steps[4]["evidence"])
        self.assertIn("zero label", steps[4]["evidence"])
        self.assertEqual(steps[6]["time"], "2026-11-05T16:41:38-08:00")
        self.assertEqual(steps[7]["time"], "2026-11-05T16:42:14-08:00")
        self.assertIn("blob SHAs matching", steps[7]["evidence"])

    def test_two_gates_are_yuriy_and_final_step_is_open(self):
        steps = json.loads(DATA.read_text(encoding="utf-8"))
        gates = [s for s in steps if s["gate"]]
        self.assertEqual(len(gates), 2)
        self.assertTrue(all(s["actor"] == "Yuriy" for s in gates))
        self.assertEqual([s["action"] for s in gates],
                         ["Picks the dual timeline", "Approves the push"])
        last = steps[-1]
        self.assertTrue(last["unfinished"])
        self.assertIsNone(last["time"])
        self.assertEqual(last["action"],
                         "Links the figure on the demos page")

    def test_callout_is_computed_from_the_times(self):
        steps = steering_viz.making_of_load(DATA)
        data = steering_viz.making_of_data(steps)
        # Build ran 11:12:08 to 11:26:02, 13 minutes 54 seconds.
        # The push approval came 11:26:57 to 16:41:38, 5 hours.
        self.assertIn("14 minutes", data["callout"])
        self.assertIn("5 hours", data["callout"])
        self.assertIn("still open", data["callout"])


class TestMakingOfRender(unittest.TestCase):
    def test_render_has_three_lanes_gates_and_open_node(self):
        steps = steering_viz.making_of_load(DATA)
        data = steering_viz.making_of_data(steps)
        html = steering_viz.making_of_html(
            data, {"title": "t", "subtitle": "s"})
        for lane in steering_viz.MAKING_LANES:
            self.assertIn(lane, html)
        self.assertIn("function drawLanes()", html)
        self.assertIn("function drawArrow(", html)
        self.assertIn("function drawNode(", html)
        self.assertIn("function showPanel(", html)
        self.assertIn("Approval gate (human)", html)
        self.assertIn("Still open", html)
        self.assertIn("hand-built record of one chat, not a computed "
                      "receipt", html)
        self.assertIn("Each step cites the message that records it",
                      steering_viz.MAKING_CAPTION)
        self.assertEqual(len(re.findall(r'https?://|src="|href="', html)),
                         0)
        text = _visible_text(html)
        self.assertNotIn("\u2014", text)
        self.assertNotIn(";", text)
        payload = json.loads(re.search(
            r'<script id="making-data" type="application/json">(.*?)'
            r'</script>', html, re.S).group(1))
        self.assertEqual(len(payload["steps"]), 9)
        xs = [s["x"] for s in payload["steps"]]
        self.assertTrue(all(xs[i] < xs[i + 1] for i in range(8)))
        lanes = {s["actor"] for s in payload["steps"]}
        self.assertEqual(lanes, set(steering_viz.MAKING_LANES))
        self.assertTrue(payload["steps"][-1]["unfinished"])
        self.assertEqual(
            [s["gate"] for s in payload["steps"]],
            [False, True, False, False, False, False, True, False,
             False])

    def test_shipped_figure_matches_the_json(self):
        html = FIGURE.read_text(encoding="utf-8")
        payload = json.loads(re.search(
            r'<script id="making-data" type="application/json">(.*?)'
            r'</script>', html, re.S).group(1))
        steps = json.loads(DATA.read_text(encoding="utf-8"))
        self.assertEqual(
            [(s["actor"], s["action"]) for s in payload["steps"]],
            [(s["actor"], s["action"]) for s in steps])
        self.assertIn("14 minutes", html)
        self.assertIn("hand-built record", html)
        text = _visible_text(html)
        self.assertNotIn("\u2014", text)
        self.assertNotIn(";", text)

    def test_cli_end_to_end_on_synthetic_data(self):
        synth = [
            {"actor": "Yuriy", "action": "Asks for it",
             "time": "2026-11-06T09:00:00-08:00",
             "evidence": "A message in the chat.", "gate": True,
             "unfinished": False},
            {"actor": "Levko", "action": "Builds it",
             "time": "2026-11-06T09:05:00-08:00",
             "evidence": "A reply in the chat.", "gate": False,
             "unfinished": False},
            {"actor": "Levko", "action": "Ships it",
             "time": None, "evidence": "Not yet.", "gate": False,
             "unfinished": True},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.json"
            p.write_text(json.dumps(synth), encoding="utf-8")
            out = Path(d) / "m.html"
            steering_viz.making_of_main(
                ["--making-of", str(p), "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn('id="making-data"', html)
            self.assertIn("not yet", html)
            self.assertEqual(len(re.findall(r'https?://|src="|href="',
                                            html)), 0)

    def test_loader_rejects_bad_actors_and_undated_steps(self):
        bad_actor = [{"actor": "Ghost", "action": "x",
                      "time": "2026-11-06T09:00:00-08:00",
                      "evidence": "e", "gate": False,
                      "unfinished": False}]
        no_time = [{"actor": "Yuriy", "action": "x", "time": None,
                    "evidence": "e", "gate": False, "unfinished": False}]
        with tempfile.TemporaryDirectory() as d:
            for name, rows in (("a.json", bad_actor),
                               ("b.json", no_time)):
                p = Path(d) / name
                p.write_text(json.dumps(rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    steering_viz.making_of_load(p)


if __name__ == "__main__":
    unittest.main()
