# Receipt-vs-diff checker: spec (Oct 30, 2026)

Status: spec first, then build. This spec pins down what "verified"
means before code exists. The checker is a maintainer-side tool: a
contributor attaches a steering receipt to a PR, and the maintainer
verifies the receipt's artifact-side claims against the PR diff,
without ever seeing the transcript.

## Standing rules carried over

- The receipt is descriptive evidence, never a certified grade. The
  checker never prints an overall grade and never uses the word
  "certified".
- The transcript is the private key. The checker NEVER accepts a
  transcript as input, in any form. There is no transcript argument,
  no transcript flag, nothing to pass one through by accident.
- Local only. The checker reads two local files (plus an optional local
  repo for capture, below) and uploads nothing.
- No schema change. The receipt schema id stays
  `proof-of-steering/receipt@1.0`. The checker reads receipts; it
  never rewrites them.

## Inputs

```
python3 steering_receipt.py check <receipt.json> <diff> [--repo <repo>] [--json-out <path>]
```

- `<receipt.json>`: a code receipt or a document receipt, as emitted by
  this tool. Notes-only partial receipts are accepted but have no
  artifact file list, so every artifact claim reports unverifiable
  (see exit codes).
- `<diff>`: a unified diff file, the maintainer's natural artifact
  (`git diff > pr.diff`, or a downloaded PR diff). The parser handles
  `diff --git` headers, `---`/`+++` paths (with `a/`/`b/` prefixes
  stripped), new/deleted files (`/dev/null`), renames, binary-file
  markers, and hunk headers with omitted counts (count defaults to 1).
- `--repo`: optional, and ONLY for capture verification (below). It is
  not a general input: file and total checks run from the diff file
  alone, and no git-range input exists in v1. Justification: capture
  records live in the repo's git notes, which no diff file can carry,
  so commit-anchored capture claims are unverifiable without the repo.
  With `--repo`, the checker runs the existing commit-tier record
  verification from `capture.py` (`verify_records`, no transcript)
  and reports its tier and failure counts. It never asks for a
  transcript to reach the transcript tier.

## The central honesty constraint

A diff alone CANNOT verify steering. It contains no segments, no turn
counts, no post-first share, no steering mark, no decisions, no impact
classes, and no per-section maps. The checker verifies only
artifact-side consistency: does the artifact the receipt describes
match the artifact the diff describes? Everything else is reported as
explicitly not checked, with the reason, on every run. A report that
hid that list would be a false pass.

## Comparable quantities, defined exactly

Receipts count FINAL NON-BLANK lines. Diffs count ADDED lines
including blanks, and separately show deletions. Comparing the raw
numbers would be apples to oranges, so the checker counts added
non-blank lines itself from the diff content (added lines whose
content is not blank, where blank means empty or whitespace only) and
compares like with like. Deleted lines are counted the same way and
reported per file as information, except for created files (below).

### Code receipts

Receipt fields used: `git_join.files_at_head` (a count, not a list),
`git_join.final_nonblank_lines`, `git_join.per_file[]`, and the
headline `preexisting_share_pct`. One structural fact governs the
whole design: `per_file` holds only the UP TO 15 LARGEST files at
HEAD. When `len(per_file) < files_at_head`, the receipt does not
contain the full file list, and no per-file claim about the remaining
files can be checked. Whether the list is complete is knowable: it is
complete exactly when `len(per_file) == files_at_head`.

Per listed file, matched against the diff by new path (rename-aware:
the `+++` path wins), the verdict is one of:

- `verified`: the file is pure session content
  (`preexisting_share_pct == 0`) and added non-blank lines in the diff
  EQUAL the receipt's `final_lines`. This is the only per-file verdict
  the diff alone can prove, and it is reserved for it.
- `consistent`: the file carries pre-existing content
  (`preexisting_share_pct > 0`) and added non-blank lines are LESS
  THAN OR EQUAL to `final_lines`. The diff base is unknown, so the
  surviving pre-existing lines cannot be pinned down; the inequality
  is all the diff can honestly say. The implied surviving pre-existing
  count (`final_lines - added_nonblank`) is reported as information,
  never as a verified share.
