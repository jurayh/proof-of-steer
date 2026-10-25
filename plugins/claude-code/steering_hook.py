#!/usr/bin/env python3
"""Proof of Steering — Claude Code hook + manual runner.

Runs the Proof of Steering v1 receipt CLI (steering_receipt.py, `code`
subcommand) against a finished Claude Code session and writes the receipt
into a `.steering/` directory at the root of the session's git repo:

    .steering/steering-receipt.json   latest session's receipt (JSON)
    .steering/STEERING.md             latest session's rendered receipt
    .steering/session-<id8>.receipt.json / .STEERING.md   per-session copies
    .steering/reconstructed-<label>/  local reconstructed git repo the CLI
                                      materialises for its blame cross-check
    .steering/capture/<session>.json  capture-time steering record state
                                      accumulated during the session
    .steering/hook.log                one JSON line per hook event

Capture (the C-prime flow): under the PostToolUse hook the script runs
the CLI's `capture checkpoint`, accumulating per-segment intervention
records under .steering/capture/ while the session is live. At
SessionEnd it first runs `capture attach`, which writes the session's
records as a git note under refs/notes/steer on HEAD and then pushes
that notes ref only (never a branch) to the repo's existing origin,
announcing the push in its output; a push failure is logged, never
fatal. The receipt is built after the attach, so its capture block
already reflects the records this session just wrote. One-time setup
per repo: `proof-of-steer capture init` (see INSTALL.md).

Two modes:

  Hook mode (no arguments): read the Claude Code hook payload (JSON) from
  stdin — fields used: session_id, transcript_path, cwd, hook_event_name.
  Designed for the SessionEnd and PostToolUse hooks; the same payload
  shape makes it work under Stop too. FAIL-SILENT: any error is logged
  and the process exits 0 so a receipt problem can never break or block
  the user's session.

  Manual mode (used by the /steering slash command, and for testing):
      steering_hook.py --cwd DIR (--transcript PATH | --latest) [--print-summary]
  Manual mode is honest instead of silent: errors print to stderr and the
  exit code is 1.

Privacy: everything is local. Neither this script nor the CLI makes any
network call (stdlib only). The receipt files contain counts, categories,
file names and line attributions only — never prompt text, tool arguments
or file contents. hook.log lines contain timestamps, paths, the session
id and headline numbers only. The one content-bearing artifact is the
reconstructed repo under .steering/ — the session's OWN file contents,
rebuilt by the CLI from the session's Write/Edit operations so git blame
can cross-check provenance; it never leaves the machine (see INSTALL.md).

CLI resolution order for steering_receipt.py (first hit wins):
  1. $STEERING_RECEIPT_CLI, if set (must point at the file)
  2. ../../v1/steering_receipt.py relative to this script — the
     development tree layout: <tree>/plugins/claude-code/ + <tree>/v1/
  3. ../../steering_receipt.py relative to this script — the public
     repo layout, where the CLI modules sit at the repository root:
     <repo>/plugins/claude-code/ + <repo>/steering_receipt.py
  4. steering_receipt.py beside this script (vendored single-folder install)
  5. steering_receipt.py on $PATH

Optional environment:
  STEERING_REPO_REF   if set, passed to the CLI as --repo-ref (seed bases
                      from that git ref instead of the working tree)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
CLI_TIMEOUT_S = 1500  # generous; the settings snippet's hook timeout may be lower


# ---------------------------------------------------------------- utilities
def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_label(session_id):
    s = re.sub(r"[^A-Za-z0-9._-]", "-", str(session_id or "unknown"))[:12]
    return f"session-{s}" if s else "session-unknown"


def find_cli():
    """Resolve steering_receipt.py per the documented lookup order."""
    env = os.environ.get("STEERING_RECEIPT_CLI")
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    cand = PLUGIN_DIR / ".." / ".." / "v1" / "steering_receipt.py"
    if cand.is_file():
        return cand.resolve()
    cand = PLUGIN_DIR / ".." / ".." / "steering_receipt.py"
    if cand.is_file():
        return cand.resolve()
    cand = PLUGIN_DIR / "steering_receipt.py"
    if cand.is_file():
        return cand
    on_path = shutil.which("steering_receipt.py")
    return Path(on_path) if on_path else None


def repo_root_for(cwd):
    """Git top-level for cwd, or None when cwd is not inside a git repo."""
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    return None


def log_line(steering_dir, record):
    """Append one JSON line to .steering/hook.log. Best-effort: never raises."""
    try:
        steering_dir.mkdir(parents=True, exist_ok=True)
        with open(steering_dir / "hook.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- core run
def run_capture_cli(cli, action, repo_root, transcript, session_id):
    """Run the CLI's `capture checkpoint` or `capture attach` for one
    session. Returns (exit_code, summary_dict_or_None, stderr_tail).
    The attach subcommand prints its announcement lines before its
    JSON summary, so the summary is the last JSON-looking line."""
    cmd = [sys.executable, str(cli), "capture", action,
           "--repo", str(repo_root), "--session", str(transcript),
           "--session-id", str(session_id)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=CLI_TIMEOUT_S)
    text = proc.stdout or ""
    summary = None
    starts = [0] if text.startswith("{") else []
    idx = text.rfind("\n{")
    if idx >= 0:
        starts.append(idx + 1)
    for start in starts:
        try:
            summary = json.loads(text[start:])
            break
        except json.JSONDecodeError:
            summary = None
    tail = (proc.stderr or "").strip().splitlines()
    return proc.returncode, summary, (tail[-1][:300] if tail else "")


def run_receipt(cli, transcript, session_id, cwd, repo_root):
    """Run the CLI for one session. Returns (exit_code, summary_dict, stderr_tail).
    Raises only for pre-flight problems the caller should log."""
    steering_dir = repo_root / ".steering"
    steering_dir.mkdir(parents=True, exist_ok=True)
    label = sanitize_label(session_id)
    recon_dir = steering_dir / f"reconstructed-{label}"
    # The CLI appends commits to an existing reconstructed repo, which would
    # corrupt the blame cross-check on a re-run — always start it fresh.
    # This directory is our own generated artifact inside .steering/.
    if recon_dir.exists():
        shutil.rmtree(recon_dir, ignore_errors=True)

    cmd = [sys.executable, str(cli), "code", str(transcript),
           "--label", label, "--repo", str(repo_root),
           "--out", str(steering_dir), "--recon-dir", str(recon_dir)]
    repo_ref = os.environ.get("STEERING_REPO_REF")
    if repo_ref:
        cmd += ["--repo-ref", repo_ref]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=CLI_TIMEOUT_S)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return proc.returncode, None, (tail[-1][:300] if tail else "")
    receipt_path = steering_dir / f"{label}.receipt.json"
    md_path = steering_dir / f"{label}.STEERING.md"
    if not receipt_path.is_file():
        return 1, None, "CLI exited 0 but produced no receipt file"
    # "Latest session" copies the slash command and humans look for.
    shutil.copyfile(receipt_path, steering_dir / "steering-receipt.json")
    if md_path.is_file():
        shutil.copyfile(md_path, steering_dir / "STEERING.md")
    with open(receipt_path, encoding="utf-8") as f:
        receipt = json.load(f)
    gj = receipt.get("git_join", {})
    summary = {
        "label": receipt.get("label"),
        "harness": receipt.get("harness"),
        "human_turns": receipt.get("mechanistic", {}).get("human_turns"),
        "post_first_prompt_share_pct": gj.get("headline_fields", {}).get(
            "post_first_prompt_share_pct"),
        "blame_agreement_pct": gj.get("blame_vs_memory_provenance_agreement_pct"),
        "receipt_json": str(steering_dir / "steering-receipt.json"),
        "steering_md": str(steering_dir / "STEERING.md"),
    }
    return 0, summary, ""


def process_session(session_id, transcript, cwd, event_name, quiet):
    """Shared driver for hook and manual modes.

    Returns (ok, message, summary). Never raises when quiet (hook mode);
    in manual mode problems come back as (False, message, None)."""
    def fail(msg):
        return False, msg, None

    if not cwd or not Path(cwd).is_dir():
        return fail(f"cwd missing or not a directory: {cwd!r}")
    root = repo_root_for(cwd)
    if root is None:
        return fail(f"cwd is not inside a git repository: {cwd}")
    steering_dir = root / ".steering"
    base = {"ts": utcnow(), "event": event_name or "manual",
            "session_id": session_id, "cwd": str(cwd), "repo_root": str(root)}

    if not transcript or not Path(transcript).is_file():
        log_line(steering_dir, {**base, "status": "skipped",
                                "reason": f"transcript not found: {transcript}"})
        return fail(f"transcript not found: {transcript}")
    cli = find_cli()
    if cli is None:
        log_line(steering_dir, {**base, "status": "error",
                                "reason": "steering_receipt.py not found "
                                          "(see INSTALL.md lookup order)"})
        return fail("steering_receipt.py not found (see INSTALL.md lookup order)")

    log_line(steering_dir, {**base, "status": "start",
                            "transcript": str(transcript), "cli": str(cli)})
    if event_name == "PostToolUse":
        # Capture checkpoint only: accumulate the session's steering
        # records while it is live. No receipt is built here.
        try:
            code, cap, err_tail = run_capture_cli(
                cli, "checkpoint", root, transcript, session_id)
        except Exception as e:  # hook mode must survive anything
            log_line(steering_dir, {**base, "status": "error",
                                    "reason": f"{type(e).__name__}: {e}"[:300]})
            return fail(f"{type(e).__name__}: {e}")
        if code != 0 or cap is None:
            log_line(steering_dir, {**base, "status": "error",
                                    "reason": f"capture checkpoint exit {code}: {err_tail}"})
            return fail(f"capture checkpoint exited {code}: {err_tail}")
        log_line(steering_dir, {**base, "status": "checkpoint",
                                "segments_accumulated": cap.get("segments_accumulated")})
        return True, "ok", {"checkpoint": cap}
    if event_name == "SessionEnd":
        # Capture attach BEFORE the receipt, so the receipt's capture
        # block reflects the records this session just wrote. Attach
        # problems are logged and never fail the receipt.
        try:
            code, cap, err_tail = run_capture_cli(
                cli, "attach", root, transcript, session_id)
            if code == 0 and cap is not None:
                log_line(steering_dir, {**base, "status": "capture",
                                        "attached_turns": cap.get("attached_turns"),
                                        "commit": (cap.get("commit") or "")[:12],
                                        "push": cap.get("push")})
            else:
                log_line(steering_dir, {**base, "status": "capture-error",
                                        "reason": f"capture attach exit {code}: {err_tail}"})
        except Exception as e:
            log_line(steering_dir, {**base, "status": "capture-error",
                                    "reason": f"{type(e).__name__}: {e}"[:300]})
    try:
        code, summary, err_tail = run_receipt(cli, transcript, session_id, cwd, root)
    except subprocess.TimeoutExpired:
        log_line(steering_dir, {**base, "status": "error",
                                "reason": f"CLI timed out after {CLI_TIMEOUT_S}s"})
        return fail(f"receipt CLI timed out after {CLI_TIMEOUT_S}s")
    except Exception as e:  # hook mode must survive anything
        log_line(steering_dir, {**base, "status": "error",
                                "reason": f"{type(e).__name__}: {e}"[:300]})
        return fail(f"{type(e).__name__}: {e}")
    if code != 0:
        log_line(steering_dir, {**base, "status": "error",
                                "reason": f"CLI exit {code}: {err_tail}"})
        return fail(f"receipt CLI exited {code}: {err_tail}")
    log_line(steering_dir, {**base, "status": "done", **summary})
    return True, "ok", summary


# ---------------------------------------------------------------- hook mode
def hook_mode():
    """Read the hook payload from stdin. ALWAYS exits 0."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(f"steering_hook: unparsable hook payload ({e})", file=sys.stderr)
        return 0
    session_id = payload.get("session_id") or "unknown"
    cwd = payload.get("cwd") or os.getcwd()
    transcript = payload.get("transcript_path")
    if not transcript and session_id != "unknown":
        # Fallback: Claude Code's documented transcript layout,
        # ~/.claude/projects/<project>/<session_id>.jsonl
        for cand in Path.home().glob(f".claude/projects/*/{session_id}.jsonl"):
            transcript = str(cand)
            break
    ok, msg, _ = process_session(session_id, transcript, cwd,
                                 payload.get("hook_event_name") or "hook",
                                 quiet=True)
    if not ok:
        # Reason already recorded in .steering/hook.log whenever a repo root
        # was found; stderr is the fallback channel and cannot break anything.
        print(f"steering_hook: skipped ({msg})", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- manual mode
def encode_project_dir(cwd):
    """Claude Code's project-dir encoding: every non-alphanumeric in the
    absolute path becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))


def latest_transcript(cwd):
    proj = Path.home() / ".claude" / "projects" / encode_project_dir(cwd)
    if proj.is_dir():
        files = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if files:
            return files[-1]
    return None


def print_summary(summary, receipt_path):
    print(f"Proof of Steering — receipt for session {summary['label']}")
    print(f"  harness:                  {summary['harness']}")
    print(f"  human turns:              {summary['human_turns']}")
    print(f"  post-first-prompt share:  {summary['post_first_prompt_share_pct']}%"
          "  (share of shipped lines introduced after the first prompt)")
    print(f"  blame agreement:          {summary['blame_agreement_pct']}%")
    print(f"  receipt: {summary['receipt_json']}")
    print(f"  rendered: {summary['steering_md']}")


def manual_mode(argv):
    ap = argparse.ArgumentParser(
        prog="steering_hook.py",
        description="Proof of Steering — generate a session receipt manually "
                    "(the Claude Code hook calls this script with no arguments).")
    ap.add_argument("--cwd", required=True, help="project directory (inside the git repo)")
    ap.add_argument("--transcript", help="path to the session .jsonl")
    ap.add_argument("--latest", action="store_true",
                    help="use the newest transcript in ~/.claude/projects/<encoded cwd>/")
    ap.add_argument("--session-id", help="session id (default: transcript file stem)")
    ap.add_argument("--print-summary", action="store_true",
                    help="print headline numbers to stdout")
    args = ap.parse_args(argv)

    transcript = None
    if args.transcript:
        transcript = Path(args.transcript)
    elif args.latest:
        transcript = latest_transcript(args.cwd)
        if transcript is None:
            print(f"steering_hook: no transcript found for {args.cwd} under "
                  "~/.claude/projects/", file=sys.stderr)
            return 1
    else:
        ap.error("one of --transcript or --latest is required")
    session_id = args.session_id or transcript.stem
    ok, msg, summary = process_session(session_id, str(transcript), args.cwd,
                                       "manual", quiet=False)
    if not ok:
        print(f"steering_hook: {msg}", file=sys.stderr)
        return 1
    if args.print_summary and summary:
        print_summary(summary, summary["receipt_json"])
    return 0


def main():
    if len(sys.argv) > 1:
        return manual_mode(sys.argv[1:])
    if sys.stdin.isatty():
        print(__doc__.split("Two modes:")[0], file=sys.stderr)
        print("Hook mode reads the Claude Code payload from stdin; "
              "for manual use see --help.", file=sys.stderr)
        return 0
    return hook_mode()


if __name__ == "__main__":
    sys.exit(main())
