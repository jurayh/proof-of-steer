"""Proof of Steering v1.4 — adoption build suite (stdlib only).

Covers the five v1.4 components:
  1. Providers in v1 (doc mode): fixture validation ported from the
     gdocs spike (the same 89 ground-truth checks, run against v1's
     provider package and join), findings-draft parity through the
     provider path, the folder provider demo number (58.3%).
  2. Heading-less sectioning: the s6 (heading-less export) and s7
     (unstructured prose) fixtures, the heuristic's behaviour on the
     real findings draft with markers stripped, strategy resolution.
  3. Impact fields: IceBerg's split matches the impact spike exactly;
     the one-prompt control's reshaping is exactly 0; Codex spot checks
     against shipped v1.3 receipts and spike classes.
  4. The steering mark: boundary sessions for every category, both
     modes; the viz badge.
  5. Hash commitment: the spec's verification procedure end to end
     (round trip), plus the tamper negative.

Run from v1/:  python3 -m unittest discover -s tests -v
"""
import hashlib, json, shutil, subprocess, sys, tempfile, unittest
import xml.etree.ElementTree as ET
from pathlib import Path

V1 = Path(__file__).resolve().parent.parent
ROOT = V1.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The gdocs spike fixtures and the extensibility folder demo are vendored
# into this repo (tests/fixtures/spike, tests/fixtures/demo_data) so the
# shipped suite is hermetic; the vendored copies are canonical here.
SPIKE_FIXTURES = FIXTURES / "spike"
DEMO_DATA = FIXTURES / "demo_data"
DEMO_RECEIPT = FIXTURES / "demo-folder.receipt.json"
# Inherently workspace-bound material (private or too large to vendor):
# the tests that need it skip cleanly when it is absent.
PG_REPO = Path.home() / "workspace" / "personal-guard"
IMPACT_RESULTS = ROOT / "impact-spike" / "results.json"
RECEIPTS_CODEX = ROOT / "receipts-codex"
needs_pg = unittest.skipUnless(PG_REPO.exists(),
                               "personal-guard workspace repo not present")
sys.path.insert(0, str(V1))
sys.path.insert(0, str(SPIKE_FIXTURES))
import steering_receipt as sr
from doc_join import doc_join, resolve_sections
from providers import ArtifactRef, get_provider
from providers.gdrive_doc import GDriveDocProvider
from fake_drive import FakeDriveTransport

def rec_user_text(text, ts="2026-10-21T10:00:00Z", **kw):
    r = {"type": "user", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}
    r.update(kw); return r

def rec_assistant(mid, blocks, ts="2026-10-21T10:00:10Z"):
    return {"type": "assistant", "timestamp": ts, "message": {"id": mid, "content": blocks}}

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

def tu(name, inp):
    return {"type": "tool_use", "name": name, "input": inp}

