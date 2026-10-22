"""Proof of Steering v1 — unittest suite (stdlib only).

Covers: injected-record filtering, message-id dedupe, segment attribution,
repo-seeded edit application (the v1 hardening), doc per-section map,
CLI help, and the no-raw-prompt-text guarantee.

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(V1))
import steering_receipt as sr

def rec_user_text(text, ts="2026-10-21T10:00:00Z", **kw):
    r = {"type": "user", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}
    r.update(kw); return r

def rec_assistant(mid, blocks, usage=None, ts="2026-10-21T10:00:10Z"):
    m = {"id": mid, "content": blocks}
    if usage: m["usage"] = usage
    return {"type": "assistant", "timestamp": ts, "message": m}

def rec_tool_result(is_error=False, ts="2026-10-21T10:00:15Z"):
    return {"type": "user", "timestamp": ts,
            "message": {"content": [{"type": "tool_result", "is_error": is_error, "content": "x"}]}}

def write_session(tmp, records, name="session.jsonl"):
    p = Path(tmp) / name
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return p

def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)

def init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], capture_output=True, check=True)
    git(path, "config", "user.email", "test@local"); git(path, "config", "user.name", "test")
    return path

class TestInjectedFiltering(unittest.TestCase):
    def test_injected_user_records_are_not_human_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_session(tmp, [
                rec_user_text("build the widget"),
                rec_user_text("hook output that is not a human", isMeta=True),
                rec_user_text("<command-name>/clear</command-name>"),
                rec_user_text("Caveat: local command output follows"),
                rec_assistant("m1", []),
            ])
            segments, meta = sr.parse_session(p)
            genuine = [s for s in segments if not s.get("pre_prompt")]
            self.assertEqual(len(genuine), 1)
            self.assertEqual(genuine[0]["prompt_chars"], len("build the widget"))
            self.assertEqual(meta["injected_filtered"], 3)

class TestMessageIdDedupe(unittest.TestCase):
    def test_duplicate_assistant_records_counted_once(self):
        blocks = [{"type": "tool_use", "name": "Write",
                   "input": {"file_path": "a.txt", "content": "x\n"}}]
        with tempfile.TemporaryDirectory() as tmp:
            p = write_session(tmp, [
                rec_user_text("go"),
                rec_assistant("dup-id", blocks, usage={"input_tokens": 50, "output_tokens": 10}),
                rec_assistant("dup-id", blocks, usage={"input_tokens": 50, "output_tokens": 10}),
            ])
            segments, meta = sr.parse_session(p)
            self.assertEqual(meta["tokens_in"], 50)
            self.assertEqual(meta["tokens_out"], 10)
            self.assertEqual(len(segments[0]["ops"]), 1)

class TestSegmentAttribution(unittest.TestCase):
    def test_two_segment_session_attribution_and_no_prompt_text(self):
        records = [
            rec_user_text("build the thing"),
            rec_assistant("m1", [{"type": "tool_use", "name": "Write",
                                  "input": {"file_path": "a.txt", "content": "l1\nl2\nl3\nl4\n"}}]),
            rec_tool_result(),
            rec_user_text("fix the second line please"),
            rec_assistant("m2", [{"type": "tool_use", "name": "Edit",
                                  "input": {"file_path": "a.txt", "old_string": "l2", "new_string": "l2-fixed"}}]),
            rec_tool_result(),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            p = write_session(tmp, records)
            r = sr.code_receipt(p, "test-attr", recon_dir=Path(tmp) / "recon")
            self.assertEqual(r["schema"], "proof-of-steering/receipt@1.0")
            self.assertEqual(r["harness"], "claude-code")
            self.assertIn("SWE-chat", r["validation_scope"])
            self.assertIn("partial pass", r["validation_scope"])
            self.assertIn("CoAuthor", r["validation_scope"])
            self.assertIn("floor on the untouched share", r["validation_scope"])
            self.assertIn("no rejection evidence", r["validation_scope"])
            m, g = r["mechanistic"], r["git_join"]
            self.assertEqual(m["human_turns"], 2)
            self.assertEqual(g["final_nonblank_lines"], 4)
            self.assertEqual(g["headline_fields"]["post_first_prompt_share_pct"], 25.0)
            self.assertEqual(g["supporting_fields"]["correction_segment_share_pct"], 25.0)
            self.assertEqual(g["context_fields"]["first_segment_survival_pct"], 75.0)
            self.assertEqual(g["blame_vs_memory_provenance_agreement_pct"], 100.0)
            surv = {s["segment"]: s["lines_surviving_to_head"] for s in g["per_segment"]}
            self.assertEqual(surv, {0: 3, 1: 1})
            self.assertEqual(m["coverage"]["edits_applied_on_transcript_base"], 1)
            # receipts never carry raw prompt text
            self.assertNotIn("fix the second line please", json.dumps(r))
            self.assertNotIn("build the thing", json.dumps(r))

class TestRepoSeeding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pos-v1-test-")
        self.repo = init_repo(Path(self.tmp) / "seed_repo")
        shutil.copytree(FIXTURES / "seed_repo", self.repo, dirs_exist_ok=True)
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "pre-existing")
        self.session = FIXTURES / "session_edit_existing.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_without_repo_edit_is_no_base(self):
        r = sr.code_receipt(self.session, "t-plain", recon_dir=Path(self.tmp) / "r0")
        c = r["mechanistic"]["coverage"]
        self.assertEqual(c["edits_total"], 1)
        self.assertEqual(c["edits_unapplied_no_base"], 1)
        self.assertEqual(c["edits_applied_on_repo_seeded_base"], 0)
        self.assertEqual(c["files_seeded_from_repo"], 0)
        self.assertFalse(c["repo_supplied"])
        self.assertIsNone(c["seed_source"])

    def test_with_repo_edit_applies_on_seeded_base(self):
        r = sr.code_receipt(self.session, "t-seeded", repo_dir=self.repo,
                            recon_dir=Path(self.tmp) / "r1")
        c = r["mechanistic"]["coverage"]
        self.assertEqual(c["edits_applied_on_repo_seeded_base"], 1)
        self.assertEqual(c["edits_unapplied_no_base"], 0)
        self.assertEqual(c["files_seeded_from_repo"], 1)
        self.assertTrue(c["repo_supplied"])
        self.assertEqual(c["seed_source"], "working-tree")
        g = r["git_join"]
        # seeded app.py: 7 non-blank lines, the edited return line replaced ->
        # 6 pre-existing lines survive of 7 at HEAD
        self.assertEqual(g["final_nonblank_lines"], 7)
        self.assertEqual(g["headline_fields"]["preexisting_share_pct"], 85.7)
        self.assertEqual(g["blame_vs_memory_provenance_agreement_pct"], 100.0)
        per_seg = {s["segment"]: s for s in g["per_segment"]}
        self.assertIn(-1, per_seg)
        self.assertEqual(per_seg[-1]["lines_surviving_to_head"], 6)
        head_text = (Path(self.tmp) / "r1" / "proj" / "demo" / "src" / "app.py")
        if not head_text.exists():  # norm path layout fallback: find it
            head_text = next((Path(self.tmp) / "r1").rglob("app.py"))
        self.assertIn("hello there, ", head_text.read_text(encoding="utf-8"))

class TestRepoRef(unittest.TestCase):
    """--repo-ref seeds from git show REF:<path>, not the working tree.

    Fixture repo: mod.py is committed with a "committed line"; the working
    tree then changes it to a "working line" (uncommitted). The session
    makes two edits, one targeting each base. Which edit applies — and
    what the reconstructed HEAD contains — must flip with the seed source.
    """
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pos-v11-test-")
        self.repo = init_repo(Path(self.tmp) / "ref_repo")
        target = self.repo / "mod.py"
        target.write_text("top\ncommitted line\nshared\n", encoding="utf-8")
        git(self.repo, "add", "-A"); git(self.repo, "commit", "-q", "-m", "base")
        target.write_text("top\nworking line\nshared\n", encoding="utf-8")
        records = [
            rec_user_text("tweak both lines"),
            rec_assistant("m1", [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "mod.py", "old_string": "working line",
                           "new_string": "working line edited"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "mod.py", "old_string": "committed line",
                           "new_string": "committed line edited"}},
            ]),
            rec_tool_result(),
        ]
        self.session = write_session(self.tmp, records)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_working_tree_seed_uses_working_tree(self):
        r = sr.code_receipt(self.session, "t-wt", repo_dir=self.repo,
                            recon_dir=Path(self.tmp) / "wt")
        c = r["mechanistic"]["coverage"]
        self.assertEqual(c["seed_source"], "working-tree")
        self.assertEqual(c["edits_applied_on_repo_seeded_base"], 1)
        self.assertEqual(c["edits_unapplied_no_match"], 1)
        head = (Path(self.tmp) / "wt" / "mod.py").read_text(encoding="utf-8")
        self.assertIn("working line edited", head)
        self.assertNotIn("committed line edited", head)

    def test_repo_ref_seed_uses_committed_content(self):
        r = sr.code_receipt(self.session, "t-ref", repo_dir=self.repo, repo_ref="HEAD",
                            recon_dir=Path(self.tmp) / "ref")
        c = r["mechanistic"]["coverage"]
        self.assertEqual(c["seed_source"], "ref:HEAD")
        self.assertEqual(c["edits_applied_on_repo_seeded_base"], 1)
        self.assertEqual(c["edits_unapplied_no_match"], 1)
        head = (Path(self.tmp) / "ref" / "mod.py").read_text(encoding="utf-8")
        self.assertIn("committed line edited", head)
        self.assertNotIn("working line edited", head)

class TestDocSections(unittest.TestCase):
    def test_per_section_map_on_synthetic_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "docs")
            doc = repo / "doc.md"
            doc.write_text("# Title\n\n## Alpha\nalpha one\nalpha two\n\n## Beta\nbeta one\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v1")
            doc.write_text("# Title\n\n## Alpha\nalpha one\nalpha two\n\n## Beta\nbeta one revised\n\n## Gamma\ngamma one\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v2")
            r = sr.doc_receipt(repo, "doc.md", "t-doc")
            self.assertEqual(r["schema"], "proof-of-steering/receipt@1.0")
            self.assertEqual(r["harness"], "git")
            self.assertEqual(r["revisions"], 2)
            self.assertEqual(r["final_nonblank_lines"], 8)
            self.assertEqual(r["overall_pct_unchanged_from_first_version"], 62.5)
            secs = {s["section"]: s for s in r["per_section"]}
            self.assertEqual(secs["Alpha"]["pct_unchanged_from_first_version"], 100.0)
            self.assertEqual(secs["Beta"]["pct_unchanged_from_first_version"], 50.0)
            self.assertEqual(secs["Gamma"]["pct_unchanged_from_first_version"], 0.0)
            self.assertEqual(secs["Gamma"]["pct_introduced_after_first_version"], 100.0)
            gamma_intro = secs["Gamma"]["introduced_by_revision"]
            self.assertEqual(list(gamma_intro.values()), [2])
            self.assertIn("rev2", next(iter(gamma_intro)))

class TestDocSentenceShare(unittest.TestCase):
    """v1.2: sentence-granularity share, revision_count, floor phrasing.

    Fixture: v2 appends one sentence ("Delta is new.") to the Gamma line.
    Line-based: that whole line counts as rewritten -> 3 of 4 final
    non-blank lines unchanged = 75.0%. Sentence-based: final sentences are
    ["# Guide", "## Notes", "Alpha opens here.", "Beta follows it.",
    "Gamma closes the section.", "Delta is new."]; all but the last appear
    verbatim in v1 -> 5/6 = 83.3%. The gap between the two numbers is the
    paragraph-line collateral error the CoAuthor run measured.
    """
    def test_sentence_share_revision_count_and_floor_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "prose")
            doc = repo / "doc.md"
            doc.write_text("# Guide\n\n## Notes\nAlpha opens here. Beta follows it.\nGamma closes the section.\n",
                           encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v1")
            doc.write_text("# Guide\n\n## Notes\nAlpha opens here. Beta follows it.\nGamma closes the section. Delta is new.\n",
                           encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v2")
            r = sr.doc_receipt(repo, "doc.md", "t-prose")
            self.assertEqual(r["revisions"], 2)
            self.assertEqual(r["revision_count"], 2)
            self.assertEqual(r["final_nonblank_lines"], 4)
            self.assertEqual(r["overall_pct_unchanged_from_first_version"], 75.0)
            self.assertEqual(r["unchanged_sentence_share_pct"], 83.3)
            self.assertIn("CoAuthor", r["validation_scope"])
            md = sr.render_md(r)
            self.assertIn("at least 75.0%", md)
            self.assertIn("a floor", md)
            self.assertIn("computed over 2 revisions", md)
            self.assertIn("83.3%", md)

class TestCodexAdapter(unittest.TestCase):
    """v1.3: Codex rollout adapter (fixture session_codex_synthetic.jsonl).

    Hand-computed fixture: seg0 adds a.txt (alpha,beta,gamma) via an
    absolute /workspace path + b.txt (one,two) via a relative path; seg1
    ("fix beta and drop b") patches beta->BETA, has one patch FAIL
    verification (its ops must be dropped whole), writes c.txt
    (hello,world) through a heredoc exec (extracted), runs one sed -i
    (counted unparsed, never guessed), deletes b.txt, and runs pytest.
    HEAD must be a.txt(alpha,BETA,gamma) + c.txt(hello,world): origins
    seg0 {alpha,gamma} = 2, seg1 {BETA,hello,world} = 3.
    """
    def setUp(self):
        self.session = FIXTURES / "session_codex_synthetic.jsonl"

    def test_detect_format(self):
        self.assertEqual(sr.detect_format(self.session), "codex")
        self.assertEqual(sr.detect_format(FIXTURES / "session_edit_existing.jsonl"), "claude-code")

    def test_shell_classification(self):
        self.assertEqual(sr.classify_shell("cat > x.txt <<'EOF'\na\nEOF", "/workspace"),
                         ("op", ("write", "x.txt", "a")))
        self.assertEqual(sr.classify_shell("cat >> x.txt <<'EOF'\na\nEOF", "/workspace"), "unparsed")
        self.assertEqual(sr.classify_shell("sed -i 's/a/b/' x.txt", "/workspace"), "unparsed")
        self.assertEqual(sr.classify_shell("rm x.txt", "/workspace"),
                         ("op", ("delete", "x.txt")))
        self.assertEqual(sr.classify_shell("rm -rf build", "/workspace"), "unparsed")
        self.assertIsNone(sr.classify_shell("python gen.py", "/workspace"))
        self.assertIsNone(sr.classify_shell("ls -la", "/workspace"))
        self.assertIsNone(sr.classify_shell("rg pattern > /dev/null", "/workspace"))

    def test_codex_receipt_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(self.session, "t-codex", recon_dir=Path(tmp) / "recon")
            self.assertEqual(r["schema"], "proof-of-steering/receipt@1.0")
            self.assertEqual(r["harness"], "codex")
            m, g = r["mechanistic"], r["git_join"]
            # segments come from user_message events only: the developer
            # record, the <environment_context> wrapper (counted as the 1
            # injected record) and the second-channel duplicate of the
            # first prompt are not turns.
            self.assertEqual(m["human_turns"], 2)
            self.assertEqual(m["injected_user_records_filtered"], 1)
            self.assertEqual(m["tokens_in_deduped"], 3000)   # last cumulative token_count
            self.assertEqual(m["tokens_out_deduped"], 500)
            self.assertEqual(g["files_at_head"], 2)
            self.assertEqual(g["final_nonblank_lines"], 5)
            self.assertEqual(g["headline_fields"]["post_first_prompt_share_pct"], 60.0)
            self.assertEqual(g["context_fields"]["first_segment_survival_pct"], 40.0)
            self.assertEqual(g["supporting_fields"]["correction_segment_share_pct"], 60.0)
            self.assertEqual(g["blame_vs_memory_provenance_agreement_pct"], 100.0)
            surv = {s["segment"]: s["lines_surviving_to_head"] for s in g["per_segment"]}
            self.assertEqual(surv, {0: 2, 1: 3})
            ops = {s["segment"]: s["edit_write_ops"] for s in g["per_segment"]}
            self.assertEqual(ops, {0: 2, 1: 3})  # failed patch contributes no ops
            self.assertEqual(m["edit_write_ops"], 5)
            self.assertEqual(m["verification_lanes"]["shell_total"], 4)
            self.assertEqual(m["verification_lanes"]["test_like_shell"], 1)
            c = m["coverage"]
            self.assertEqual(c["writes"], 3)
            self.assertEqual(c["edits_total"], 1)
            self.assertEqual(c["edits_applied_on_transcript_base"], 1)
            self.assertEqual(c["patch_calls"], 4)
            self.assertEqual(c["patch_calls_failed"], 1)
            self.assertEqual(c["patch_calls_unresolved"], 0)
            self.assertEqual(c["patch_file_ops_parsed"], 4)
            self.assertEqual(c["patch_file_ops_failed"], 1)
            self.assertEqual(c["patch_hunks_parsed"], 1)
            self.assertEqual(c["patch_hunks_unparsed"], 0)
            self.assertEqual(c["shell_writes_extracted"], 1)
            self.assertEqual(c["shell_writes_unparsed"], 1)
            # the absolute and relative spellings of a.txt joined as one file
            files = {f["file"] for f in g["per_file"]}
            self.assertEqual(files, {"a.txt", "c.txt"})
            md = sr.render_md(r)
            self.assertIn("Codex channels: 4 apply_patch calls (1 failed", md)
            self.assertNotIn("build the thing", json.dumps(r))
            self.assertNotIn("fix beta and drop b", json.dumps(r))

class TestCLI(unittest.TestCase):
    def test_help_and_doc_subcommand(self):
        h = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(h.returncode, 0)
        self.assertIn("code", h.stdout); self.assertIn("doc", h.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "docs")
            (repo / "d.md").write_text("# T\n\nhello\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v1")
            out = Path(tmp) / "out"
            run = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"),
                                  "doc", str(repo), "d.md", "--label", "cli-doc", "--out", str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            receipt = json.loads((out / "cli-doc.receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["schema"], "proof-of-steering/receipt@1.0")
            self.assertEqual(receipt["harness"], "git")
            self.assertTrue((out / "cli-doc.STEERING.md").exists())

if __name__ == "__main__":
    unittest.main()
