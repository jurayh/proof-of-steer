# Proof of Steering — Claude Code plugin: test record

Test: `tests/run_hook_test.py` (runnable, stdlib only, all work in a temp
dir). First run on 2026-10-22 on this project's build VM (Python 3.12.3,
git 2.43.0): 17/17 checks passed in ~4 s (the receipt CLI itself takes
~2 s on this transcript). The capture section below was added with the
capture adoption and re-run on 2026-10-25 on the same VM: **28/28
checks passed in ~5 s**.

## Setup

- Transcript: the real IceBerg spike session
  `860618e1-0cf6-43c6-81cf-fe67123082ba.jsonl` (trace-commons corpus,
  2.7 MB) — the session whose spike numbers were hand-checked
  (SPIKE-REPORT.md §2).
- Target repo: a fresh temp git repo containing one uniquely named
  marker file, so no session path can suffix-match it and repo seeding
  must find nothing — the unseeded spike numbers are the expectation.
- `STEERING_RECEIPT_CLI` / `STEERING_REPO_REF` were unset in the test
  environment, so the run exercised the default CLI lookup: rule 2,
  `../../v1/steering_receipt.py` relative to the hook script (the log
  confirms the resolved path).

## Results

Hook mode, simulated documented SessionEnd payload
(`session_id`, `transcript_path`, `cwd`, `hook_event_name: "SessionEnd"`,
`reason: "prompt_input_exit"`):

| Check | Result |
|---|---|
| Exit code | 0 |
| `.steering/steering-receipt.json` written | yes |
| `.steering/STEERING.md` written | yes |
| Receipt `schema` | `proof-of-steering/receipt@1.0` |
| Receipt `harness` | `claude-code` |
| `post_first_prompt_share_pct` | **86.4** (spike: 86.4) |
| Blame vs provenance agreement | **99.5%** (spike: 99.5%) |
| Human turns | **40** (spike: 40) |
| Coverage | 22 writes, 48 edits: 19 applied on transcript base, 0 seeded (0 files), 13 no-base, 16 no-match — the spike's exact accounting |
| `hook.log` | `start` then `done` lines for the session, with the headline numbers |

Failure paths (the fail-silent contract):

| Case | Result |
|---|---|
| Bogus `transcript_path` | exit 0; `skipped` line logged with the reason; previous receipt byte-identical afterwards |
| `cwd` outside any git repo | exit 0; nothing written anywhere (no repo root ⇒ no `.steering/`; the reason goes to stderr) |

Manual mode (what `/steering` runs), against a fake `$HOME` using the
documented `~/.claude/projects/<encoded cwd>/<session_id>.jsonl` layout:

| Check | Result |
|---|---|
| `--cwd <repo> --latest --print-summary` | exit 0; prints harness, 40 human turns, 86.4% post-first-prompt share, 99.5% blame agreement, and both receipt paths |

## Capture flow (added with the capture adoption, 2026-10-25)

Simulated payloads again, against the bundled demo session (the
7-turn synthetic sample from `demo.py`) as the "live" session, in a
fresh temp repo whose HEAD commit holds the session's final artifact
state:

| Check | Result |
|---|---|
| PostToolUse payload (`hook_event_name: "PostToolUse"`, `tool_name: "Write"`) | exit 0 |
| Checkpoint state at `.steering/capture/captest-1.json` | written, 7 segments accumulated |
| SessionEnd payload | exit 0 |
| Steering record note on HEAD under `refs/notes/steer` | present, segments carry turns 0..6 |
| SessionEnd receipt's capture block | 7 captured segments (the attach ran before the receipt build, as designed) |
| `hook.log` | `start`/`checkpoint` pair for PostToolUse, then `start`/`capture`/`done` for SessionEnd; the capture line names the attached turns 0..6 and the push outcome (no origin in this repo, so the push reads as not attempted, with the reason) |
| PostToolUse with a bogus `transcript_path` | exit 0 (fail-silent) |

The capture machinery itself (record format, attach attribution,
driver push to a bare origin, fresh-clone round trip, tamper flags at
both verification tiers, the amend behaviour, the privacy grep) is
covered by the CLI suite, `tests/test_capture.py` in the CLI tree
(15 tests), not by this harness.

## What this does and does not verify

Verified: the hook script end to end — payload handling, repo-root
detection, CLI resolution, receipt generation through the real CLI,
the capture checkpoint and attach calls, output layout, logging, and
the fail-silent behaviour — against a real transcript and the bundled
sample session, reproducing the spike's hand-checked headline numbers
exactly through the full plugin path.

Not verified: a live Claude Code firing the hook. Claude Code is not
installed on the build VM, so the payload field names (including
PostToolUse's), the settings.json hook shape, SessionEnd/Stop
semantics, and the transcript-directory layout are from Anthropic's
published documentation, not observed behaviour (INSTALL.md says the
same). The first real-machine run should be checked once: end a
session in a git repo and confirm `.steering/` appears; `hook.log`'s
`start`/`done` pair is the success signature, and a `capture` line in
between confirms the attach.
