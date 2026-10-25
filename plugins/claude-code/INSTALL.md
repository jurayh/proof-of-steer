# Proof of Steering — Claude Code plugin

A pair of hooks that leave **steering evidence** for every Claude Code
session. A PostToolUse hook accumulates capture-time steering records
while the session runs, and a SessionEnd hook attaches those records
to the session's final commit as a git note and then writes the
**steering receipt**: how much of the shipped artifact arrived after
the first prompt, which segments introduced it, and how much
correction happened along the way. The receipt is descriptive
evidence, not a certified grade (see the SCHEMA.md beside the CLI).

Everything runs **locally**. Neither the hook nor the receipt CLI
makes any network call. Python standard library only. The one
deliberate exception is the capture attach at SessionEnd, which
pushes the steering notes ref (and nothing else) to the repo's
existing origin, and announces that it did so.

## What you get

| Piece | File |
|---|---|
| Hook script | `steering_hook.py` |
| Slash command | `commands/steering.md` (installs as `/steering`) |
| Settings fragment | `settings-snippet.json` (SessionEnd + PostToolUse) |
| Receipt and capture CLI it drives | `steering_receipt.py` with `capture.py` (Proof of Steering) |

Requirements: Python 3, `git`, and Claude Code.

## Where files land

For a session whose working directory is inside git repo `R`, the hook
writes under `R/.steering/`:

| File | What it is |
|---|---|
| `steering-receipt.json` | The latest session's receipt (schema `proof-of-steering/receipt@1.0`) |
| `STEERING.md` | The same receipt, rendered for humans |
| `session-<id8>.receipt.json`, `session-<id8>.STEERING.md` | Per-session copies, kept |
| `reconstructed-session-<id8>/` | A local git repo the CLI rebuilds from the session's Write/Edit operations so `git blame` can cross-check line provenance |
| `capture/<session-id>.json` | Capture state accumulated by the PostToolUse hook during the session (provisional records; the authoritative record is the git note written at SessionEnd) |
| `hook.log` | One JSON line per hook event (start / checkpoint / capture / done / skipped / error) |

The capture records themselves do not live under `.steering/`: at
SessionEnd they are written as a git note on HEAD under
`refs/notes/steer`, inside the repo's own git storage, and pushed to
the origin's notes ref by the attach step.

Tip: add `.steering/` to the repo's `.gitignore` unless you deliberately
want receipts committed (some teams do — the receipt JSON/MD carry no code
or prompt text; the reconstructed repo does carry your session's file
contents, see Privacy).

## Install

### 1. Get the code

Keep (or clone) the proof-of-steer tree somewhere stable, e.g.
`~/proof-of-steer/`. In the public repo the plugin lives at
`plugins/claude-code/` and the CLI modules (`steering_receipt.py`,
`capture.py`, and their companions) sit at the repository root beside
it. In the development tree the CLI modules sit in `v1/` instead. The
hook finds the CLI in either layout (see the lookup order below).

### 2. Register the hooks

