# Hash commitment for steering receipts: specification

Status: specified Oct 22, 2026. Not yet emitted by any build. Target: the
v1 adoption build. The `commitment` block specified here is purely
additive, so the schema id stays `proof-of-steering/receipt@1.0` and
existing renderers keep reading committed receipts by ignoring the block,
exactly as they already ignore `harness` and `seed_source`.

## 1. Purpose

A receipt is evidence, not a cryptographic proof: nothing in a plain
receipt stops a sender from editing its fields after the fact, or from
swapping in a different transcript when challenged. The commitment block
closes the first half of that gap. It records, at generation time, hashes
of the exact material the receipt was derived from, so that a later
reveal of that material can be checked against the receipt that was
already shared. Commit now, reveal only if challenged.

The commitment does not make a receipt unforgeable, and §7 states
exactly what it does and does not prove. Implementers must not describe
it as a signature.

## 2. The `commitment` block

Top-level receipt field `commitment`. Present if and only if the receipt
was generated with `--commitment` (§4). Never emitted as `null`, never
emitted empty. All digests are lowercase hex, 64 characters, never
truncated in the JSON (truncation is a rendering concern, §6).

| Field | Modes | Meaning |
|---|---|---|
| `algorithm` | both | Always the string `"sha256"`. A future algorithm change ships as a different value here, and verifiers must refuse values they do not implement rather than assume SHA-256. |
| `transcript_sha256` | code | SHA-256 over the exact bytes of the session file as read by the CLI at parse time (§3). Deliberately duplicates the always-on top-level `transcript_sha256` so the block is self-contained and verifiable as a unit. The two values must be identical; a receipt where they differ is malformed. |
| `repo_head_sha` | code | Full 40-character commit SHA of HEAD of the reconstructed repo at the end of replay, after the final segment commit (the chain includes the pre-existing seed commit when seeding occurred). |
| `seed_repo_head_sha` | code, only when `--repo` was supplied | The commit the seeding resolved to: the `--repo-ref` value resolved with `git rev-parse <ref>^{commit}`, or the seed repo's HEAD when no ref was given. Complements the coverage field `seed_source`, which records the source kind in words. Absent when no repo was supplied. |
| `artifact_file_sha256` | code, optional within the block | Map of repo-relative path to SHA-256 of that file's bytes at reconstructed HEAD (the HEAD blob bytes). Covers every file in the reconstructed HEAD, not only the 15 files listed in `per_file`. A sender may omit it to keep the receipt small; verifiers then rely on `repo_head_sha` plus field comparison (§6). |
| `revision_content_sha256` | document | Array of SHA-256 digests, oldest first, exactly parallel to `revision_shas` (length equals `revisions`). Each digest is over that revision's file blob bytes (§3). |
| `final_content_sha256` | document | SHA-256 of the final revision's content. Always equals the last element of `revision_content_sha256`; it is duplicated so a checker can anchor on the shipped artifact without indexing the array. |

No other fields are part of the block in this version. In particular the
block carries no self-asserted timestamp: a timestamp the sender types
proves nothing, and the timeline guarantee in §7 comes from the
receipt's first sharing being observed by others, not from a field.

## 3. Hash definitions (canonical bytes)

- **Transcript (code mode).** SHA-256 over the raw bytes of the session
  file, exactly as read from disk by the CLI, with no decoding, no
  newline conversion, and no reformatting. This is the same byte string
  the existing top-level `transcript_sha256` is computed over
  (`hashlib.sha256(transcript_bytes)` in `steering_receipt.py`), so the
  commitment implementation reuses that bytes object and must not
  re-read the file.
- **Revision content (doc mode).** SHA-256 over the stored blob bytes of
  the file at that revision, i.e. the output bytes of
  `git cat-file blob <rev>:<path>`. Blob bytes are used rather than the
  CLI's text-decoded `git show` output so the digest does not depend on
  decoding or newline behaviour.
- **Artifact file (code mode).** SHA-256 over the HEAD blob bytes of the
  file in the reconstructed repo, the same bytes the file has in the
  reconstructed working tree at the end of replay.
- **Commit SHAs** (`repo_head_sha`, `seed_repo_head_sha`) are git's own
  object ids, copied verbatim, never recomputed by the CLI.

## 4. Emission rules

- **Flag.** `--commitment` is added to both the `code` and the `doc`
  subcommands. Default is off.
- **Why off by default.** Hashing is computationally cheap, so cost is
  not the reason. The transcript hash binds the receipt to one exact
  file, byte for byte. Session files are re-exported, re-saved,
  redacted, and converted between harness formats in normal handling,
  and every such touch changes the hash and orphans every receipt
  committed against the earlier bytes. A sender who expects the
  transcript to move should be able to issue an unbound receipt. In doc
  mode the analogous cost is that the receipt freezes one exact history
  even if the repo is later legitimately rewritten. The binding is
  valuable for disputed, high-stakes, or public work, so it is a
  deliberate act, not a default.
- **Same run, same bytes.** The commitment is computed by the CLI inside
  the same run that computes the receipt's fields, from the same
  in-memory material it parsed. There is no mode that adds a commitment
  to an existing receipt, and implementations must not provide one: a
  hash computed in a later, separate step binds a file to a receipt
  whose fields may have been edited in between, and proves nothing.