- `mismatch`: any of (a) a pure file whose added non-blank count
  differs from `final_lines`, with the direction reported ("diff is
  missing N lines the receipt claims" vs "diff has N lines the receipt
  does not account for"); (b) a seeded file whose added non-blank
  count EXCEEDS `final_lines`; (c) a listed file with session content
  (`preexisting_share_pct < 100`) that the diff never touches; (d) a
  created file (`--- /dev/null`) with deleted lines.
- `unverifiable`: binary file, rename-only file (content moved, not
  added), or a file whose hunks are incomplete because the diff is
  truncated. The reason travels with the verdict.

Files in the diff that are NOT among the listed files are reported as
`unlisted`, with their added-line counts, and are NEVER counted as
mismatch: they may be genuine receipt files beyond the top-15 cut.
They are still constrained in aggregate by the totals check below, and
the report lists them prominently so a human sees them. When the
receipt's file list is complete (`len(per_file) == files_at_head`),
a diff file outside the list is instead a `mismatch` ("diff changes a
file the receipt does not list"), because then the distinction is
knowable.

Listed files that are 100% pre-existing and absent from the diff are
`consistent` (untouched seeded files are expected to be absent), not
mismatch.

Totals, over ALL diff files against the receipt total: when the
headline `preexisting_share_pct == 0` (greenfield receipt), total
added non-blank lines must EQUAL `final_nonblank_lines` for
`verified`; otherwise `mismatch` with direction. When pre-existing
content exists, total added non-blank lines must be LESS THAN OR
EQUAL to `final_nonblank_lines` for `consistent`; otherwise
`mismatch`. The totals check is what constrains unlisted files in
aggregate.

### Document receipts

Receipt fields used: `source` (basename only; the stored path may be
scrubbed), `final_nonblank_lines`,
`overall_pct_unchanged_from_first_version` (a FLOOR),
`history_complete`. The diff file matched is the one whose basename
matches the receipt's document basename; if the diff has exactly one
file it is used; if no file matches, that is a `mismatch`.

- File presence and the total inequality work as for code:
  added non-blank lines must be LESS THAN OR EQUAL to
  `final_nonblank_lines`, else `mismatch`.
- Floor consistency, only when `history_complete` is true: implied
  surviving lines = `final_nonblank_lines - added_nonblank`. If
  implied surviving is BELOW the floor (`floor_pct / 100 *
  final_nonblank_lines`, minus a rounding tolerance of one line),
  that is a `mismatch`: the diff added more than the receipt's floor
  allows. If implied surviving is at or above the floor, `consistent`
  (a partial diff can only raise implied surviving, never lower it).
  When `history_complete` is false, the floor is relative to the
  first AVAILABLE revision, the diff base is unknown, and the floor
  check is skipped with the reason stated.
- Per-section claims are explicitly `unverifiable`: diff hunks do not
  map to document sections.

### Capture block (code receipts only)

A receipt with a `capture` block reports its coverage split
(captured / inferred / unmeasured over segments total) and
`commits_with_records`. Against a diff file alone, every commit-
anchored capture claim is `unverifiable`: commit hashes and git notes
are not in a diff file, and the checker says so rather than
pretending otherwise. File and total checks still run normally.

With `--repo`, the checker additionally runs the existing commit-tier
verification (`capture.verify_records`, transcript tier never
attempted) and reports its tier plus pass/fail counts. Any failure is
a `mismatch` on the capture section. Recorded files absent from the
diff are listed as information, not a verdict, because a PR diff may
legitimately span only part of the recorded history.

## Diff integrity: truncated diffs never pass

The parser checks every hunk's declared old/new counts against the
lines actually present. If the diff ends mid-hunk, or a new file
header begins before a hunk's declared counts are satisfied, the diff
is `truncated`. Files fully parsed before the cut are still checked;
the cut file and everything after it report `unverifiable` with
reason "diff truncated". A truncated diff can never produce a clean
result (see exit codes). An empty diff is not truncated: it is zero
files, and every listed session-content file then reports `mismatch`
(absent from the diff).

## Output

Human summary on stdout, with sections: inputs, diff integrity,
per-file checks (one line per file: verdict, receipt lines, diff
added non-blank lines, deleted lines, reason where applicable),
unlisted diff files, totals, capture section (when the receipt has a
capture block), and NOT CHECKED (every unverifiable claim with its
reason). Machine-readable JSON with the same structure goes to
`--json-out <path>` when given. There is NO single overall verdict:
the report carries verdict counts (`verified`, `consistent`,
`mismatch`, `unverifiable`, `unlisted`) and the claim lists, and the
reader decides. The word "certified" never appears.

## Exit codes

- `0`: no `mismatch` verdict, the diff is complete, and at least one
  claim was checked.
- `1`: any `mismatch` verdict, or the diff is truncated, or zero
  claims were checked (for example a notes-only receipt, where there
  is nothing to check: exiting success would be a false pass).
- `2`: input error (unreadable files, unparseable receipt, diff with
  no parseable content at all).

## What it must NOT do

- Verify, grade, or endorse the steering mark, post-first share, turn
  counts, impact classes, or decisions from a diff.
- Grade the PR or the contributor.
- Accept or require a transcript, in any argument or flag.
- Upload anything, or contact any service.
- Rewrite the receipt, the diff, or any repo state. The checker only
  reads its inputs (`--repo` is read-only; `verify_records` reads
  notes and commits and writes nothing).

## Fixtures (hand-computed ground truth)

Fixtures live under `tests/fixtures/check/` with a generator script
documenting provenance. Every diff is derived from measured data
(real receipts and real git diffs), never invented line counts:

- F1 matching: IceBerg code receipt + the genuine empty-tree-to-HEAD
  diff of its reconstructed repo. Expect: all 15 listed files
  `verified`, totals `verified` (3102 == 3102), 13 unlisted diff
  files listed (not mismatch), no mismatch, exit 0.
- F2 extra file, complete list: small demo-session receipt (file list
  complete: `len(per_file) == files_at_head`) + its genuine diff +
  one appended new-file section for a file the receipt does not list.
  Expect: the extra file is a `mismatch`, totals `mismatch`, exit 1.
- F3 changed counts: F1's diff with one added line removed from a
  hunk (header counts fixed). Expect: that file `mismatch` (diff
  missing 1 line), totals `mismatch`, exit 1.
- F4 different artifact: one-prompt control receipt + IceBerg diff.
  Expect: `mismatch` verdicts, exit 1.
- F5 truncated: F1's diff cut mid-hunk. Expect: `truncated`,
  partial results only, exit 1, no false pass.
- F6 capture: capture-block receipt from the live-session flow
  (init, commit, checkpoint, attach) + its commit diff. Without
  `--repo`: file/total checks run, capture section `unverifiable`.
  With `--repo`: capture section `verified against the commit`
  (commit tier, no failures). Both runs exit 0 on their own terms
  (no mismatch in either).
- F7 document: findings-draft doc receipt + the genuine
  first-to-final diff of its git history. Expect: floor consistency
  holds (`consistent`), per-section claims listed under NOT CHECKED.
- F8 empty diff: IceBerg receipt + an empty diff. Expect: every
  listed session-content file `mismatch` (absent), exit 1.