Open your Claude Code settings — `~/.claude/settings.json` for all
projects, or `.claude/settings.json` in one project — and merge in the
contents of `settings-snippet.json`, replacing the placeholder path with
the real absolute path of `steering_hook.py`. The snippet registers
the same script under two hooks:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"/ABSOLUTE/PATH/TO/proof-of-steer/plugins/claude-code/steering_hook.py\"",
            "timeout": 600
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"/ABSOLUTE/PATH/TO/proof-of-steer/plugins/claude-code/steering_hook.py\"",
            "timeout": 600
          }
        ]
      }
    ]
  }
}
```

What each hook does:

- **PostToolUse** runs the capture checkpoint only: it re-reads the
  transcript as it stands and refreshes the session's provisional
  steering records under `.steering/capture/`. No receipt is built.
  Registering only SessionEnd also works; the SessionEnd attach then
  computes the records from the final transcript on its own, and the
  checkpoint state is a progress cache, not a requirement.
- **SessionEnd** runs the capture attach first (records onto HEAD as
  a git note, then the driver push of the notes ref only), and then
  builds the receipt, whose capture block already reflects the
  records this session just wrote.

Notes:

- `matcher` is empty = fire on every event. For SessionEnd that means
  every session end, whatever the reason (clear, logout, prompt exit,
  …). To restrict it, name reasons, e.g. `"matcher": "prompt_input_exit"`.
- `timeout` is in seconds. The default hook timeout may be too short for
  long sessions; 600 gives the receipt build room. If the timeout kills
  the hook, the session still ends normally — `hook.log` will show a
  `start` line with no matching `done`, which is the diagnostic.
- The hook is **fail-silent by design**: any problem (no git repo,
  unparsable transcript, CLI error) is written to `.steering/hook.log`
  (or stderr when there is no repo) and the hook exits 0. A broken
  receipt can never block or break a session.

### 3. Slash command (optional)

Copy `commands/steering.md` to `~/.claude/commands/steering.md` (all
projects) or `.claude/commands/steering.md` (one project). Then tell it
where the hook script is — set this in your shell profile:

```sh
export STEERING_HOOK="$HOME/proof-of-steer/plugins/claude-code/steering_hook.py"
```

`/steering` then regenerates the receipt for the **current** session (the
newest transcript for the project — i.e. the session in progress, so the
receipt covers it so far) and shows the headline numbers.

### 4. Verify

From any project directory inside a git repo, after at least one session:

```sh
python3 "$STEERING_HOOK" --cwd "$PWD" --latest --print-summary
```

You should get the session's human-turn count, post-first-prompt share
and blame agreement, plus the two receipt paths. (A scripted end-to-end
test of the hook itself lives in `tests/run_hook_test.py`; results in
`TESTING.md`.)

## Capture setup: one command per repo

Capture needs a one-time setup in each repo where you want steering
records, run once by hand:

```sh
proof-of-steer capture init /path/to/repo
```

It writes three pieces of git config: a fetch refspec so
`refs/notes/steer` arrives with a normal `git fetch`, a push refspec
pair so a normal `git push` carries the notes **alongside** the
branches (a lone notes push refspec makes git push exactly the
configured refspecs and silently drop the branches, so the pair is
always written together), and `notes.rewriteRef` covering
`refs/notes/steer` so git copies records onto amended and rebased
commits where it supports doing so. Running it again changes nothing.

With the setup in place, the flow during a session is:

1. Each PostToolUse firing refreshes the checkpoint state under
   `.steering/capture/`. The state holds provisional per-segment
   records (ids, hashes, counts, timestamps, line spans in replay
   coordinates) and never leaves the machine.
2. At SessionEnd the attach writes the session's segments as one
   steering record, a git note on HEAD under `refs/notes/steer`, with
   the hunks finalized against the HEAD commit's real diff.
3. The attach then pushes **only** `refs/notes/steer` to the repo's
   existing origin and announces the push in its output (watch for
   the `capture: pushed` line, also recorded in `hook.log`). It never
   pushes a branch or any other ref. If the push fails, the failure
   is announced and logged, the record stays stored locally, and the
   init config above remains as the fallback transport: your next
   normal `git push` carries the notes with your branches.
4. The SessionEnd receipt is built after the attach, so its capture
   block counts this session's segments as captured, verified
   against the transcript. Later receipts for the same session, run
   anywhere the notes have travelled, show the same split.

To read a repo's records without any transcript, run
`proof-of-steer notes /path/to/repo`: a notes-only partial receipt
with the per-commit classes, decision outcomes, and marks the
records support, labelled notes-only and verified against the
commit at most. Transcript-derived fields are shown as unavailable,
not zero.

How sessions map to commits in this build: everything a session
produced that is present in the target commit is attributed to that
one commit, at attach time. Attach to intermediate commits during a
long session (run `proof-of-steer capture attach` by hand whenever
you commit) if you want per-commit records instead. Work that was
never committed is not in any commit's diff, so no record can claim
it; the records under-claim rather than over-claim.

## Which hooks, and why these two

**SessionEnd** fires once, when the session is over and the
transcript is complete: exactly the receipt's input, and the moment
the session's work has a final commit to attach records to.
**PostToolUse** fires after every tool call and only refreshes the
capture checkpoint, which is cheap insurance: if a session dies
without a clean SessionEnd, the checkpoint state still holds the
provisional records, and a later attach (or the next session's) can
finalize them from the transcript.

**Stop works too for the receipt**, with the same script and payload shape, if you want a
*live* `.steering/STEERING.md` refreshed after every assistant turn:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python3 \"/ABSOLUTE/PATH/TO/proof-of-steering/plugins/claude-code/steering_hook.py\"", "timeout": 600 }
        ]
      }
    ]
  }
}
```

