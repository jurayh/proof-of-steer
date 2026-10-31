"""Generate the receipt-vs-diff checker fixtures from measured data.

Every receipt here is produced by the shipped pipeline and every base
diff is a real `git diff`. Only the DERIVED variants (extra file,
missing line, truncation, empty) are scripted edits of a genuine diff,
and each edit is recorded in manifest.json with its expected effect.
Run from the release directory: python3 tests/fixtures/check/generate.py

Requires (not shipped, workspace-local only):
- the trace-commons corpus sessions (IceBerg + control)
- the personal-guard repo (findings-draft history)
- the demo sample session bundled in demo.py
"""

import json
import subprocess
import sys
from pathlib import Path

RELEASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RELEASE))
OUT = RELEASE / "tests" / "fixtures" / "check"
TMP = Path("/tmp/check-fixture-gen")

CORPUS = Path.home() / "workspace" / "user" / "corpus" / "public" / "trace-commons" / "sessions" / "claude_code"
ICEBERG_SESSION = CORPUS / "860618e1-0cf6-43c6-81cf-fe67123082ba.jsonl"
CONTROL_SESSION = CORPUS / "4130c9a7-ee88-443a-91b5-224accd13629.jsonl"
PERSONAL_GUARD = Path.home() / "workspace" / "personal-guard"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def code_receipt_to(session, label, workdir):
    import steering_receipt as sr
    recon = workdir / f"recon-{label}"
    r = sr.code_receipt(str(session), label, recon_dir=recon)
    return r, recon


def diff_empty_to_head(recon):
    return run(["git", "-C", str(recon), "diff", EMPTY_TREE, "HEAD"])


