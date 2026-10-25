"""Proof of Steering — capture adoption suite (stdlib only, hermetic).

Covers the capture-time steering records (capture-spike adoption,
Oct 2026): records written as git notes under refs/notes/steer at
commit time, the recorder flow (capture init, checkpoint, attach
with the driver pushing the notes ref only), the receipt's capture
block with its two verification tiers, the notes-only partial
receipt, and the amend behaviour.

The demo session is the live-session fixture throughout: its final
artifact state is committed to a temp repo (one commit, the shape a
real session leaves), and in the per-segment flow each prefix of the
transcript is committed in turn (the spike's shape). The four spike
gates are re-run against the shipped code paths here:

  Gate A  round trip through a bare remote using the driver push,
          plus the user's normal push for the branch: a fresh clone
          reads all seven segments as captured.
  Gate B  one-field tampers are flagged by the right check at the
          right tier: a shifted hunk fails the diff check at the
          commit tier, a rewritten class passes the commit tier and
          fails the transcript tier.
  Gate C  a repo with no notes yields a normal receipt whose
          capture block reads zero captured.
  Gate D  a grep over the stored records finds no prompt text, no
          file content, no assistant prose, and no shell commands
          from the session.

Amend behaviour, as observed on git 2.43 and asserted below: with
the rewrite config capture init writes, amending a commit copies
the note onto the amended commit, but the record inside still names
the pre-amend commit (a stale anchor, flagged by verification), the
old commit keeps its note, and a later attach re-anchors the record
onto the amended commit.

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(V1))
import capture
import demo as demo_mod
import steering_receipt as sr

VOCAB = ("continuation", "procedural", "reshaping", "unmeasured",
         "followed_recommendation", "diverged_to_listed", "free_text",
         "verified against the transcript", "verified against the commit")


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check)


def make_repo(tmp, name="work", bare_origin=False):
    repo = Path(tmp) / name
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    # .steering/ is the tool's own local state (INSTALL.md advises
    # ignoring it); keep it out of the session's commits
    (repo / ".gitignore").write_text(".steering/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "repo setup")
    origin = None
    if bare_origin:
        origin = Path(tmp) / "origin.git"
        subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(origin)],
                       check=True)
        git(repo, "remote", "add", "origin", str(origin))
    return repo, origin


def demo_session(tmp):
    p = Path(tmp) / "session.jsonl"
    p.write_text(demo_mod.SAMPLE_SESSION_JSONL + "\n", encoding="utf-8")
    return p


def write_artifact_state(repo, files):
    for fp, lines in files.items():
        target = Path(repo) / Path(fp).name
        target.write_text("\n".join(l for l, _ in lines) + "\n",
                          encoding="utf-8")


def commit_all(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def captured_demo_repo(tmp):
    """The live-session flow: init, one commit holding the session's
    final artifact state, checkpoint, attach (driver pushes notes)."""
    repo, origin = make_repo(tmp, bare_origin=True)
    session = demo_session(tmp)
    capture.init_repo(repo)
    analysis = capture.build_segment_records(session)
    write_artifact_state(repo, analysis["replay_final"])
    head = commit_all(repo, "session work")
    capture.write_checkpoint(repo, session, session_id="cap-session")
    res = capture.attach_pending(repo, session, session_id="cap-session")
    assert res["status"] == "attached", res
    return repo, origin, session, head, res


class TestInit(unittest.TestCase):
    def test_init_writes_the_documented_setup_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin = make_repo(tmp)
            first = capture.init_repo(repo)
            self.assertEqual(len(first["added"]), 4)
            fetch = git(repo, "config", "--get-all", "remote.origin.fetch").stdout
            push = git(repo, "config", "--get-all", "remote.origin.push").stdout
            rewrite = git(repo, "config", "--get-all", "notes.rewriteRef").stdout
            self.assertIn("+refs/notes/steer:refs/notes/steer", fetch)
            # the spike's trap: the branch refspec is written ALONGSIDE
            # the notes refspec, never the notes refspec alone
            self.assertIn("refs/heads/*:refs/heads/*", push)
            self.assertIn("refs/notes/steer:refs/notes/steer", push)
            self.assertIn("refs/notes/steer", rewrite)
            second = capture.init_repo(repo)
            self.assertEqual(second["added"], [])
            self.assertEqual(len(second["already_present"]), 4)


class TestCheckpoint(unittest.TestCase):
    def test_checkpoint_accumulates_provisional_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin = make_repo(tmp)
            session = demo_session(tmp)
            state = capture.write_checkpoint(repo, session, session_id="live-1")
            self.assertEqual(len(state["segments"]), 7)
            state_file = repo / ".steering" / "capture" / "live-1.json"
            self.assertTrue(state_file.is_file())
            byte_segments, _ = capture.split_transcript(session)
            for entry, bs in zip(state["segments"], byte_segments):
                self.assertEqual(entry["transcript_sha256"], bs["sha256"])
                self.assertEqual(entry["hunks_basis"],
                                 "session replay snapshots (provisional)")
            self.assertEqual([s["impact_class"] for s in state["segments"]],
                             ["continuation", "procedural", "continuation",
                              "reshaping", "continuation", "reshaping",
                              "reshaping"])


class TestRoundTripGateA(unittest.TestCase):
    def test_fresh_clone_reads_captured_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, origin, session, head, res = captured_demo_repo(tmp)
            self.assertEqual(res["attached_turns"], list(range(7)))
            self.assertTrue(res["push"]["attempted"] and res["push"]["ok"])
            announcements = "\n".join(capture.attach_announcements(res))
            self.assertIn("pushed refs/notes/steer:refs/notes/steer", announcements)
            # the user's normal push carries the branch (the driver
            # push moved the notes ref only)
            git(repo, "push", "-q", "origin")
            clone = Path(tmp) / "clone"
            subprocess.run(["git", "clone", "-q", str(origin), str(clone)],
                           check=True)
            self.assertEqual(capture.load_records(clone), {})
            capture.init_repo(clone)
            git(clone, "fetch", "-q", "origin")
            records = capture.load_records(clone)
            self.assertEqual(sorted(records), [head])
            rec = records[head]
            self.assertEqual([s["turn"] for s in rec["segments"]], list(range(7)))
            v = capture.verify_records(clone, session)
            self.assertEqual(v["failed"], 0)
            self.assertEqual(v["tier"], "verified against the transcript")
            v2 = capture.verify_records(clone)
            self.assertEqual(v2["failed"], 0)
            self.assertEqual(v2["tier"], "verified against the commit")
            r = sr.code_receipt(session, "clone", recon_dir=Path(tmp) / "recon",
                                capture_repo=clone)
            cap = r["capture"]
            self.assertEqual(cap["captured_segments"], 7)
            self.assertEqual(cap["inferred_segments"], 0)
            self.assertEqual(cap["unmeasured_segments"], 0)
            self.assertEqual(cap["verification"]["tier"],
                             "verified against the transcript")
            self.assertEqual(r["git_join"]["headline_fields"]
                             ["post_first_prompt_share_pct"], 50.0)
            self.assertTrue(all(row["origin"] == "captured"
                                for row in cap["per_segment"]))


class TestPerSegmentFlow(unittest.TestCase):
    """The spike's shape: one commit per artifact-changing segment,
    records attached prefix by prefix."""

    def build(self, tmp):
        repo, _origin = make_repo(tmp)
        session = demo_session(tmp)
        capture.init_repo(repo)
        byte_segments, preamble = capture.split_transcript(session)
        heads = {}
        for k in range(len(byte_segments)):
            prefix = Path(tmp) / f"prefix-{k}.jsonl"
            prefix.write_bytes(preamble + b"".join(
                s["raw"] for s in byte_segments[: k + 1]))
            analysis = capture.build_segment_records(prefix)
            write_artifact_state(repo, analysis["replay_final"])
            git(repo, "add", "-A")
            dirty = git(repo, "status", "--porcelain").stdout.strip()
            if dirty:
                git(repo, "commit", "-q", "-m", f"segment {k}")
            heads[k] = git(repo, "rev-parse", "HEAD").stdout.strip()
            res = capture.attach_pending(repo, prefix, session_id="perseg",
                                         push=False)
            self.assertEqual(res["attached_turns"], [k], f"prefix {k}: {res}")
        return repo, session, heads

    def test_records_match_commit_diffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, session, heads = self.build(tmp)
            records = capture.load_records(repo)
            claimed = {}
            for sha, rec in records.items():
                for s in rec["segments"]:
                    claimed[s["turn"]] = (sha, s)
            self.assertEqual(sorted(claimed), list(range(7)))
            # the procedural segment merged into the previous commit
            self.assertEqual(claimed[1][0], claimed[0][0])
            # the reshaping edit's recorded hunks equal its commit's
            # diff exactly in this shape
            seg3_commit = claimed[3][0]
            self.assertEqual(claimed[3][1]["hunks"],
                             capture.commit_hunks(repo, seg3_commit))
            v = capture.verify_records(repo, session)
            self.assertEqual(v["failed"], 0)
            self.assertEqual(v["tier"], "verified against the transcript")

    def test_hunk_tamper_fails_the_diff_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, session, heads = self.build(tmp)
            records = capture.load_records(repo)
            target = next(sha for sha, rec in records.items()
                          if any(s["turn"] == 3 for s in rec["segments"]))
            rec = records[target]
            for s in rec["segments"]:
                if s["turn"] == 3:
                    s["hunks"][0]["start"] += 1  # the one-field tamper
            capture.write_note(repo, target, rec)
            v = capture.verify_records(repo, session)
            fails = [c for c in v["checks"] if c["status"] == "fail"]
            self.assertTrue(any(c["check"] == "V3-hunks-vs-diff"
                                and c["segment"] == 3 for c in fails), fails)
            self.assertEqual(v["tier"], "not verified")
            v2 = capture.verify_records(repo)
            self.assertTrue(any(c["check"] == "V3-hunks-vs-diff"
                                for c in v2["checks"]
                                if c["status"] == "fail"))
            self.assertEqual(v2["tier"], "not verified")

    def test_class_tamper_passes_commit_tier_fails_transcript_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, session, heads = self.build(tmp)
            records = capture.load_records(repo)
            target = next(sha for sha, rec in records.items()
                          if any(s["turn"] == 3 for s in rec["segments"]))
            rec = records[target]
            for s in rec["segments"]:
                if s["turn"] == 3:
                    s["impact_class"] = "continuation"  # the class lie
            capture.write_note(repo, target, rec)
            v2 = capture.verify_records(repo)
            self.assertEqual(v2["tier"], "verified against the commit")
            v = capture.verify_records(repo, session)
            self.assertTrue(any(c["check"] == "V4-class-vs-replay"
                                and c["status"] == "fail"
                                for c in v["checks"]))
            # the lie is caught, and the record degrades to the tier
            # whose checks all still pass: the commit tier
            self.assertEqual(v["tier"], "verified against the commit")
            # the receipt's capture block applies the same rule
            r = sr.code_receipt(session, "tampered",
                                recon_dir=Path(tmp) / "recon",
                                capture_repo=repo)
            cap = r["capture"]
            self.assertEqual(cap["captured_segments"], 7)
            self.assertEqual(cap["verification"]["tier"],
                             "verified against the commit")
            self.assertTrue(any(f["check"] == "V4-class-vs-replay"
                                for f in cap["verification"]["failures"]))


class TestDegradationGateC(unittest.TestCase):
    def test_no_notes_reads_zero_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin = make_repo(tmp)
            session = demo_session(tmp)
            capture.init_repo(repo)
            r = sr.code_receipt(session, "plain", recon_dir=Path(tmp) / "recon",
                                capture_repo=repo)
            cap = r["capture"]
            self.assertEqual(cap["captured_segments"], 0)
            self.assertEqual(cap["inferred_segments"], 7)
            self.assertEqual(cap["unmeasured_segments"], 0)
            self.assertEqual(cap["commits_with_records"], 0)
            self.assertEqual(cap["verification"]["tier"], "not verified")
            self.assertIn("0 captured, 7 inferred, 0 unmeasured",
                          sr.render_md(r))
            # and without a capture repo the block is absent entirely
            r2 = sr.code_receipt(session, "plain2",
                                 recon_dir=Path(tmp) / "recon2")
            self.assertNotIn("capture", r2)
            nr, _md = capture.notes_only_receipt(repo, "empty-notes")
            self.assertEqual(nr["capture"]["segments_recorded"], 0)
            self.assertEqual(nr["capture"]["verification_tier"], "not verified")


class TestNotesOnlyReceipt(unittest.TestCase):
    def test_partial_receipt_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin, _session, head, _res = captured_demo_repo(tmp)
            nr, md = capture.notes_only_receipt(repo, "demo-notes")
            self.assertTrue(nr["notes_only"])
            self.assertIsNone(nr["transcript_sha256"])
            self.assertIsNone(nr["mechanistic"])
            self.assertIsNone(nr["git_join"])
            self.assertEqual(nr["unavailable_fields"],
                             ["transcript_sha256", "mechanistic", "git_join"])
            self.assertEqual(nr["capture"]["verification_tier"],
                             "verified against the commit")
            self.assertEqual(nr["capture"]["segments_recorded"], 7)
            self.assertEqual(nr["mark"]["category"], "Closely steered")
            self.assertEqual(nr["mark_scope"],
                             "aggregate over recorded segments only")
            self.assertEqual(len(nr["per_commit"]), 1)
            self.assertEqual(nr["per_commit"][0]["commit"], head)
            self.assertEqual(nr["per_commit"][0]["mark"]["category"],
                             "Closely steered")
            self.assertTrue(md.startswith(
                "# STEERING.md — demo-notes (code, notes-only partial receipt)"))
            self.assertIn("Notes-only partial receipt", md)
            self.assertIn("verified against the commit", md)
            self.assertIn("unavailable, not zero", md)


class TestDecisionsRecordedAsClassesOnly(unittest.TestCase):
    def test_decision_entries_carry_classes_not_answers(self):
        fixture = FIXTURES / "session_decisions_basic.jsonl"
        analysis = capture.build_segment_records(fixture)
        classes = []
        marked = 0
        for r in analysis["records"]:
            for e in r["decisions"]:
                self.assertEqual(e["status"], "answered")
                for q in e["questions"]:
                    classes.append(q["class"])
                    marked += 1 if q["with_recommendation"] else 0
        self.assertEqual(sorted(classes),
                         ["diverged_to_listed", "diverged_to_listed",
                          "followed_recommendation", "free_text"])
        self.assertEqual(marked, 2)
        blob = json.dumps(analysis["records"])
        for secret in ("Which format should the config use?",
                       "Where should the config file live?",
                       "JSON (Recommended)", "Home directory", "Eager", "Lazy"):
            self.assertNotIn(secret, blob)


class TestPrivacyGateD(unittest.TestCase):
    def test_records_hold_no_session_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin, _session, _head, _res = captured_demo_repo(tmp)
            blobs = []
            for sha in capture.list_noted_commits(repo):
                blobs.append(git(repo, "notes", "--ref", "steer",
                                 "show", sha).stdout)
            self.assertEqual(len(blobs), 1)
            blob = blobs[0]
            harvested = set()
            for line in demo_mod.SAMPLE_SESSION_JSONL.splitlines():
                rec = json.loads(line)
                msg = rec.get("message") or {}
                content = msg.get("content")
                blocks = content if isinstance(content, list) else []
                for b in blocks:
                    if b.get("type") == "text":
                        harvested.add(b["text"])
                    elif b.get("type") == "tool_use":
                        inp = b.get("input") or {}
                        for key in ("content", "old_string", "new_string",
                                    "command"):
                            val = inp.get(key)
                            if isinstance(val, str):
                                harvested.update(
                                    l for l in val.split("\n") if len(l) >= 6)
                    elif b.get("type") == "tool_result":
                        c = b.get("content")
                        if isinstance(c, str) and len(c) >= 6:
                            harvested.add(c)
            checked = 0
            for s in sorted(harvested):
                if len(s) < 6 or any(s in w or w in s for w in VOCAB):
                    continue  # record vocabulary is not session text
                checked += 1
                self.assertNotIn(s, blob)
            self.assertGreater(checked, 30)


class TestAmend(unittest.TestCase):
    def _repo_with_record(self, tmp):
        repo, _origin = make_repo(tmp)
        session = demo_session(tmp)
        capture.init_repo(repo)
        analysis = capture.build_segment_records(session)
        write_artifact_state(repo, analysis["replay_final"])
        old_head = commit_all(repo, "session work")
        res = capture.attach_pending(repo, session, session_id="amend",
                                     push=False)
        self.assertEqual(res["status"], "attached")
        self.assertIsNotNone(capture.read_note(repo, old_head))
        return repo, session, old_head

    def test_record_follows_amend_with_a_stale_anchor_then_reanchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, session, old_head = self._repo_with_record(tmp)
            # message-only amend: the note is copied onto the new
            # commit by the rewrite config, the record inside still
            # names the old one, and the old commit keeps its note
            git(repo, "commit", "-q", "--amend", "-m", "session work v2")
            new_head = git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(new_head, old_head)
            copied = capture.read_note(repo, new_head)
            self.assertIsNotNone(copied)
            self.assertEqual(copied["commit"], old_head)  # stale anchor
            self.assertIsNotNone(capture.read_note(repo, old_head))
            v = capture.verify_records(repo)
            self.assertTrue(any(c["check"] == "V1-anchor"
                                and c["status"] == "fail"
                                and c["commit"] == new_head
                                for c in v["checks"]))
            # a later attach re-anchors the copied record
            res2 = capture.attach_pending(repo, session, session_id="amend",
                                          push=False)
            self.assertEqual(res2["reanchored_from"], old_head)
            self.assertEqual(capture.read_note(repo, new_head)["commit"],
                             new_head)
            v2 = capture.verify_records(repo, session)
            self.assertEqual(v2["failed"], 0)
            self.assertEqual(v2["tier"], "verified against the transcript")

    def test_content_amend_leaves_the_record_flagged_by_the_diff_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, session, old_head = self._repo_with_record(tmp)
            # a content amend that moves lines out from under the
            # record: the note follows, the anchor goes stale, and
            # after re-anchoring the diff check flags the hunks whose
            # claimed positions no longer exist in the amended diff,
            # because they describe the pre-amend diff. That is the
            # honest outcome, asserted here rather than smoothed over.
            lines = (repo / "reading_list.py").read_text(
                encoding="utf-8").splitlines()
            (repo / "reading_list.py").write_text(
                "\n".join(lines[5:]) + "\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "--amend", "--no-edit")
            new_head = git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertIsNotNone(capture.read_note(repo, new_head))
            res = capture.attach_pending(repo, session, session_id="amend",
                                         push=False)
            self.assertEqual(res["reanchored_from"], old_head)
            v = capture.verify_records(repo, session)
            self.assertTrue(any(c["check"] == "V3-hunks-vs-diff"
                                and c["status"] == "fail"
                                and c["commit"] == new_head
                                for c in v["checks"]))
            self.assertEqual(v["tier"], "not verified")


class TestPushFailureIsNotFatal(unittest.TestCase):
    def test_broken_origin_reports_and_keeps_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _origin = make_repo(tmp)
            git(repo, "remote", "add", "origin", str(Path(tmp) / "nope.git"))
            session = demo_session(tmp)
            capture.init_repo(repo)
            analysis = capture.build_segment_records(session)
            write_artifact_state(repo, analysis["replay_final"])
            head = commit_all(repo, "session work")
            res = capture.attach_pending(repo, session, session_id="pf")
            self.assertEqual(res["status"], "attached")
            self.assertTrue(res["push"]["attempted"])
            self.assertFalse(res["push"]["ok"])
            announcements = "\n".join(capture.attach_announcements(res))
            self.assertIn("FAILED", announcements)
            self.assertIn("not fatal", announcements)
            self.assertIsNotNone(capture.read_note(repo, head))


class TestCliFlow(unittest.TestCase):
    def test_cli_init_attach_and_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, origin = make_repo(tmp, bare_origin=True)
            session = demo_session(tmp)

            def cli(*args):
                return subprocess.run(
                    [sys.executable, str(V1 / "steering_receipt.py"), *args],
                    capture_output=True, text=True, check=True)
            out = cli("capture", "init", str(repo))
            self.assertIn("refs/notes/steer", out.stdout)
            analysis = capture.build_segment_records(session)
            write_artifact_state(repo, analysis["replay_final"])
            head = commit_all(repo, "session work")
            out = cli("capture", "checkpoint", "--repo", str(repo),
                      "--session", str(session), "--session-id", "cli-1")
            self.assertIn('"segments_accumulated": 7', out.stdout)
            out = cli("capture", "attach", "--repo", str(repo),
                      "--session", str(session), "--session-id", "cli-1")
            self.assertIn("capture: attached steering record for 7 segment(s)",
                          out.stdout)
            self.assertIn("capture: pushed refs/notes/steer:refs/notes/steer "
                          "to origin", out.stdout)
            self.assertIsNotNone(capture.read_note(repo, head))
            out_dir = Path(tmp) / "out"
            out = cli("notes", str(repo), "--label", "cli-notes",
                      "--out", str(out_dir))
            summary = json.loads(out.stdout)
            self.assertEqual(summary["verification_tier"],
                             "verified against the commit")
            nr = json.loads((out_dir / "cli-notes.notes.receipt.json")
                            .read_text(encoding="utf-8"))
            self.assertTrue(nr["notes_only"])
            self.assertTrue((out_dir / "cli-notes.notes.STEERING.md").is_file())
            # code with the repo in play carries the capture block
            out = cli("code", str(session), "--label", "cli-code",
                      "--repo", str(repo), "--out", str(out_dir))
            r = json.loads((out_dir / "cli-code.receipt.json")
                           .read_text(encoding="utf-8"))
            self.assertEqual(r["capture"]["captured_segments"], 7)


class TestDemoUntouched(unittest.TestCase):
    def test_demo_receipt_has_no_capture_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "demo-out"
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                rc = demo_mod.run_demo(out)
            self.assertEqual(rc, 0)
            r = json.loads((out / "demo.receipt.json").read_text(encoding="utf-8"))
            self.assertNotIn("capture", r)


if __name__ == "__main__":
    unittest.main()
