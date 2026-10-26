#!/usr/bin/env python3
"""End-to-end test for the Proof of Steering Claude Code hook.

Simulates Claude Code hook invocations against the real IceBerg spike
transcript (trace-commons session 860618e1) and checks:

  1. Hook mode, documented SessionEnd payload -> exit 0, receipt written
     to <repo>/.steering/steering-receipt.json, harness "claude-code",
     post_first_prompt_share_pct == 87.2 (at complete op collection;
     the spike's hand-checked value was 86.4 on the lossy parse;
     the temp repo shares no file paths with the session, so repo seeding
     must find nothing and the unseeded spike numbers must reproduce).
  2. Hook mode, bogus transcript path -> exit 0 (fail-silent), the reason
     is logged to .steering/hook.log, the previous receipt is untouched.
  3. Hook mode, cwd outside any git repo -> exit 0.
  4. Manual mode --latest --print-summary against a fake $HOME with the
     documented ~/.claude/projects/<encoded>/<session>.jsonl layout ->
     exit 0 and the headline numbers print.
  5. Capture flow (simulated payloads, the bundled demo session as the
     live session): a PostToolUse payload -> exit 0, checkpoint state
     under .steering/capture/ with 7 accumulated segments; then a
     SessionEnd payload -> exit 0, a steering record note on HEAD
     carrying turns 0..6, a receipt whose capture block shows 7
     captured segments, and checkpoint + capture lines in hook.log.
     A PostToolUse payload with a bogus transcript -> exit 0.

Run:  python3 tests/run_hook_test.py     (exit 0 = all checks passed)
Local only; everything happens in a temp directory.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HOOK = PLUGIN_DIR / "steering_hook.py"
SESSION_ID = "860618e1-0cf6-43c6-81cf-fe67123082ba"

spec = importlib.util.spec_from_file_location("steering_hook", HOOK)
hook_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook_mod)

failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def find_transcript():
    corpus = Path.home() / "workspace/user/corpus/public/trace-commons/sessions/claude_code"
    hits = sorted(corpus.glob("860618e1-*.jsonl"))
    if not hits:
        sys.exit(f"IceBerg transcript not found under {corpus}")
    return hits[0]


def clean_env(extra=None):
    env = dict(os.environ)
    for k in ("STEERING_RECEIPT_CLI", "STEERING_REPO_REF", "STEERING_HOOK"):
        env.pop(k, None)  # exercise the default CLI lookup order (../../v1/...)
    env.update(extra or {})
    return env


def run_hook(payload, extra_env=None):
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=clean_env(extra_env), timeout=1700)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", *args], check=True, capture_output=True)


def main():
    transcript = find_transcript()
    print(f"transcript: {transcript}")
    tmp = Path(tempfile.mkdtemp(prefix="steering-hook-test-"))
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "zzz-steering-hook-test-marker.txt").write_text(
        "unique marker content 5f2c9a — no session path ends with this name\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "marker")

    # ---- 1. hook mode, happy path -------------------------------------
    payload = {"session_id": SESSION_ID, "transcript_path": str(transcript),
               "cwd": str(repo), "hook_event_name": "SessionEnd",
               "reason": "prompt_input_exit"}
    p = run_hook(payload)
    check("hook success: exit 0", p.returncode == 0, f"rc={p.returncode}")
    steering = repo / ".steering"
    rpath = steering / "steering-receipt.json"
    check("receipt written", rpath.is_file())
    check("STEERING.md written", (steering / "STEERING.md").is_file())
    receipt = json.loads(rpath.read_text())
    check("schema id", receipt.get("schema") == "proof-of-steering/receipt@1.0")
    check("harness is claude-code", receipt.get("harness") == "claude-code",
          f"harness={receipt.get('harness')}")
    share = receipt["git_join"]["headline_fields"]["post_first_prompt_share_pct"]
    check("post_first_prompt_share_pct == 87.2", share == 87.2, f"got {share}")
    agree = receipt["git_join"]["blame_vs_memory_provenance_agreement_pct"]
    check("blame agreement == 99.9", agree == 99.9, f"got {agree}")
    turns = receipt["mechanistic"]["human_turns"]
    check("human turns == 40", turns == 40, f"got {turns}")
    log_lines = (steering / "hook.log").read_text().strip().splitlines()
    done = [json.loads(l) for l in log_lines if json.loads(l).get("status") == "done"]
    check("hook.log has done line", len(done) == 1 and done[0]["session_id"] == SESSION_ID)
    before = hashlib.sha256(rpath.read_bytes()).hexdigest()

    # ---- 2. hook mode, bogus transcript -------------------------------
    bad = dict(payload, transcript_path=str(tmp / "no-such-session.jsonl"))
    p = run_hook(bad)
    check("bogus transcript: exit 0", p.returncode == 0, f"rc={p.returncode}")
    after = hashlib.sha256(rpath.read_bytes()).hexdigest()
    check("bogus transcript: previous receipt untouched", before == after)
    statuses = [json.loads(l).get("status")
                for l in (steering / "hook.log").read_text().strip().splitlines()]
    check("bogus transcript: skip logged", "skipped" in statuses,
          f"statuses={statuses}")

    # ---- 3. hook mode, cwd not a git repo ------------------------------
    plain = tmp / "plain"
    plain.mkdir()
    p = run_hook(dict(payload, cwd=str(plain)))
    check("non-repo cwd: exit 0", p.returncode == 0, f"rc={p.returncode}")
    check("non-repo cwd: nothing written", not (plain / ".steering").exists())

    # ---- 4. manual mode --latest --------------------------------------
    home = tmp / "home"
    proj = home / ".claude" / "projects" / hook_mod.encode_project_dir(repo)
    proj.mkdir(parents=True)
    (proj / f"{SESSION_ID}.jsonl").write_bytes(transcript.read_bytes())
    p = subprocess.run([sys.executable, str(HOOK), "--cwd", str(repo),
                        "--latest", "--print-summary"],
                       capture_output=True, text=True,
                       env=clean_env({"HOME": str(home)}), timeout=1700)
    check("manual --latest: exit 0", p.returncode == 0,
          f"rc={p.returncode} stderr={p.stderr.strip()[:200]}")
    check("manual --latest: prints 87.2", "87.2" in p.stdout)
    check("manual --latest: prints 40 turns", "40" in p.stdout)

    # ---- 5. capture flow -------------------------------------------
    v1 = (PLUGIN_DIR / ".." / ".." / "v1").resolve()
    sys.path.insert(0, str(v1))
    import capture as capture_mod
    import demo as demo_mod

    repo2 = tmp / "repo2"
    repo2.mkdir()
    git(repo2, "init", "-q", "-b", "main")
    git(repo2, "config", "user.email", "t@t")
    git(repo2, "config", "user.name", "t")
    (repo2 / ".gitignore").write_text(".steering/\n")
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "setup")
    cap_session = tmp / "cap-session.jsonl"
    cap_session.write_text(demo_mod.SAMPLE_SESSION_JSONL + "\n")
    analysis = capture_mod.build_segment_records(cap_session)
    for fp, lines in analysis["replay_final"].items():
        (repo2 / Path(fp).name).write_text(
            "\n".join(l for l, _ in lines) + "\n")
    git(repo2, "add", "-A")
    git(repo2, "commit", "-q", "-m", "session work")

    p = run_hook({"session_id": "captest-1",
                  "transcript_path": str(cap_session), "cwd": str(repo2),
                  "hook_event_name": "PostToolUse", "tool_name": "Write"})
    check("capture PostToolUse: exit 0", p.returncode == 0,
          f"rc={p.returncode}")
    state_path = repo2 / ".steering" / "capture" / "captest-1.json"
    check("capture PostToolUse: checkpoint state written", state_path.is_file())
    if state_path.is_file():
        st = json.loads(state_path.read_text())
        check("capture PostToolUse: 7 segments accumulated",
              len(st["segments"]) == 7, f"got {len(st['segments'])}")

    p = run_hook({"session_id": "captest-1",
                  "transcript_path": str(cap_session), "cwd": str(repo2),
                  "hook_event_name": "SessionEnd",
                  "reason": "prompt_input_exit"})
    check("capture SessionEnd: exit 0", p.returncode == 0,
          f"rc={p.returncode}")
    note = subprocess.run(["git", "-C", str(repo2), "notes", "--ref",
                           "steer", "show", "HEAD"],
                          capture_output=True, text=True)
    check("capture SessionEnd: steer note on HEAD", note.returncode == 0)
    if note.returncode == 0:
        rec = json.loads(note.stdout)
        check("capture SessionEnd: note carries turns 0..6",
              [s["turn"] for s in rec["segments"]] == list(range(7)))
    rpath2 = repo2 / ".steering" / "session-captest-1.receipt.json"
    check("capture SessionEnd: receipt written", rpath2.is_file())
    if rpath2.is_file():
        r2 = json.loads(rpath2.read_text())
        got = r2.get("capture", {}).get("captured_segments")
        check("capture SessionEnd: receipt shows 7 captured", got == 7,
              f"got {got}")
    log2 = (repo2 / ".steering" / "hook.log").read_text().strip().splitlines()
    statuses2 = [json.loads(l).get("status") for l in log2]
    check("capture: hook.log has checkpoint and capture lines",
          "checkpoint" in statuses2 and "capture" in statuses2,
          f"statuses={statuses2}")
    cap_lines = [json.loads(l) for l in log2
                 if json.loads(l).get("status") == "capture"]
    check("capture: capture log line names the attached turns",
          bool(cap_lines) and cap_lines[0].get("attached_turns") == list(range(7)))
    p = run_hook({"session_id": "captest-1",
                  "transcript_path": str(tmp / "no-such.jsonl"),
                  "cwd": str(repo2), "hook_event_name": "PostToolUse",
                  "tool_name": "Write"})
    check("capture PostToolUse bogus transcript: exit 0",
          p.returncode == 0, f"rc={p.returncode}")

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED: {failures}")
        return 1
    print("ALL CHECKS PASSED")
    print(f"(artifacts kept in {tmp} for inspection)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
