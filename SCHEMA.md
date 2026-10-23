# proof-of-steer — receipt schema

**Schema id: `proof-of-steering/receipt@1.0`** (frozen Oct 21, 2026;
v1.1 changes Oct 22, 2026 are purely additive — the `harness` field and
coverage `seed_source` — so the schema id stays `receipt@1.0` and a 1.0
renderer still reads v1.1 receipts correctly by ignoring unknown fields.
v1.2 changes Oct 22, 2026 are likewise purely additive — doc-mode
`unchanged_sentence_share_pct` and `revision_count`, the extended
`validation_scope`, floor phrasing for the doc headline, and the
rejection-blind-spot note — so the schema id stays `receipt@1.0`.
v1.3 changes Oct 22, 2026 are likewise purely additive — a second code
adapter (Codex rollouts, `harness: "codex"`, a new value of the existing
field) and Codex-only coverage counters — so the schema id stays
`receipt@1.0`)
Emitted by `steering_receipt.py` as `<label>.receipt.json`, with a rendered
`<label>.STEERING.md` alongside. Stdlib-only, computed locally; a receipt
never contains raw prompt text, tool arguments, or file contents — counts,
categories, file names, and line attributions only.

Field-status vocabulary, from the spike verdict (SPIKE-REPORT.md §5):

- **headline** — validated in the spike; separates steered from one-prompt
  work where line authorship cannot.
- **context** — reported for completeness; known to saturate or mislead if
  read alone (each field says why).
- **supporting** — real signal but noisy; must be read jointly with other
  fields (each field says with what).

