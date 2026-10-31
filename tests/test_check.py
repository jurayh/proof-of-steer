"""Tests for the receipt-vs-diff checker (check.py).

Fixtures under fixtures/check/ are generated from measured data by
fixtures/check/generate.py: real receipts from the shipped pipeline
and real git diffs. Only the derived variants (extra file, missing
line, truncation, empty) are scripted edits of a genuine diff, each
recorded in manifest.json with its expected effect.
"""

import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import check as check_mod

FIX = Path(__file__).resolve().parent / "fixtures" / "check"

# GitHub refuses any path component named `.git`, so the captured-repo
# fixture ships its git directory as `dotgit` and tests materialize it as
# `.git` on first use. A checkout that already has `.git` (a local run)
# is left untouched.
_dotgit = FIX / "captured-repo" / "dotgit"
_git = FIX / "captured-repo" / ".git"
if _dotgit.is_dir() and not _git.exists():
    shutil.copytree(_dotgit, _git)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def run(receipt_name, diff_name, repo=None):
    receipt = load(receipt_name)
    diff_text = (FIX / diff_name).read_text(encoding="utf-8")
    return check_mod.check_receipt(receipt, diff_text, repo=repo)


def verdicts(report, verdict):
    return [c for c in report["file_checks"] if c["verdict"] == verdict]