Costs of the Stop variant: the receipt is rebuilt from scratch on every
turn (O(session) each time — noticeable on long sessions), and each
receipt covers a partial transcript. The hook ignores the
`stop_hook_active` field; it never writes a decision, so it cannot trap a
session in a stop loop.

## How the hook finds the receipt CLI

First hit wins:

1. **`$STEERING_RECEIPT_CLI`** — explicit path to `steering_receipt.py`.
2. **`../../v1/steering_receipt.py` relative to the hook script** — the
   development tree layout: `<tree>/plugins/claude-code/` beside
   `<tree>/v1/`.
3. **`../../steering_receipt.py` relative to the hook script** — the
   public repo layout, where the CLI modules sit at the repository
   root: `<repo>/plugins/claude-code/` beside
   `<repo>/steering_receipt.py`.
4. **`steering_receipt.py` beside the hook script** — vendored
   single-folder installs.
5. **`steering_receipt.py` on `$PATH`**.

One more optional variable: **`STEERING_REPO_REF`** — if set, the hook
passes it to the CLI as `--repo-ref`, seeding pre-existing file bases
from that git ref (e.g. the commit the session started from) instead of
the working tree. Leave it unset unless you know the ref; the choice is
recorded on the receipt either way (`coverage.seed_source`).

## Privacy

- **Local only.** No network calls anywhere; stdlib only; nothing is
  uploaded, phoned home, or sent to any service. The single exception
  is the capture attach pushing the notes ref to the repo's **own
  existing origin**, announced in its output: your records travel to
  your remote, nowhere else.
- **Receipts never contain prompt text**, tool arguments, or file
  contents — counts, categories, file names, and line attributions only.
  That is a property of the receipt schema, not a redaction pass.
- **Steering records hold ids, hashes, counts, timestamps, and line
  spans only.** Never transcript text, never prompt text, never file
  contents. Decision entries store the class of each answer, never
  the answer. The one string from the work itself is a file path in a
  hunk entry, and that path is already in the commit the record
  rides on.
- **`hook.log`** contains timestamps, paths, the session id, and headline
  numbers. Nothing else.
- **The reconstructed repo is the one content-bearing artifact**: the CLI
  rebuilds the session's files (from the session's own Write/Edit
  operations) inside `.steering/` so `git blame` can verify provenance.
  It is your own code, generated on your machine, and safe to delete at
  any time — the next hook run rebuilds it.
- The receipt records the transcript's SHA-256, so anyone you share a
  receipt with can verify it against the transcript *if you also choose
  to share the transcript*. The hook never shares either.

## Uninstall

1. Remove the `SessionEnd`, `PostToolUse` (and `Stop`, if you added
   it) blocks from your settings.json.
2. Delete the project's `.steering/` directory (and the
   `STEERING_HOOK` / `STEERING_RECEIPT_CLI` exports, if you set them).
3. Delete `steering.md` from your commands directory, if installed.
4. Optional, per repo: the capture config and records are ordinary
   git state. Remove the `remote.origin.fetch` / `remote.origin.push`
   refspec lines and `notes.rewriteRef` that `capture init` added if
   you want them gone, and delete the records with
   `git update-ref -d refs/notes/steer` (local only; copies already
   pushed stay on the remote until deleted there too).

Nothing else was touched: no files outside `.steering/` are written, and
no settings other than the snippet you pasted are changed.

## Verification status — read this

The hook contract used here (payload JSON on stdin with `session_id`,
`transcript_path`, `cwd`, `hook_event_name`; SessionEnd's additional
`reason`; PostToolUse's additional `tool_name`; the settings.json shape
above; the transcript layout under
`~/.claude/projects/<encoded project path>/<session_id>.jsonl`) is taken
from **Anthropic's published Claude Code hooks and slash-command
documentation**. It was **not** verified against a live Claude Code on
the machine this plugin was built on — Claude Code is not installed
there. The PostToolUse capture wiring carries exactly the same status:
the payload fields are documented, the behaviour was verified only
through simulated payloads. What *was* verified end to end (see
`TESTING.md`): the hook script driven by simulated documented payloads
against a real session transcript and against the bundled sample
session, producing receipts whose headline numbers match the spike's
hand-checked values, capture records that verify at both tiers, plus
the failure paths. If a future Claude Code changes the payload, the
hook degrades the way it is designed to: it logs the reason and exits 0.