## Common fields (both kinds)

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Always `proof-of-steering/receipt@1.0`. |
| `label` | string | Caller-supplied receipt label. |
| `kind` | string | `code` or `document`. |
| `harness` | string\|null | (v1.1, additive; `"codex"` value added v1.3) The harness the receipt's source came from: `"claude-code"` or `"codex"` for code receipts (see the Codex adapter section), `"git"` for document receipts (the source is a git history, no agent harness), `null` when unknown. Stratification key for the per-harness context fields — see the stratification note below. |
| `validation_scope` | string | What the field set has been validated on so far. Current text (updated Oct 22, 2026 after the SWE-chat run and extended the same day with the CoAuthor result, full text in `steering_receipt.py`): validated on trace-commons (28 sessions, full join, blame ~100%) and local repositories; at-scale SWE-chat validation completed with a partial pass — bimodality approximately reproduced (40.9% vs 41%), pushback reproduced on the dominant agent (49.2% vs ~50%, Claude Code excl. first turns; pooled mix-sensitive), survival not reproduced (53.4% vs 59% under the dataset's metric-v2; per-agent 25–97%, so survival stays a context field stratified by agent). `post_first_prompt_share_pct` is validated as a steering-presence detector, not a dose measure. Document mode ground-truth-tested on CoAuthor (1,447 sessions): per-part map validated (sentence agreement 88.3%, false-untouched ~0.05%); headline % unchanged is a floor, not a dose estimate (MAE 13.0 pp, granularity-sensitive); document receipts contain no rejection evidence. Evidence: the SWE-chat validation report (VALIDATION.md) and the CoAuthor validation report (VALIDATION-coauthor.md) in the project records. |
| `labels` | object | `receipt_nature` is always "descriptive evidence, not a certified grade". Code receipts add `semantic_weights` (always "none" in v1 — all categories are rule-based) and `field_status` summarising the demotions below. Doc receipts add `method`. |

### Per-harness stratification (v1.1)

Survival (`first_segment_survival_pct`) and every pushback-derived field
(`correction_keyword_prompts`, `prompts_after_error`,
`correction_segment_share_pct`) are **per-harness values**. They describe
how users of one harness behaved, and pooling them across harnesses
produces numbers that describe the agent mix, not the work. SWE-chat
evidence (VALIDATION.md §4, §7): pushback rates run 21% (Codex) to 60%
(Copilot CLI), with Claude Code at 49.2%; per-agent survival spans
25–97%. Read and compare these fields only within one `harness` value,
never as cross-harness aggregates.

## Code receipts (`kind: "code"`)

Source: one coding-agent session JSONL — a Claude Code session
(`harness: "claude-code"`) or a Codex rollout (`harness: "codex"`,
adapter added in v1.3; `--format auto` sniffs which). The transcript is
replayed (Write/Edit ops in order) into a reconstructed local git repo —
one commit per human-turn segment — and `git blame` on HEAD cross-checks
the in-memory line provenance.

| Field | Type | Status | Meaning |
|---|---|---|---|
| `transcript_sha256` | string | — | SHA-256 of the transcript file, so anyone holding the transcript can re-verify the receipt. |
| `mechanistic.human_turns` | int | headline input | Genuine human prompts, after injected user-role records are filtered (see `injected_user_records_filtered`). |
| `mechanistic.injected_user_records_filtered` | int | — | User-role records dropped as injected: `isMeta` records or text starting with `<command-`, `<local-command`, or `Caveat:`. |
| `mechanistic.correction_keyword_prompts` | int | context | Prompts matching the correction keyword regex. Wrong at the edges (a spec paste can trip it); never read alone. Pushback-derived: per-harness (see stratification note). |
| `mechanistic.prompts_after_error` | int | supporting | Prompts whose preceding segment contained an `is_error` tool result. Pushback-derived: per-harness (see stratification note). |
| `mechanistic.rubber_stamp_prompts` | int | context | Prompts matching the rubber-stamp regex (`ok`, `continue`, `lgtm`, …). |
| `mechanistic.tokens_in_deduped` / `tokens_out_deduped` | int | context | Token totals from assistant `message.usage`, deduped by `message.id` (streaming duplicates would otherwise inflate ~3x). |
| `mechanistic.active_minutes_gapcap300` | float | context | Session span with inter-record gaps capped at 300s (idle time excluded). |
| `mechanistic.wall_minutes` | float | context | Raw first-to-last timestamp span. |
| `mechanistic.verification_lanes` | object | supporting | Per-harness verification counts: `test_like_shell` (shell commands matching a test-runner regex), `shell_total`, `browser_lane_actions`. A zero `test_like_shell` does NOT mean no verification (browser/manual lanes dominate some corpora). |
| `mechanistic.edit_write_ops` | int | — | Total Write + Edit tool calls in the session. |
| `mechanistic.coverage` | object | **headline (honesty)** | Reconstruction coverage — a low-coverage receipt must be discounted by its reader. See coverage fields below. |
| `git_join.method` | string | — | How the join was computed (reconstructed repo, commit per segment, blame cross-check; seed commit when `--repo` was used). |
| `git_join.reconstructed_repo_local_path` | string | — | Local path of the reconstructed repo (never uploaded). |
| `git_join.files_at_head` | int | — | Files in the reconstructed HEAD. |
| `git_join.final_nonblank_lines` | int | — | Non-blank lines in HEAD; the denominator for all share fields. |
| `git_join.git_ai_style_line_authorship` | string | context | Note that authorship alone carries no triage signal (spike finding); the agent-vs-pre-existing split lives in `per_segment`. |
| `git_join.first_artifact_segment` | int | — | Index of the first segment whose snapshot contains artifact lines (segment 0 may be prompt-only). |
| `git_join.headline_fields.post_first_prompt_share_pct` | float\|null | **headline** | Share of HEAD lines whose origin segment is after the first artifact-producing segment. 0% = the shipped artifact is the first prompt's output, untouched in origin. Spike medians: 0.0% (≤2-turn sessions) vs 77.2% (≥10-turn). |
| `git_join.headline_fields.preexisting_share_pct` | float\|null | headline | Share of HEAD lines seeded from `--repo` (origin −1) that survived unchanged. Only nonzero when `--repo` was supplied. |
| `git_join.context_fields.first_segment_survival_pct` | float\|null | context (demoted) | Share of the first artifact segment's lines surviving into HEAD. Saturates at ~100% on greenfield/creation corpora (spike finding). Per-harness value — do not pool across harnesses (SWE-chat: per-agent survival 25–97%; see the stratification note). |
| `git_join.context_fields.first_segment_lines` / `first_segment_lines_surviving_to_head` | int | context | Numerator/denominator behind the survival field. |
| `git_join.context_fields.share_of_head_already_present_after_first_segment_pct` | float\|null | context | Share of HEAD lines that already existed (by exact line text) after the first artifact segment. |
| `git_join.supporting_fields.correction_segment_share_pct` | float\|null | supporting (demoted) | Share of HEAD lines originating in correction-keyword or after-error segments. Noisy in both directions (0–100% in both spike groups); read jointly with `human_turns`. Pushback-derived: per-harness value, do not pool across harnesses. |
| `git_join.blame_vs_memory_provenance_agreement_pct` | float\|null | — | Agreement between `git blame` attribution and in-memory provenance over HEAD lines. Below ~95% means the reconstruction itself is suspect. |
| `git_join.per_segment[]` | array | headline | One row per segment: `segment` (index; −1 = pre-existing seed pseudo-segment, with `kind` set), `prompt_chars` (length only, never text), `correction_keyword`, `after_error`, `rubber_stamp`, `edit_write_ops`, `lines_introduced_gross`, `lines_surviving_to_head`. |
| `git_join.per_file[]` | array | headline | Up to 15 largest files at HEAD: `file`, `final_lines`, `first_segment_share_pct`, `preexisting_share_pct`. |

### Coverage fields (`mechanistic.coverage`)

| Field | Meaning |
|---|---|
| `repo_supplied` | Whether `--repo` was given. |
| `seed_source` | (v1.1, additive) Where seeded base content came from: `null` when no repo was supplied, `"working-tree"` for the repo's current working tree, or `"ref:<ref>"` when `--repo-ref <ref>` seeded from `git show <ref>:<path>` (session-time content when the ref names the commit the session ran against). |
| `writes` | Write ops replayed. |
| `edits_total` | Edit ops in the session. |
| `edits_applied_on_transcript_base` | Edits applied to a file the session itself Wrote earlier. |
| `edits_applied_on_repo_seeded_base` | Edits applied only because the base was seeded from `--repo` (the file was never Written in-session). |
| `edits_unapplied_no_base` | Edits whose target file was never Written and could not be seeded (no `--repo`, or no suffix match in it). |
| `edits_unapplied_no_match` | Edits whose base existed but `old_string` was not found in the reconstructed state. |
| `files_seeded_from_repo` | Distinct files seeded from `--repo`. |
| `patch_calls` | (Codex only, v1.3) `apply_patch` tool calls in the rollout. |
| `patch_calls_failed` | (Codex only) Patch calls whose tool output reports failure (`apply_patch verification failed…`, or a `patch_apply_end` with `success: false`). `apply_patch` is atomic, so a failed call's ops are dropped whole — none enter the join. |
| `patch_calls_unresolved` | (Codex only) Patch calls with neither a tool output nor a `patch_apply_end` event (truncated rollout tail). Their ops are included and this counter flags them. |
| `patch_file_ops_parsed` | (Codex only) File sections (Add/Update/Delete) from successful patches, converted to join ops. |
| `patch_file_ops_failed` | (Codex only) File sections inside failed patches (dropped; see `patch_calls_failed`). |
| `patch_hunks_parsed` / `patch_hunks_unparsed` | (Codex only) Update hunks converted to edit ops / hunks with no old-side lines to anchor a replace (counted, never guessed). A parsed hunk whose old and new blocks are identical is a no-op and emits no op (applying it would fabricate provenance). |
| `patch_body_lines_unparsed` | (Codex only) Lines inside a patch section body with no recognised prefix. |
| `shell_writes_extracted` | (Codex only) `exec_command` writes replayed into the join — only the unambiguous shapes: a lone heredoc `cat > path` write, or a bare `rm <path>`. |
| `shell_writes_unparsed` | (Codex only) `exec_command` commands whose command line shows a write/remove that was not extracted (heredoc appends, `sed -i`, echo/printf redirects, flagged or chained `rm`/`mv`/`cp`, other file redirects). Counted, never guessed into the join. Interpreter invocations (`python x.py`, `node server.js`) are opaque — their file effects are not counted either way. |

Seeding rule: lazy, on first Edit to an unknown file; match by normalized
path suffix (either path may be the suffix of the other, to absorb the
transcript's original-machine prefix and 4-component truncation); shortest
matching repo path wins. Seeded lines carry origin segment −1 and appear
in the reconstructed repo as an initial "pre-existing" commit, so blame
agrees with provenance for them too. Content source: the working tree by
default; with `--repo-ref REF` (v1.1) the candidate file list comes from
`git ls-tree` at REF and each base from `git show REF:<path>`, so a file
that changed after the session seeds as it was at REF, not as it is
today. `--repo-ref` requires `--repo`. The source used is recorded as
coverage `seed_source`.

### Codex adapter (v1.3)

Rollout records (`session_meta`, `turn_context`, `response_item`,
`event_msg`) are parsed into the same segment model as Claude Code
sessions, so every code field above is computed identically; only the
extraction differs:

- **Segments** start at `event_msg` `user_message` events — the one
  canonical input channel. The same input also appears as
  `response_item` user-role messages, which additionally carry injected
  wrappers (`<environment_context>`, developer text): those records are
  never segment starts, and wrapper texts are what
  `injected_user_records_filtered` counts for Codex receipts. A rollout
  with N `user_message` events yields N segments; in headless
  `codex_exec` corpora those are the scripted task prompts.
- **File ops** come from `apply_patch` payloads: Add File → write,
  each Update hunk → an edit op whose old/new blocks include the hunk's
  context lines (they anchor the replace), Delete File → a delete op,
  Update + `Move to:` → a move op (line origins preserved). Patch paths
  are normalised by stripping the session cwd (from `session_meta`), so
  the absolute and relative spellings of one file join as one file.
  Failed patches are dropped whole (see coverage). `patch_apply_end`
  events corroborate outcomes but are not the op source — they are
  missing for exactly the failed calls in observed corpora, and their
  `changes` map undercounts sections versus the patch payloads.
- **Shell mutations** via `exec_command` are extracted only when the
  whole command is unambiguous (lone heredoc `cat >` write, bare
  `rm <path>`); mutation-shaped commands beyond that are counted in
  `shell_writes_unparsed` and never guessed (see the coverage table).
- **Tokens**: the `tokens_*_deduped` fields carry the rollout's final
  cumulative `token_count` totals (input includes cached input). No
  dedupe applies — Codex reports running totals, not per-message usage.
- **Errors**: a segment counts as after-error when the previous segment
  contained an `exec_command` output with a nonzero exit code, a failed
  patch, or a non-`Exit code: 0` tool output. Headless corpora trip
  this routinely (e.g. a search exiting 1 on no match); the field keeps
  its supporting status.
- `--repo` / `--repo-ref` seeding applies unchanged (same replay), for
  rollouts whose workspace repo is on disk.

## Document receipts (`kind: "document"`)

Source: one markdown file's git history (`git log --follow`), in any local
repo. Shipped as-is from the spike. The `harness` field is `"git"` for
this kind: the source is a revision history, not an agent harness, and no
pushback/survival field is computed for documents.

| Field | Type | Meaning |
|---|---|---|
| `source` | string | `<repo> :: <relative path>`. |
| `revisions` | int | Committed versions of the file. 1 = one-shot document. |
| `revision_count` | int | (v1.2, additive) The number of revisions the unchanged shares below were computed over — the same count as `revisions`, recorded alongside the headline because the headline floor is only interpretable together with it (see below). |
| `revision_shas` | array | Short SHAs, oldest first. |
| `final_nonblank_lines` | int | Non-blank lines in the final version. |
| `overall_pct_unchanged_from_first_version` | float\|null | **Headline — a floor, not a point estimate.** At least this share of final lines survives verbatim from the first version: the exact-line rule only ever marks a line rewritten (any edit, even one word, counts as rewritten), and finer revision granularity only lowers the number. Read it as "at least X% of the final text survives verbatim from the first version", and only alongside `revision_count` — the level is strongly granularity-sensitive (CoAuthor, identical writing: 36.7% / 17.1% / 10.0% at 2 / 4 / 6 snapshots; MAE 13.0 pp against keystroke ground truth). It is a steering-presence signal, not a dose measure. |
| `unchanged_sentence_share_pct` | float\|null | (v1.2, additive) Share of final-version sentences appearing verbatim (exact string) among the first version's sentences, splitting both versions into sentences (split after terminal punctuation; heading lines and fragments count as one sentence each). The less granularity-sensitive prose measure: on CoAuthor the sentence-level labels agreed with keystroke ground truth at 88.3% with a false-untouched rate of ~0.05%, where the paragraph-line measure's dominant error is collateral (one edited word marks a whole line rewritten). The line-based share above remains the headline for code-like or short-line documents. |
| `per_section[]` | array | **Headline.** Per heading-delimited section of the final version: `section`, `final_lines`, `pct_unchanged_from_first_version`, `pct_introduced_after_first_version`, `introduced_by_revision` (map of `revN (sha)` → distinct final lines first appearing in that revision). The per-section unchanged shares carry the same floor semantics as the overall headline; their "unchanged" labels are the high-precision part of the map (CoAuthor false-untouched rate ~0.05%). |
| `labels.method` | string | Exact-line provenance; conservative — any edit marks a line rewritten; a moved-but-identical line still counts as unchanged (generous direction, noted in the spike report). |

A "revision" is a commit. The map proves which parts changed after the
first draft and when — steering evidence when revisions correspond to
review rounds, not proof of who typed what.

### Rejection blind spot (doc mode)

Revision history can only show what was written and later changed. It
cannot show rejected suggestions, dismissed drafts, or edits that were
never saved in a revision — that material never entered the history at
all. On CoAuthor, writers dismissed ~25% of opened suggestion panels,
and none of that rejection evidence is visible to document mode.
Document receipts therefore carry no dismissal/rejection fields (unlike
code mode's transcript-derived pushback fields), and doc-mode steering
evidence is a **lower bound on interaction**: a document receipt that
shows little revision does not show that little was rejected.

## Versioning

Any change to a field's meaning, a demotion/promotion, or the seeding
rule bumps the schema id (1.1, 2.0, …). Additive fields bump the minor
version. Receipts state their schema id; renderers must not silently
reinterpret an older receipt under a newer schema.

## Specified, not yet emitted: `commitment`

An optional top-level `commitment` block is fully specified but not
yet emitted by any build, and no receipt produced today carries one.
When implemented (target: the v1 adoption build, behind an opt-in
`--commitment` flag) it records SHA-256 hashes of the exact material a
receipt was derived from (the transcript bytes in code mode, the
revision blob contents in doc mode, plus the reconstructed repo HEAD
in code mode), so a sender who later reveals the material can prove
the receipt was honestly derived from it and was not edited after the
fact. It is additive, so the schema id stays
`proof-of-steering/receipt@1.0`. The full specification, including the
verification procedure and what it does and does not prove, lives in
the project's `specs/hash-commitment.md` (it lands in this repo with
the adoption build).
