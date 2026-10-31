"""Artifact replay figure (steering_viz --replay).

Frames are the shipped tool's own prefix replays: frame 0 is the state
before the first human turn, frame k is the state after human turn k.
These tests pin the frame semantics on a small synthetic session, the
player controls and caption hygiene of the emitted page, and the
reconciliation of the shipped flagship figure against its receipt
(the corpus test skips where the corpus is absent).

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
FIGURE = V1 / "examples" / "artifact-replay.html"

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


def _synthetic_frames():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC),
                     encoding="utf-8")
        return steering_viz.replay_frames(p)


class TestReplayFrames(unittest.TestCase):
    def test_synthetic_frame_semantics(self):
        frames, meta = _synthetic_frames()
        # Frame 0 empty, then one frame per human turn.
        self.assertEqual(len(frames), 5)
        self.assertEqual(meta["turns"], 4)
        self.assertEqual(frames[0]["lines"], 0)
        self.assertEqual(frames[0]["files"], 0)
        self.assertIsNone(frames[0]["impact"])
        # Turn 1 writes a.py (3 lines); turn 2 is procedural, no change.
        self.assertEqual(frames[1]["impact"], "continuation")
        self.assertEqual(frames[1]["lines"], 3)
        self.assertEqual(frames[2]["impact"], "procedural")
        self.assertEqual(frames[2]["lines"], 3)
        self.assertEqual(frames[2]["rows"][0]["dnow"], 0)
        # Turn 3 rewrites beta into beta2, beta3: 4 lines, beta discarded.
        f3 = frames[3]
        self.assertEqual(f3["impact"], "reshaping")
        self.assertEqual(f3["lines"], 4)
        row = f3["rows"][0]
        self.assertEqual(row["file"], "a.py")
        self.assertEqual(row["present"], 4)
        self.assertEqual(row["comp"], {"continuation": 2, "reshaping": 2})
        self.assertEqual(row["dnow"], 1)
        self.assertEqual(row["dprev"], 0)
        # Turn 4 adds b.py; the discard fades one more frame, then ends.
        f4 = frames[4]
        self.assertEqual(f4["lines"], 6)
        self.assertEqual(f4["files"], 2)
        a4 = [r for r in f4["rows"] if r["file"] == "a.py"][0]
        self.assertEqual((a4["dnow"], a4["dprev"]), (0, 1))
        # Composition sums equal present lines in every row, every frame.
        for f in frames:
            for r in f["rows"]:
                self.assertEqual(sum(r["comp"].values()), r["present"])
        # Files present never decreases on this session (no delete tool).
        counts = [f["files"] for f in frames]
        self.assertEqual(counts, sorted(counts))

    def test_replay_html_controls_and_hygiene(self):
        frames, meta = _synthetic_frames()
        html = steering_viz.replay_html(frames, {**meta, "title": "t",
                                                 "subtitle": "s"})
        for token in ('id="play"', 'id="scrub"', 'id="speed"',
                      "Play", "Pause"):
            self.assertIn(token, html)
        self.assertNotIn("autoplay", html)
        self.assertEqual(len(re.findall(r'https?://|src="', html)), 0)
        # Caption and method prose carry no em-dash and no semicolon.
        for text in (steering_viz.REPLAY_CAPTION,
                     steering_viz.REPLAY_METHOD):
            self.assertNotIn("\u2014", text)
            self.assertNotIn(";", text)

    def test_replay_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in SYNTHETIC),
                         encoding="utf-8")
            out = Path(d) / "replay.html"
            steering_viz.replay_main(["--replay", str(p), "-o", str(out)])
            html = out.read_text(encoding="utf-8")
            self.assertIn('id="play"', html)
            self.assertIn("Artifact replay", html)

    @needs_iceberg
    def test_flagship_figure_reconciles_with_receipt(self):
        frames, meta = steering_viz.replay_frames(ICEBERG_SESSION)
        receipt = json.loads(ICEBERG_RECEIPT.read_text(encoding="utf-8"))
        gj = receipt["git_join"]
        self.assertEqual(len(frames), 41)
        self.assertEqual(meta["turns"], 40)
        self.assertEqual(frames[-1]["lines"],
                         gj["final_nonblank_lines"])
        self.assertEqual(frames[-1]["lines"], 3102)
        self.assertEqual(frames[-1]["files"], gj["files_at_head"])
        self.assertEqual(frames[-1]["files"], 28)
        rec = {s["segment"]: s["impact_class"]
               for s in gj["per_segment"]}
        for f in frames[1:]:
            self.assertEqual(f["impact"], rec[f["segment"]])
        for f in frames:
            for r in f["rows"]:
                self.assertEqual(sum(r["comp"].values()), r["present"])
        if FIGURE.exists():
            html = FIGURE.read_text(encoding="utf-8")
            m = re.search(r'<script id="replay-data" '
                          r'type="application/json">(.*?)</script>',
                          html, re.S)
            shipped = json.loads(m.group(1).replace("\\u003c", "<"))
            self.assertEqual(shipped["frames"][-1]["lines"], 3102)
            self.assertEqual(len(shipped["frames"]), 41)