def main():
    import demo as demo_mod
    import steering_receipt as sr
    import capture as cap

    OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    manifest = {}

    # F1: IceBerg receipt + genuine empty-tree-to-HEAD diff.
    r, recon = code_receipt_to(ICEBERG_SESSION, "iceberg", TMP)
    (OUT / "iceberg.receipt.json").write_text(json.dumps(r, indent=1))
    iceberg_diff = diff_empty_to_head(recon)
    (OUT / "iceberg.diff").write_text(iceberg_diff)
    assert r["git_join"]["files_at_head"] == 28, r["git_join"]["files_at_head"]
    assert r["git_join"]["final_nonblank_lines"] == 3102
    assert len(r["git_join"]["per_file"]) == 15
    manifest["iceberg"] = {
        "files_at_head": 28,
        "final_nonblank_lines": 3102,
        "listed_files": 15,
        "diff_files": iceberg_diff.count("diff --git "),
    }

    # F4 counterpart: one-prompt control receipt (diff reused from F1).
    r, _recon = code_receipt_to(CONTROL_SESSION, "control", TMP)
    (OUT / "control.receipt.json").write_text(json.dumps(r, indent=1))
    assert r["git_join"]["files_at_head"] == 34

    # F2 base: demo-session receipt + genuine diff (small file list).
    session = TMP / "demo-session.jsonl"
    session.write_text(demo_mod.SAMPLE_SESSION_JSONL + "\n")
    r, recon = code_receipt_to(session, "demo", TMP)
    (OUT / "demo.receipt.json").write_text(json.dumps(r, indent=1))
    demo_diff = diff_empty_to_head(recon)
    (OUT / "demo.diff").write_text(demo_diff)
    manifest["demo"] = {
        "files_at_head": r["git_join"]["files_at_head"],
        "listed_files": len(r["git_join"]["per_file"]),
        "complete_list": len(r["git_join"]["per_file"]) == r["git_join"]["files_at_head"],
        "final_nonblank_lines": r["git_join"]["final_nonblank_lines"],
    }
    assert manifest["demo"]["complete_list"], manifest["demo"]

    # F2 derived: append a new-file section the receipt does not list.
    extra = (
        "diff --git a/extra.txt b/extra.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/extra.txt\n"
        "@@ -0,0 +1,5 @@\n"
        "+alpha\n+beta\n+gamma\n+delta\n+epsilon\n"
    )
    (OUT / "demo-extra.diff").write_text(demo_diff + extra)

    # F3 derived: remove one added line from the first hunk of the
    # largest listed file (IceBerg/style.css, 380 lines), fixing the
    # hunk header counts. Targeting a listed file, so the file check
    # itself fires, not just the totals check.
    lines = iceberg_diff.splitlines(keepends=True)
    import re
    target_header = "diff --git a/IceBerg/style.css b/IceBerg/style.css"
    sec = next(i for i, l in enumerate(lines) if l.startswith(target_header))
    hi = next(i for i in range(sec, len(lines)) if lines[i].startswith("@@ "))
    ai = next(i for i in range(hi + 1, len(lines)) if lines[i].startswith("+") and not lines[i].startswith("+++"))
    header = lines[hi]
    m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    old_start, old_count, new_start, new_count = m.groups()
    new_count = int(new_count) if new_count is not None else 1
    lines[hi] = f"@@ -{old_start},{old_count} +{new_start},{new_count - 1} @@\n"
    del lines[ai]
    (OUT / "iceberg-missing-line.diff").write_text("".join(lines))
    manifest["missing_line"] = {"file": "IceBerg/style.css", "removed_added_lines": 1}

    # F5 derived: cut the IceBerg diff mid-hunk (60% of bytes).
    cut = len(iceberg_diff.encode()) * 60 // 100
    truncated = iceberg_diff.encode()[:cut].decode(errors="replace")
    (OUT / "iceberg-truncated.diff").write_text(truncated)

    # F8: empty diff.
    (OUT / "empty.diff").write_text("")

    # F6: capture-block receipt from the live-session flow + its
    # commit diff. Replicates the test_capture captured_demo_repo
    # pattern using the capture module's own APIs.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "work"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        cap.git(repo, "config", "user.email", "t@t")
        cap.git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".steering/\n")
        cap.git(repo, "add", ".gitignore")
        cap.git(repo, "commit", "-q", "-m", "repo setup")
        cap.init_repo(repo)
        analysis = cap.build_segment_records(session)
        # Preserve replay paths (unlike the test helper, which flattens
        # to basenames) so the commit diff paths match the receipt's
        # per-file paths exactly.
        for fp, flines in analysis["replay_final"].items():
            target = repo / fp
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(l for l, _ in flines) + "\n")
        cap.git(repo, "add", "-A")
        cap.git(repo, "commit", "-q", "-m", "session work")
        cap.write_checkpoint(repo, session, session_id="cap-session")
        res = cap.attach_pending(repo, session, session_id="cap-session", push=False)
        assert res["status"] == "attached", res
        r = sr.code_receipt(str(session), "captured", recon_dir=TMP / "recon-captured",
                            capture_repo=str(repo))
        assert "capture" in r and r["capture"]["captured_segments"] > 0, r.get("capture")
        (OUT / "captured.receipt.json").write_text(json.dumps(r, indent=1))
        cap_diff = run(["git", "-C", str(repo), "diff", "HEAD~1", "HEAD"])
        (OUT / "captured.diff").write_text(cap_diff)
        # Persist the repo (with notes) for the --repo variant test.
        run(["cp", "-r", str(repo), str(OUT / "captured-repo")])
        manifest["captured"] = {
            "captured_segments": r["capture"]["captured_segments"],
            "commits_with_records": r["capture"]["commits_with_records"],
        }

    # F7: findings-draft doc receipt (copy of the shipped example) +
    # genuine first-to-final diff of its git history.
    shipped = RELEASE / "examples" / "doc-steered-findings-draft.receipt.json"
    (OUT / "findings.receipt.json").write_text(shipped.read_text())
    findings_diff = run(["git", "-C", str(PERSONAL_GUARD), "diff",
                         "bde19aa5", "a58f7e5e", "--", "FINDINGS_DRAFT.md"])
    (OUT / "findings.diff").write_text(findings_diff)

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