# ================================================================ component 1+2: providers and fixtures
class Checks:
    def __init__(self):
        self.results = []
    def eq(self, name, got, want):
        self.results.append((name, got == want, f"got {got!r} want {want!r}"))
    def true(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
    @property
    def passed(self): return sum(1 for _, ok, _ in self.results if ok)
    @property
    def ok(self): return all(ok for _, ok, _ in self.results)

def run_fixture_pipeline(scenario, section_strategy="auto"):
    """v1 provider -> snapshots -> v1 join, exactly the spike's shape."""
    sdir = SPIKE_FIXTURES / scenario
    transport = FakeDriveTransport(sdir)
    provider = GDriveDocProvider(transport=transport)
    ref = ArtifactRef("gdrive-doc", transport.file_meta["id"])
    meta = provider.describe(ref)
    snaps = provider.snapshots(ref)
    versions = [(s.id, s.content()) for s in snaps]
    receipt = None
    if versions:
        receipt = doc_join(versions, label=f"fixture-{scenario}",
                           source=f"gdrive-fixture :: {meta.title}",
                           provider="gdrive-doc",
                           history_complete=meta.history_complete,
                           section_strategy=section_strategy,
                           authors=[s.author for s in snaps])
    return transport, meta, snaps, receipt

ALEX = "Alex Rivers"

def common(c, meta, snaps, receipt, *, title, ids, authors, history_complete):
    c.eq("describe title", meta.title, title)
    c.eq("history_complete (describe)", meta.history_complete, history_complete)
    c.eq("snapshot ids in order", [s.id for s in snaps], ids)
    c.eq("snapshot authors", [s.author for s in snaps], authors)
    ts = [s.timestamp for s in snaps]
    c.true("snapshot timestamps ascending", ts == sorted(ts), str(ts))
    if receipt is not None:
        c.eq("receipt provider", receipt["provider"], "gdrive-doc")
        c.eq("receipt revisions", receipt["revisions"], len(ids))
        c.eq("receipt revision_shas", receipt["revision_shas"], ids)
        c.eq("receipt history_complete", receipt["history_complete"], history_complete)
        c.eq("receipt authors (coverage)", receipt.get("authors"),
             list(dict.fromkeys(a for a in authors if a)))

def sections_of(receipt):
    return [(s["section"], s["pct_unchanged_from_first_version"]) for s in receipt["per_section"]]

class TestFixtureValidationPort(unittest.TestCase):
    """The gdocs spike's 89 ground-truth checks, against v1's code."""

    def collect(self):
        all_checks = []
        # S1 clean growth
        c = Checks(); _, meta, snaps, r = run_fixture_pipeline("s1-clean-growth")
        common(c, meta, snaps, r, title="Harbour and Garden Plan (fixture)",
               ids=[f"s1-r{i}" for i in range(1, 6)], authors=[ALEX] * 5, history_complete=False)
        c.eq("per-section pct", sections_of(r), [("Harbour Plan", 20.0), ("Garden Notes", 60.0), ("Budget Sketch", 0.0)])
        c.eq("overall pct", r["overall_pct_unchanged_from_first_version"], 28.6)
        c.eq("sentence share", r["unchanged_sentence_share_pct"], 28.6)
        c.eq("final nonblank lines", r["final_nonblank_lines"], 14)
        by = {s["section"]: s for s in r["per_section"]}
        c.eq("Harbour intro", by["Harbour Plan"]["introduced_by_revision"], {"rev1 (s1-r1)": 1, "rev3 (s1-r3)": 4})
        c.eq("Garden intro", by["Garden Notes"]["introduced_by_revision"], {"rev1 (s1-r1)": 3, "rev2 (s1-r2)": 1, "rev5 (s1-r5)": 1})
        c.eq("Budget intro", by["Budget Sketch"]["introduced_by_revision"], {"rev4 (s1-r4)": 4})
        t1 = run_fixture_pipeline("s1-clean-growth")[0]
        lists = [q for q in t1.requests if q[0] == "revisions.list"]
        c.eq("revisions.list calls (single page)", len(lists), 1)
        all_checks += c.results
        # S2 truncated
        c = Checks(); _, meta, snaps, r = run_fixture_pipeline("s2-truncated")
        common(c, meta, snaps, r, title="Status Notes (fixture, truncated history)",
               ids=["s2-r3", "s2-r4", "s2-r5"], authors=[ALEX] * 3, history_complete=False)
        c.eq("baseline is first available revision", r["revision_shas"][0], "s2-r3")
        c.eq("per-section pct", sections_of(r), [("Status Notes", 60.0)])
        c.eq("overall pct", r["overall_pct_unchanged_from_first_version"], 60.0)
        c.eq("sentence share", r["unchanged_sentence_share_pct"], 60.0)
        all_checks += c.results
        # S3 multi-author
        c = Checks(); _, meta, snaps, r = run_fixture_pipeline("s3-multi-author")
        authors = ["Mina Park", "Jonas Feld", "Mina Park", "Jonas Feld"]
        common(c, meta, snaps, r, title="Field Log (fixture, two authors)",
               ids=[f"s3-r{i}" for i in range(1, 5)], authors=authors, history_complete=False)
        c.eq("receipt authors distinct", r.get("authors"), ["Mina Park", "Jonas Feld"])
        c.eq("per-section pct", sections_of(r), [("Field Log", 50.0)])
        c.eq("overall pct", r["overall_pct_unchanged_from_first_version"], 50.0)
        all_checks += c.results
        # S4 pagination
        c = Checks(); transport, meta, snaps, r = run_fixture_pipeline("s4-pagination")
        common(c, meta, snaps, r, title="Running Log (fixture, paginated)",
               ids=[f"s4-r{k:02d}" for k in range(1, 26)], authors=[ALEX] * 25, history_complete=False)
        lists = [q for q in transport.requests if q[0] == "revisions.list"]
        c.eq("revisions.list calls", len(lists), 3)
        c.eq("page tokens presented", [t for _, t in lists], [None, "fixture-token-page-2", "fixture-token-page-3"])
        gets = [q for q in transport.requests if q[0] == "revisions.get"]
        c.eq("revisions.get calls", len(gets), 25)
        c.eq("per-section pct", sections_of(r), [("Running Log", 7.7)])
        c.eq("overall pct", r["overall_pct_unchanged_from_first_version"], 7.7)
        c.eq("final nonblank lines", r["final_nonblank_lines"], 26)
        all_checks += c.results
        # S5 single
        c = Checks(); _, meta, snaps, r = run_fixture_pipeline("s5-single")
        common(c, meta, snaps, r, title="Solo Draft (fixture, one revision)",
               ids=["s5a-r1"], authors=[ALEX], history_complete=False)
        c.eq("per-section pct", sections_of(r), [("Solo Draft", 100.0)])
        c.eq("overall pct", r["overall_pct_unchanged_from_first_version"], 100.0)
        all_checks += c.results
        # S5 empty
        c = Checks(); _, meta, snaps, r = run_fixture_pipeline("s5-empty")
        common(c, meta, snaps, r, title="Empty Export (fixture)",
               ids=["s5b-r1"], authors=[ALEX], history_complete=False)
        c.eq("final nonblank lines", r["final_nonblank_lines"], 0)
        c.eq("per-section empty", r["per_section"], [])
        c.eq("overall pct is null", r["overall_pct_unchanged_from_first_version"], None)
        c.eq("sentence share is null", r["unchanged_sentence_share_pct"], None)
        all_checks += c.results
        # S5 zero
        c = Checks()
        transport = FakeDriveTransport(SPIKE_FIXTURES / "s5-zero")
        provider = GDriveDocProvider(transport=transport)
        snaps0 = provider.snapshots(ArtifactRef("gdrive-doc", transport.file_meta["id"]))
        c.eq("zero snapshots", snaps0, [])
        try:
            doc_join([], label="fixture-s5-zero", source="gdrive-fixture",
                     provider="gdrive-doc", history_complete=False)
            raised = None
        except ValueError as e:
            raised = str(e)
        c.eq("join refuses empty history", raised, "no snapshots")
        all_checks += c.results
        return all_checks

    def test_all_89_fixture_checks_pass_on_v1(self):
        checks = self.collect()
        failures = [(n, d) for n, ok, d in checks if not ok]
        self.assertEqual(len(checks), 89, f"expected the spike's 89 checks, ported {len(checks)}")
        self.assertEqual(failures, [])

class TestHeadinglessFixtures(unittest.TestCase):
    def test_s6_headingless_export_sections_by_heuristic(self):
        _, meta, snaps, r = run_fixture_pipeline("s6-headingless")
        self.assertEqual(r["section_strategy"], "heuristic")
        self.assertIn("heuristic", r["labels"]["method"])
        self.assertEqual(sections_of(r), [("Harbour Plan", 60.0), ("Garden Notes", 66.7), ("Budget Sketch", 0.0)])
        self.assertEqual(r["overall_pct_unchanged_from_first_version"], 45.5)
        self.assertEqual(r["unchanged_sentence_share_pct"], 45.5)
        self.assertEqual(r["final_nonblank_lines"], 11)
        self.assertEqual(r.get("authors"), ["Alex Rivers", "Mina Park"])
        by = {s["section"]: s for s in r["per_section"]}
        self.assertEqual(by["Harbour Plan"]["introduced_by_revision"],
                         {"rev1 (s6-r1)": 3, "rev2 (s6-r2)": 1, "rev3 (s6-r3)": 1})
        self.assertEqual(by["Garden Notes"]["introduced_by_revision"],
                         {"rev1 (s6-r1)": 2, "rev2 (s6-r2)": 1})
        self.assertEqual(by["Budget Sketch"]["introduced_by_revision"], {"rev3 (s6-r3)": 3})
        self.assertEqual(r["mark"]["category"], "Closely steered")
        self.assertEqual(r["mark"]["reshaped_sections"], 2)

    def test_s7_unstructured_prose_falls_back_to_whole(self):
        _, meta, snaps, r = run_fixture_pipeline("s7-prose")
        self.assertEqual(r["section_strategy"], "whole")
        # final text: 5 non-blank lines, 3 of them verbatim from r1
        self.assertEqual(sections_of(r), [("(whole document)", 60.0)])
        self.assertEqual(r["overall_pct_unchanged_from_first_version"], 60.0)
        self.assertEqual(r["unchanged_sentence_share_pct"], 60.0)
        self.assertEqual(r["final_nonblank_lines"], 5)

    @needs_pg
    def test_heuristic_on_real_doc_with_markers_stripped(self):
        """The Personal-Guard findings draft, '#' markers removed (the
        Google-Docs-export shape): the heuristic must recover the
        section map the markdown strategy sees (17 of 18 headings;
        the 103-char title exceeds the length cap by design)."""
        import re as _re
        repo = PG_REPO
        final = subprocess.run(["git", "-C", str(repo), "show", "HEAD:FINDINGS_DRAFT.md"],
                               capture_output=True, text=True).stdout
        true_secs, _ = resolve_sections(final, "markdown")
        stripped = "\n".join(_re.sub(r"^#{1,3}\s+", "", l) for l in final.splitlines())
        secs, resolved = resolve_sections(stripped, "auto")
        self.assertEqual(resolved, "heuristic")
        titles = [t for t, _ in secs if t != "(preamble)"]
        true_titles = [t for t, _ in true_secs]
        recovered = [t for t in true_titles if t in titles]
        self.assertEqual(len(recovered), 17)
        self.assertEqual(len(titles), 17)  # zero false positives

    def test_strategy_resolution_rules(self):
        md = "# A\nbody one\n\n## B\nbody two\n"
        secs, strat = resolve_sections(md, "auto")
        self.assertEqual(strat, "markdown")
        secs, strat = resolve_sections(md, "whole")
        self.assertEqual((strat, [t for t, _ in secs]), ("whole", ["(whole document)"]))
        one = "Only Heading\nbody text here.\nmore body.\n"
        secs, strat = resolve_sections(one, "auto")
        self.assertEqual(strat, "whole")  # a single candidate is not enough for auto
        secs, strat = resolve_sections(one, "heuristic")
        self.assertEqual(strat, "heuristic")  # ... but explicit opt-in honours it
        self.assertEqual([t for t, _ in secs if t != "(preamble)"], ["Only Heading"])

class TestProviderParityAndFolder(unittest.TestCase):
    @needs_pg
    def test_findings_draft_parity_through_providers(self):
        repo = PG_REPO
        r = sr.doc_receipt(repo, "FINDINGS_DRAFT.md", "v14-parity")
        self.assertEqual(r["provider"], "git")
        self.assertEqual(r["history_complete"], True)
        self.assertEqual(r["authors"], ["Yuriy H"])
        self.assertEqual(r["overall_pct_unchanged_from_first_version"], 36.0)
        self.assertEqual(r["final_nonblank_lines"], 242)
        self.assertEqual(r["revisions"], 3)
        self.assertEqual([s["pct_unchanged_from_first_version"] for s in r["per_section"]],
                         [75.0, 100.0, 100.0, 100.0, 100.0, 100.0, 0.0, 91.7,
                          0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(r["mark"]["category"], "Closely steered")
        self.assertEqual(r["mark"]["reshaped_sections"], 1)
        self.assertNotIn("commitment", r)

    def test_folder_provider_demo_number(self):
        demo = DEMO_DATA
        r = sr.doc_receipt_provider("folder", "v14-folder", folder=str(demo))
        self.assertEqual(r["provider"], "folder")
        self.assertEqual(r["history_complete"], True)
        self.assertEqual(r["overall_pct_unchanged_from_first_version"], 58.3)
        self.assertEqual(r["revisions"], 3)
        self.assertEqual({s["section"]: s["pct_unchanged_from_first_version"] for s in r["per_section"]},
                         {"Field Notes": 100.0, "Alpha": 60.0, "Beta": 100.0, "Gamma": 0.0})
        shipped = json.loads(DEMO_RECEIPT.read_text())
        self.assertEqual(r["final_nonblank_lines"], shipped["final_nonblank_lines"])
        self.assertEqual(r["unchanged_sentence_share_pct"], shipped["unchanged_sentence_share_pct"])

    def test_git_provider_shallow_clone_reports_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = init_repo(Path(tmp) / "src")
            (src / "d.md").write_text("# T\n\none\n", encoding="utf-8")
            git(src, "add", "-A"); git(src, "commit", "-q", "-m", "v1")
            (src / "d.md").write_text("# T\n\none\ntwo\n", encoding="utf-8")
            git(src, "add", "-A"); git(src, "commit", "-q", "-m", "v2")
            subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{src}", str(Path(tmp) / "shallow")],
                           capture_output=True, check=True)
            r = sr.doc_receipt(Path(tmp) / "shallow", "d.md", "v14-shallow")
            self.assertEqual(r["history_complete"], False)
            self.assertEqual(r["revisions"], 1)

    def test_registry_shape(self):
        from providers import PROVIDERS
        self.assertEqual(sorted(PROVIDERS), ["folder", "gdrive-doc", "git"])
        self.assertEqual(get_provider("git").scheme, "git")

# ================================================================ component 3: impact
CC_DIR = Path.home() / "workspace/user/corpus/public/trace-commons/sessions/claude_code"
CODEX_DIR = Path.home() / "workspace/user/corpus/public/codex-aletheia"
needs_cc = unittest.skipUnless(CC_DIR.exists(),
                               "trace-commons corpus sessions not present")
needs_iceberg = unittest.skipUnless(CC_DIR.exists() and IMPACT_RESULTS.exists(),
                                    "trace-commons corpus sessions or impact-spike results.json not present")
needs_codex = unittest.skipUnless(
    CODEX_DIR.exists() and IMPACT_RESULTS.exists() and RECEIPTS_CODEX.exists(),
    "codex corpus sessions, impact-spike results.json, or receipts-codex not present")

def corpus_file(d, prefix):
    return next(p for p in d.glob("*.jsonl") if p.name.startswith(prefix))

class TestImpactRegression(unittest.TestCase):
    @needs_iceberg
    def test_iceberg_impact_matches_spike_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(corpus_file(CC_DIR, "860618e1"), "v14-ice",
                                recon_dir=Path(tmp) / "recon")
            g = r["git_join"]
            self.assertEqual(g["headline_fields"]["post_first_prompt_share_pct"], 86.4)
            self.assertEqual(g["blame_vs_memory_provenance_agreement_pct"], 99.5)
            im = g["impact"]
            self.assertEqual(im["procedural_turns"], 16)
            self.assertEqual(im["continuation_turns"], 5)
            self.assertEqual(im["reshaping_turns"], 11)
            self.assertEqual(im["unmeasured_segments"], 8)
            self.assertEqual(im["reshaping_share_pct"], 27.5)
            self.assertEqual(im["reshaping_lines"], 344)
            self.assertEqual(im["redirect_segments"], 9)
            self.assertIn("interactive Claude Code session", im["scope"])
            self.assertEqual(r["mark"]["category"], "Closely steered")
            classes = {s["segment"]: s["impact_class"] for s in g["per_segment"] if s["segment"] >= 0}
            spike = json.loads(IMPACT_RESULTS.read_text())
            want = {p["segment"]: p["class"] for p in spike["claude_code"]["860618e1"]["per_segment"]
                    if not p["pre_prompt"]}
            self.assertEqual(classes, want)

    @needs_cc
    def test_control_reshaping_exactly_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(corpus_file(CC_DIR, "4130c9a7"), "v14-ctl",
                                recon_dir=Path(tmp) / "recon")
            im = r["git_join"]["impact"]
            self.assertEqual(im["reshaping_turns"], 0)
            self.assertEqual(im["reshaping_lines"], 0)
            self.assertEqual(im["reshaping_share_pct"], 0.0)
            self.assertEqual(r["git_join"]["headline_fields"]["post_first_prompt_share_pct"], 0.0)
            self.assertEqual(r["mark"]["category"], "One-shot")

    @needs_codex
    def test_codex_spot_checks_against_shipped_receipts(self):
        spike = json.loads(IMPACT_RESULTS.read_text())
        labels = ["codex-019eee77052d"]
        shipped0 = RECEIPTS_CODEX / f"{labels[0]}.receipt.json"
        self.assertTrue(shipped0.exists())
        by_label = {}
        for p in CODEX_DIR.glob("*.jsonl"):
            parts = p.stem.split("-")
            by_label[f"codex-{parts[-5]}{parts[-4][:4]}"] = p
        picked = sorted(by_label)[:1] + sorted(by_label)[25:26] + sorted(by_label)[-1:]
        with tempfile.TemporaryDirectory() as tmp:
            for label in picked:
                shipped = json.loads((RECEIPTS_CODEX / f"{label}.receipt.json").read_text())
                r = sr.code_receipt(by_label[label], label, recon_dir=Path(tmp) / label)
                self.assertEqual(r["mechanistic"]["human_turns"], shipped["mechanistic"]["human_turns"], label)
                self.assertEqual(r["git_join"]["final_nonblank_lines"], shipped["git_join"]["final_nonblank_lines"], label)
                self.assertEqual(r["git_join"]["headline_fields"]["post_first_prompt_share_pct"],
                                 shipped["git_join"]["headline_fields"]["post_first_prompt_share_pct"], label)
                mine = {s["segment"]: (s["lines_introduced_gross"], s["lines_surviving_to_head"])
                        for s in r["git_join"]["per_segment"]}
                want = {s["segment"]: (s["lines_introduced_gross"], s["lines_surviving_to_head"])
                        for s in shipped["git_join"]["per_segment"]}
                self.assertEqual(mine, want, label)
                im = r["git_join"]["impact"]
                sc = spike["codex"][label]["class_counts"]
                self.assertEqual(im["procedural_turns"], sc.get("procedural", 0), label)
                self.assertEqual(im["continuation_turns"], sc.get("continuation", 0), label)
                self.assertEqual(im["reshaping_turns"], sc.get("reshaping", 0), label)
                self.assertEqual(im["unmeasured_segments"], sc.get("unmeasured", 0), label)
                self.assertEqual(im["redirect_segments"], spike["codex"][label]["redirect_segments"], label)
                self.assertIn("codex_exec", im["scope"], label)
                self.assertEqual(r["mechanistic"]["session_origin"],
                                 {"originator": "codex_exec", "source": "exec"}, label)

    def test_codex_synthetic_impact_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sr.code_receipt(FIXTURES / "session_codex_synthetic.jsonl", "v14-cx",
                                recon_dir=Path(tmp) / "recon")
            im = r["git_join"]["impact"]
            # seg1 rewrote seg0's "beta" line: exactly one reshaping turn.
            self.assertEqual(im["reshaping_turns"], 1)
            self.assertEqual(im["reshaping_lines"], 4)
            self.assertEqual(im["procedural_turns"], 0)
            self.assertEqual(r["mark"]["category"], "Steered")

# ================================================================ component 4: the mark
class TestMarkBoundaries(unittest.TestCase):
    def session(self, tmp, blocks_per_segment):
        records = []
        for i, blocks in enumerate(blocks_per_segment):
            records.append(rec_user_text(f"step {i}", ts=f"2026-10-21T10:{i:02d}:00Z"))
            records.append(rec_assistant(f"m{i}", blocks, ts=f"2026-10-21T10:{i:02d}:30Z"))
        return write_session(tmp, records)

    def test_prompted_when_followups_never_reshape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.session(tmp, [
                [tu("Write", {"file_path": "a.txt", "content": "l1\nl2\n"})],
                [tu("Write", {"file_path": "b.txt", "content": "x1\n"})],
            ])
            r = sr.code_receipt(p, "v14-prompted", recon_dir=Path(tmp) / "r")
            self.assertEqual(r["git_join"]["impact"]["reshaping_turns"], 0)
            self.assertEqual(r["mark"]["category"], "Prompted")

    def test_steered_with_single_reshape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.session(tmp, [
                [tu("Write", {"file_path": "a.txt", "content": "l1\nl2\n"})],
                [tu("Edit", {"file_path": "a.txt", "old_string": "l2", "new_string": "l2-new"})],
            ])
            r = sr.code_receipt(p, "v14-steered", recon_dir=Path(tmp) / "r")
            self.assertEqual(r["git_join"]["impact"]["reshaping_turns"], 1)
            self.assertEqual(r["mark"]["category"], "Steered")

    def test_closely_needs_share_twenty_too(self):
        blocks = [[tu("Write", {"file_path": "a.txt", "content": "l1\nl2\nl3\nl4\n"})]]
        for i in range(3):
            blocks.append([tu("Edit", {"file_path": "a.txt", "old_string": f"l{i+1}",
                                        "new_string": f"l{i+1}-v2"})])
        for _ in range(13):  # procedural padding: prompts with no ops
            blocks.append([])
        with tempfile.TemporaryDirectory() as tmp:
            p = self.session(tmp, blocks)
            r = sr.code_receipt(p, "v14-sharegate", recon_dir=Path(tmp) / "r")
            im = r["git_join"]["impact"]
            self.assertEqual(im["reshaping_turns"], 3)
            self.assertEqual(im["reshaping_share_pct"], 17.6)
            self.assertEqual(r["mark"]["category"], "Steered")  # share < 20: not Closely

    def test_doc_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "docs")
            doc = repo / "d.md"
            base = "# T\n\n## Alpha\nalpha one\n\n## Beta\nbeta one\n"
            doc.write_text(base, encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v1")
            r1 = sr.doc_receipt(repo, "d.md", "v14-doc1")
            self.assertEqual(r1["mark"]["category"], "One-shot")
            doc.write_text(base + "\n## Gamma\ngamma one\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v2")
            r2 = sr.doc_receipt(repo, "d.md", "v14-doc2")
            self.assertEqual(r2["mark"]["category"], "Prompted")  # addition only
            doc.write_text(base.replace("alpha one\n", "alpha one\nalpha two added\n")
                           + "\n## Gamma\ngamma one\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v3")
            r3 = sr.doc_receipt(repo, "d.md", "v14-doc3")
            self.assertEqual(r3["mark"]["reshaped_sections"], 1)
            # sections are T, Alpha, Beta, Gamma: 1 of 4 reshaped
            self.assertEqual(r3["mark"]["category"], "Steered")
            doc.write_text(base.replace("alpha one\n", "alpha one\nalpha two added\n")
                               .replace("beta one\n", "beta one\nbeta two added\n")
                           + "\n## Gamma\ngamma one\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v4")
            r4 = sr.doc_receipt(repo, "d.md", "v14-doc4")
            self.assertEqual(r4["mark"]["reshaped_sections"], 2)
            # 2 of 4 sections reshaped = at least half -> Closely steered
            self.assertEqual(r4["mark"]["category"], "Closely steered")

    def test_badge_svg(self):
        sys.path.insert(0, str(V1))
        import steering_viz as viz
        with tempfile.TemporaryDirectory() as tmp:
            p = self.session(tmp, [
                [tu("Write", {"file_path": "a.txt", "content": "l1\nl2\n"})],
                [tu("Edit", {"file_path": "a.txt", "old_string": "l2", "new_string": "l2-new"})],
            ])
            r = sr.code_receipt(p, "v14-badge", recon_dir=Path(tmp) / "r")
            svg = viz.badge_svg(r)
            ET.fromstring(svg)  # well-formed
            self.assertIn("STEERED", svg)
            self.assertIn("2 human turns", svg)
            self.assertNotIn("http://", svg.replace("http://www.w3.org/2000/svg", ""))
            out = subprocess.run([sys.executable, str(V1 / "steering_viz.py"),
                                  "/dev/null", "--badge"], capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)  # not a receipt: refuses cleanly
            if not PG_REPO.exists():
                self.skipTest("personal-guard workspace repo not present")
            rd = sr.doc_receipt(PG_REPO, "FINDINGS_DRAFT.md", "v14-badge-doc")
            svg2 = viz.badge_svg(rd)
            ET.fromstring(svg2)
            self.assertIn("CLOSELY STEERED", svg2)
            self.assertIn("3 revisions", svg2)

# ================================================================ component 5: commitment
def strip_volatile(d):
    if isinstance(d, dict):
        return {k: strip_volatile(v) for k, v in d.items()
                if k not in ("label", "reconstructed_repo_local_path")}
    if isinstance(d, list):
        return [strip_volatile(v) for v in d]
    return d

def verify_code_receipt(challenged, transcript_path, recon_dir):
    """The spec section 6 procedure. Returns (ok, stage)."""
    data = Path(transcript_path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != challenged["commitment"]["transcript_sha256"] or \
            digest != challenged["transcript_sha256"]:
        return False, "transcript hash"
    fresh = sr.code_receipt(transcript_path, challenged["label"],
                            recon_dir=recon_dir, commitment=True)
    if strip_volatile(fresh) != strip_volatile(challenged):
        return False, "field diff"
    return True, "verified"

class TestCommitment(unittest.TestCase):
    def test_code_round_trip_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            sess = FIXTURES / "session_codex_synthetic.jsonl"
            r = sr.code_receipt(sess, "v14-commit", recon_dir=Path(tmp) / "a", commitment=True)
            c = r["commitment"]
            self.assertEqual(c["algorithm"], "sha256")
            self.assertEqual(c["transcript_sha256"], hashlib.sha256(sess.read_bytes()).hexdigest())
            self.assertEqual(c["transcript_sha256"], r["transcript_sha256"])
            self.assertRegex(c["repo_head_sha"], r"^[0-9a-f]{40}$")
            head = subprocess.run(["git", "-C", str(Path(tmp) / "a"), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            self.assertEqual(c["repo_head_sha"], head)
            for rel, want in c["artifact_file_sha256"].items():
                blob = subprocess.run(["git", "-C", str(Path(tmp) / "a"), "cat-file", "blob",
                                       f"HEAD:{rel}"], capture_output=True).stdout
                self.assertEqual(hashlib.sha256(blob).hexdigest(), want)
            ok, stage = verify_code_receipt(r, sess, Path(tmp) / "b")
            self.assertEqual((ok, stage), (True, "verified"))
            # negative: flip one byte inside a prompt string (still valid JSONL)
            data = sess.read_bytes().replace(b"build the thing", b"build the thinh")
            self.assertEqual(len(data), len(sess.read_bytes()))
            tampered = Path(tmp) / "tampered.jsonl"; tampered.write_bytes(data)
            ok, stage = verify_code_receipt(r, tampered, Path(tmp) / "c")
            self.assertEqual((ok, stage), (False, "transcript hash"))
            # and a forged field in the receipt itself fails the diff stage
            forged = json.loads(json.dumps(r)); forged["mechanistic"]["human_turns"] = 99
            ok, stage = verify_code_receipt(forged, sess, Path(tmp) / "d")
            self.assertEqual((ok, stage), (False, "field diff"))
            # STEERING.md carries exactly the spec's one line
            md = sr.render_md(r)
            cline = [l for l in md.splitlines() if l.startswith("- Commitment")]
            self.assertEqual(len(cline), 1)
            self.assertIn(c["transcript_sha256"][:12] + "…", cline[0])
            self.assertIn(c["repo_head_sha"][:12] + "…", cline[0])

    def test_code_commitment_reproducible_with_seeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "seedsrc")
            shutil.copytree(FIXTURES / "seed_repo", repo, dirs_exist_ok=True)
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "base")
            sess = FIXTURES / "session_edit_existing.jsonl"
            r1 = sr.code_receipt(sess, "v14-seed-commit", repo_dir=repo,
                                 recon_dir=Path(tmp) / "a", commitment=True)
            r2 = sr.code_receipt(sess, "v14-seed-commit", repo_dir=repo,
                                 recon_dir=Path(tmp) / "b", commitment=True)
            self.assertEqual(r1["commitment"], r2["commitment"])
            want_seed = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD^{commit}"],
                                       capture_output=True, text=True).stdout.strip()
            self.assertEqual(r1["commitment"]["seed_repo_head_sha"], want_seed)

    def test_doc_commitment_known_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp) / "docs")
            doc = repo / "d.md"
            doc.write_text("# T\n\nalpha\nbeta\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v1")
            doc.write_text("# T\n\nalpha\nbeta revised\ngamma\n", encoding="utf-8")
            git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "v2")
            r = sr.doc_receipt(repo, "d.md", "v14-doc-commit", commitment=True)
            c = r["commitment"]
            shas = subprocess.run(["git", "-C", str(repo), "log", "--follow", "--reverse",
                                   "--pretty=format:%H", "--", "d.md"],
                                  capture_output=True, text=True).stdout.split()
            want = []
            for sha in shas:
                blob = subprocess.run(["git", "-C", str(repo), "cat-file", "blob",
                                       f"{sha}:d.md"], capture_output=True).stdout
                want.append(hashlib.sha256(blob).hexdigest())
            self.assertEqual(c["revision_content_sha256"], want)
            self.assertEqual(c["final_content_sha256"], want[-1])
            r2 = sr.doc_receipt(repo, "d.md", "v14-doc-commit", commitment=True)
            self.assertEqual(r2["commitment"], c)
            md = sr.render_md(r)
            self.assertIn("2 revision content hashes", md)
            plain = sr.doc_receipt(repo, "d.md", "v14-doc-plain")
            self.assertNotIn("commitment", plain)

    def test_cli_commitment_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"), "code",
                                  str(FIXTURES / "session_codex_synthetic.jsonl"),
                                  "--label", "cli-commit", "--commitment", "--out", str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            r = json.loads((out / "cli-commit.receipt.json").read_text())
            self.assertIn("commitment", r)
            self.assertEqual(json.loads(run.stdout)["commitment"], True)
            self.assertEqual(json.loads(run.stdout)["mark"], "Steered")

# ================================================================ CLI providers
class TestDocCLIProviders(unittest.TestCase):
    def test_cli_folder_inference_and_git_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            demo = DEMO_DATA
            run = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"), "doc",
                                  str(demo), "--label", "cli-folder", "--out", str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads(run.stdout)
            self.assertEqual(summary["provider"], "folder")
            self.assertEqual(summary["overall_unchanged_pct"], 58.3)
            run = subprocess.run([sys.executable, str(V1 / "steering_receipt.py"), "doc",
                                  str(demo), "--provider", "folder", "--section-strategy", "whole",
                                  "--label", "cli-folder2", "--out", str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            r = json.loads((out / "cli-folder2.receipt.json").read_text())
            self.assertEqual(r["section_strategy"], "whole")
            self.assertEqual(len(r["per_section"]), 1)

if __name__ == "__main__":
    unittest.main()