- **Deterministic replay under the flag.** When `--commitment` is
  passed, reconstructed-repo commits are created with author and
  committer dates pinned: each segment commit uses the timestamp of that
  segment's first transcript record, and the pre-existing seed commit
  uses the earliest segment timestamp. (Author and committer identity
  are already fixed by the reconstructed repo's config.) If a segment
  has no parseable timestamp, fall back to the first parseable timestamp
  in the transcript, then to `1970-01-01T00:00:00+00:00`. This is what
  makes `repo_head_sha` reproducible by a verifier's re-run (§6).
  Without `--commitment`, commit dates stay unpinned and no commitment
  block is emitted: current behaviour, unchanged.

## 5. STEERING.md rendering

Exactly one line is added to the header block, immediately after the
validation-scope line, and only when the block is present. Digests are
rendered as the first 12 hex characters followed by `…`. Full values
live only in the JSON.

- Code mode:
  `- Commitment (sha256): transcript <t12>…, reconstructed HEAD <h12>…[, seed repo <s12>…]. Reveal the material to verify.`
  The seed-repo clause appears only when `seed_repo_head_sha` is
  present.
- Doc mode:
  `- Commitment (sha256): final content <f12>…, <N> revision content hashes. Reveal the material to verify.`
  where `<N>` is the length of `revision_content_sha256`.

## 6. Verification procedure

Precondition: the challenged receipt carries a `commitment` block and
was shared at some point in a way a third party can timestamp (attached
to a pull request, committed to a repo, sent by email). §7 explains why
that observation matters.

### Code mode

1. The sender reveals the transcript file and discloses the seeding
   inputs, if any (the `--repo` directory and ref). The receipt's
   coverage `seed_source` already records whether seeding happened and
   from what kind of source.
2. The verifier hashes the revealed file's bytes. If the digest differs
   from `commitment.transcript_sha256` or from the top-level
   `transcript_sha256`, stop: the revealed file is not the file the
   receipt was made from.
3. The verifier re-runs the CLI on the revealed transcript with
   `--commitment` and the same seeding inputs, into a clean output
   directory.
4. The verifier diffs the fresh receipt against the challenged receipt
   field by field. Every field must be equal, including the whole
   `commitment` block (with `repo_head_sha` comparable across runs
   because of the pinned-date rule in §4), with only these volatile
   exceptions: `label`, if the re-run used a different one, and
   `git_join.reconstructed_repo_local_path`, which is machine-local by
   design. Any other difference means the challenged receipt was not
   produced by this CLI from this material.
5. Optional: if the sender also shares the original reconstructed repo
   directory, check `git rev-parse HEAD` against `repo_head_sha` and
   spot-check `artifact_file_sha256` entries against HEAD blobs.

### Doc mode

1. The verifier opens the repo the receipt names and lists the file's
   revisions oldest first with `git log --follow --reverse`, the same
   enumeration the CLI uses.
2. For each revision in order, hash the blob bytes
   (`git cat-file blob <rev>:<path>`) and compare the sequence against
   `revision_content_sha256` (count and each element). The last digest
   must also equal `final_content_sha256`. Any mismatch stops the
   check: the history the receipt describes is not this history.
3. The verifier re-runs the CLI in doc mode with `--commitment` and
   diffs all fields as in code-mode step 4, with one additional
   volatile exception: the repo-path prefix of `source` is a local
   path; compare the relative path and everything else.

## 7. What verification proves, and what it does not

A full match proves:

- The challenged receipt was derived by the CLI from exactly the
  revealed material. Every number in it is the public implementation's
  output on that input.
- The receipt was not edited after generation. Any edit breaks the
  field-by-field comparison against a fresh run.
- The material was not swapped after the receipt was shared. Different
  material cannot reproduce the committed hashes.
- Combined with an observed first-sharing time, the pair (material,
  receipt) existed by that time. The timeline is fixed: the story
  cannot be retrofitted after questions are asked.

A full match does **not** prove:

- That the revealed material is authentic. A fabricated transcript,
  manufactured together with a matching receipt before sharing,
  verifies perfectly. The commitment raises the cost of fabrication
  (the faker must build a complete, internally consistent session
  whose replay reproduces the claimed artifact and blame agreement, in
  advance) and it freezes the story, but it does not create truth.
- That the artifact under review is the artifact the session produced.
  That is a separate comparison, which `artifact_file_sha256` supports
  against the files as submitted.
- Anything about process the receipt itself cannot see. The doc-mode
  rejection blind spot, per-harness stratification, and the
  presence-not-dose reading all apply to committed receipts unchanged.

If the receipt was never shared in an observable way before the
challenge, verification proves internal consistency at reveal time
only: this receipt is the honest CLI output on this material. The
sender gains the timeline guarantee by sharing the receipt (not the
material) early, which is the behaviour the design is meant to reward.

## 8. Implementation checklist (adoption build)

- Add `--commitment` to both subparsers; thread it into `code_receipt`
  and `doc_receipt`.
- Code mode: reuse the parse-time transcript bytes object for the hash;
  after replay, read the reconstructed HEAD SHA; resolve and record
  the seed SHA when `--repo` is present; build the artifact file hash
  map from HEAD blobs (skippable per §2).
- Pin reconstructed commit dates under the flag (§4), which requires
  passing per-segment timestamps into `build_git_repo`.
- Doc mode: hash each revision's blob bytes with `git cat-file` during
  the existing version walk.
- Render the §5 line in `render_md` when the block is present.
- Tests: known-answer vectors on the existing fixtures (a committed
  receipt's full block pinned in the test), a two-runs reproducibility
  test for `repo_head_sha`, a tamper test (edit one field in a
  committed receipt, run the §6 comparison, expect failure), and a doc
  fixture asserting the revision hash sequence.