class TestDiffParser(unittest.TestCase):
    def test_new_file_counts_blanks_out(self):
        d = check_mod.parse_diff(
            "diff --git a/x.py b/x.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/x.py\n"
            "@@ -0,0 +1,4 @@\n"
            "+a\n"
            "+\n"
            "+b\n"
            "+   \n")
        self.assertFalse(d.truncated)
        self.assertEqual(d.files[0].status, "added")
        self.assertEqual(d.files[0].added_nonblank, 2)

    def test_deleted_file_and_rename_and_binary(self):
        d = check_mod.parse_diff(
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-a\n"
            "-b\n"
            "diff --git a/r1 b/r2\n"
            "similarity index 100%\n"
            "rename from r1\n"
            "rename to r2\n"
            "diff --git a/bin.dat b/bin.dat\n"
            "Binary files a/bin.dat and b/bin.dat differ\n")
        self.assertEqual([f.status for f in d.files], ["deleted", "renamed", "binary"])
        self.assertEqual(d.files[1].path, "r2")
        self.assertFalse(d.truncated)

    def test_truncated_mid_hunk(self):
        d = check_mod.parse_diff(
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,3 +1,4 @@\n"
            " a\n"
            "+b\n")
        self.assertTrue(d.truncated)
        self.assertEqual(d.truncated_file, "x.py")
        self.assertFalse(d.files[0].complete)

    def test_hunk_count_defaults_to_one(self):
        d = check_mod.parse_diff(
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n")
        self.assertFalse(d.truncated)
        self.assertEqual(d.files[0].added_nonblank, 1)
        self.assertEqual(d.files[0].deleted_nonblank, 1)

    def test_no_newline_marker_not_counted(self):
        d = check_mod.parse_diff(
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "\\ No newline at end of file\n"
            "+b\n"
            "\\ No newline at end of file\n")
        self.assertFalse(d.truncated)
        self.assertEqual(d.files[0].added_nonblank, 1)


class TestFixtures(unittest.TestCase):
    def test_f1_matching(self):
        r = run("iceberg.receipt.json", "iceberg.diff")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["diff"]["integrity"], "complete")
        self.assertEqual(r["counts"]["mismatch"], 0)
        self.assertEqual(r["counts"]["verified"], 16)  # 15 files + totals
        self.assertEqual(r["counts"]["unlisted"], 13)
        self.assertEqual(r["totals"]["verdict"], "verified")
        self.assertEqual(r["totals"]["receipt_lines"], 3102)
        self.assertEqual(r["totals"]["diff_added_nonblank"], 3102)
        # The unverifiable list names steering claims, never grades.
        claims = [n["claim"] for n in r["not_checked"]]
        self.assertIn("steering mark", claims)
        self.assertIn("post-first share", claims)

    def test_f2_extra_file_complete_list(self):
        r = run("demo.receipt.json", "demo-extra.diff")
        self.assertEqual(r["exit_code"], 1)
        bad = [c for c in r["file_checks"] if c["file"] == "extra.txt"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["verdict"], "mismatch")
        self.assertEqual(r["totals"]["verdict"], "mismatch")

    def test_f3_missing_line(self):
        r = run("iceberg.receipt.json", "iceberg-missing-line.diff")
        self.assertEqual(r["exit_code"], 1)
        bad = [c for c in r["file_checks"] if c["file"] == "IceBerg/style.css"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["verdict"], "mismatch")
        self.assertIn("missing 1 line", bad[0]["detail"])
        self.assertEqual(r["totals"]["verdict"], "mismatch")

    def test_f4_different_artifact(self):
        r = run("control.receipt.json", "iceberg.diff")
        self.assertEqual(r["exit_code"], 1)
        self.assertGreater(r["counts"]["mismatch"], 0)
        self.assertEqual(r["totals"]["verdict"], "mismatch")

    def test_f5_truncated_never_passes(self):
        r = run("iceberg.receipt.json", "iceberg-truncated.diff")
        self.assertEqual(r["exit_code"], 1)
        self.assertEqual(r["diff"]["integrity"], "truncated")
        self.assertEqual(r["counts"]["mismatch"], 0)
        self.assertGreater(r["counts"]["unverifiable"], 0)
        self.assertEqual(r["totals"]["verdict"], "unverifiable")

    def test_f6_capture_without_repo(self):
        r = run("captured.receipt.json", "captured.diff")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["totals"]["verdict"], "verified")
        self.assertEqual(r["capture"]["verdict"], "unverifiable")
        claims = [n["claim"] for n in r["not_checked"]]
        self.assertIn("capture commit claims", claims)

    def test_f6_capture_with_repo(self):
        r = run("captured.receipt.json", "captured.diff",
                repo=str(FIX / "captured-repo"))
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["capture"]["verdict"], "verified")
        self.assertEqual(r["capture"]["tier"], "verified against the commit")
        self.assertEqual(r["capture"]["failed"], 0)

    def test_f7_document_floor(self):
        r = run("findings.receipt.json", "findings.diff")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual(r["totals"]["verdict"], "consistent")
        claims = [n["claim"] for n in r["not_checked"]]
        self.assertIn("per-section attribution", claims)

    def test_f8_empty_diff(self):
        r = run("iceberg.receipt.json", "empty.diff")
        self.assertEqual(r["exit_code"], 1)
        self.assertEqual(r["counts"]["mismatch"], 16)  # 15 files + totals
        self.assertEqual(r["totals"]["verdict"], "mismatch")

    def test_notes_only_receipt_checks_nothing(self):
        import capture as cap
        nr, _md = cap.notes_only_receipt(str(FIX / "captured-repo"), "demo-notes")
        report = check_mod.check_receipt(nr, "")
        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["counts"]["verified"], 0)
        self.assertEqual(report["counts"]["consistent"], 0)


class TestCli(unittest.TestCase):
    def test_run_check_exit_codes_and_json_out(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check_mod.run_check(
                    str(FIX / "iceberg.receipt.json"),
                    str(FIX / "iceberg.diff"), json_out=str(out))
            self.assertEqual(code, 0)
            self.assertIn("Totals [verified]", buf.getvalue())
            self.assertNotIn("certified", buf.getvalue())
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["exit_code"], 0)

    def test_run_check_input_errors(self):
        self.assertEqual(check_mod.run_check("/nonexistent.json", "/nonexistent.diff"), 2)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(check_mod.run_check(str(bad), str(FIX / "iceberg.diff")), 2)


if __name__ == "__main__":
    unittest.main()
