# Proof of Steering — receipt schema

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
`receipt@1.0`.
v1.4 changes Oct 22, 2026 (the adoption build) are likewise purely additive:
document mode runs on history providers and gains `provider`,
`history_complete`, `authors`, and `section_strategy`; code receipts gain
`git_join.impact` effect classes and per-segment impact rows; both kinds
gain the `mark` field; and the `commitment` block specified below is now
emitted behind the opt-in `--commitment` flag, so the schema id stays
`receipt@1.0`.
The decisions adoption (Oct 25, 2026) is likewise purely additive: code
receipts gain a top-level `decisions` block (see the decision points
section below) and document receipts are unchanged, so the schema id
stays `receipt@1.0`.)
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
| `validation_scope` | string | What the field set has been validated on so far. Current text (updated Oct 22, 2026 after the SWE-chat run and extended the same day with the CoAuthor result, full text in `steering_receipt.py`): validated on trace-commons (28 sessions, full join, blame ~100%) and local repositories; at-scale SWE-chat validation completed with a partial pass — bimodality approximately reproduced (40.9% vs 41%), pushback reproduced on the dominant agent (49.2% vs ~50%, Claude Code excl. first turns; pooled mix-sensitive), survival not reproduced (53.4% vs 59% under the dataset's metric-v2; per-agent 25–97%, so survival stays a context field stratified by agent). `post_first_prompt_share_pct` is validated as a steering-presence detector, not a dose measure. Document mode ground-truth-tested on CoAuthor (1,447 sessions): per-part map validated (sentence agreement 88.3%, false-untouched ~0.05%); headline % unchanged is a floor, not a dose estimate (MAE 13.0 pp, granularity-sensitive); document receipts contain no rejection evidence. Evidence: `~/workspace/proof-of-steering/swe-chat/VALIDATION.md` and `~/workspace/proof-of-steering/coauthor/VALIDATION-coauthor.md`. |
| `labels` | object | `receipt_nature` is always "descriptive evidence, not a certified grade". Code receipts add `semantic_weights` (always "none" in v1 — all categories are rule-based) and `field_status` summarising the demotions below. Doc receipts add `method`. |
| `mark` | object | (v1.4, additive) The steering mark: `category` (one of One-shot, Prompted, Steered, Closely steered) and `basis` (one sentence naming the counts the category was computed from). Doc marks add `reshaped_sections` and `sections`. The mark names the process shape, how the work was steered, and is not a grade: it says nothing about quality, and a One-shot artifact can be exactly right. See "The steering mark" below for the definitions. |
| `commitment` | object | (v1.4, additive; only when generated with `--commitment`) Hash commitment over the exact material the receipt was derived from. See the `commitment` section below. Never present when the flag was not passed; never null, never empty. |

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
| `git_join.impact` | object | headline (v1.4) | Effect-based segment classification (see the impact section below): `procedural_turns`, `continuation_turns`, `reshaping_turns`, `unmeasured_segments`, `reshaping_share_pct`, `reshaping_lines`, `redirect_segments`, `method`, and `scope` (the scope label keyed to the segment source). |
| `decisions` | object | supporting (decisions adoption) | Structured questions the agent asked and the user answered (AskUserQuestion events; see the decision points section below): `decision_points`, `decisions_with_recommendation`, `followed_recommendation`, `diverged_to_listed`, `free_text_answers`, `rejected_decision_calls`, a `coverage` object (errored, dismissed, and input-unparseable calls, plus unparseable answers), `method`, and `scope`. Code receipts only. |
| `capture` | object | supporting (capture adoption) | Capture-time steering records read from the repo's git notes under `refs/notes/steer` (see the capture section below): the coverage split `captured_segments`, `inferred_segments`, and `unmeasured_segments` over `segments_total`, plus `commits_with_records`, `session_match`, a `verification` object with the tier and per-tier counts, a `per_segment` list marking each segment's origin, `method`, and `scope`. Present only when a capture repo is in play (the CLI passes `--repo` by default, or `--capture-repo` explicitly). Never present on receipts built without one, and never on document receipts. Codex receipts carry the block as zeros with a scope note, because capture records are written from Claude Code sessions in this build. |
| `mechanistic.session_origin` | object | context (v1.4, Codex only) | The rollout's `session_meta` origin metadata, `originator` and `source` (for example `codex_exec` / `exec` for unattended runs). Keys the impact scope label; absent when the rollout carries none. |
| `git_join.per_segment[]` | array | headline | One row per segment: `segment` (index; −1 = pre-existing seed pseudo-segment, with `kind` set), `prompt_chars` (length only, never text), `correction_keyword`, `after_error`, `rubber_stamp`, `edit_write_ops`, `lines_introduced_gross`, `lines_surviving_to_head`. Human-segment rows add (v1.4) `impact_class`, `redirect`, and `overlap_earlier_lines`. |
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

### Impact classes (v1.4)

Every human segment is classified by its **measured effect** on the
artifact, computed from the replay's line provenance. Prompt text is
never read for the classification (the keyword counts stay as a
supporting field; the impact spike found the two detectors
complementary, failing in near-disjoint ways).

- `procedural_turns`: segments with no file ops attributed (approvals,
  answers, discussion, shell-only turns). In interactive Claude Code
  sessions 52.8% of turns are procedural, so a raw turn count overstates
  steering roughly twofold before any other correction.
- `continuation_turns`: segments whose applied ops only added lines,
  touching no line an earlier segment introduced.
- `reshaping_turns`: segments where an applied op edited or deleted at
  least one line an earlier segment introduced (or deleted a file
  containing such lines). A Codex patch hunk counts only the lines it
  removes, never its context lines.
- `unmeasured_segments`: segments with ops attributed but none applied
  in the replay (no base, no string match). Always printed beside the
  other counts, never folded into them; a receipt with many unmeasured
  segments discounts itself, as low coverage does.
- `reshaping_share_pct`: reshaping turns as a share of human turns.
- `reshaping_lines`: total earlier-segment lines edited or deleted by
  reshaping segments, so a 1-line touch and a 41-line rewrite do not
  weigh the same.
- `redirect_segments`: non-first human segments that were the first to
  produce a file (an orthogonal first-touch count; a segment can be
  both a redirect and any class above).

Validation (impact spike, Oct 2026): reshaping share separated steered
sessions (10+ turns) from near-one-prompt controls at AUC 0.929,
against 0.602 for the keyword correction segment share and 0.616 for
the keyword line share; every control measured exactly 0 reshaping
segments. Code receipts carry the impact paragraph in their
`validation_scope` text.

**Scope label.** `git_join.impact.scope` states what the classes may be
read as, keyed to the segment source the adapter knows. The classes
measure inter-segment rework; they read as human-steering evidence
only when the turns are genuine human input. For interactive Claude
Code sessions the label says exactly that. For Codex rollouts whose
`session_meta` origin is an unattended exec run (`originator:
codex_exec` or `source: exec`), the label says the turns are scripted
task prompts and reshaping measures the scripted schedule and agent
self-repair, not a human steering: in the headless batch the follow-up
prompts were a pre-written escalation ladder fired on schedule, and
reshaping there (median share 66.7%) is dense by construction. For
Codex rollouts without usable origin metadata, the label prints the
general caution.

### Decision points (decisions adoption)

Code receipts carry a top-level `decisions` block counting the
structured questions the agent asked and the user answered: Claude
Code `AskUserQuestion` calls, paired with their tool results and
classified by the chosen answer. The block makes behavior at offered
forks visible, including the rubber-stamp pattern where a user takes
every recommended option and never answers in their own words. It
complements the turn-level impact classes, which only see steering
after a draft exists: a user who steers well at the forks may show
little reshaping precisely because the rework never became
necessary.

Fields:

- `decision_points`: answered questions. Errored, rejected,
  dismissed, and input-unparseable calls never contribute.
- `decisions_with_recommendation`: of those, the questions where one
  option was marked "(Recommended)". This is the only denominator
  for followed and diverged rates.
- `followed_recommendation`: the chosen answer equals the marked
  option.
- `diverged_to_listed`: the chosen answer equals a different listed
  option. On questions where no recommendation was marked, any
  listed pick lands here. Multi-select picks that split cleanly
  into listed labels also land here.
- `free_text_answers`: the chosen answer matches no listed label,
  meaning the user left the offered options entirely.
- `rejected_decision_calls`: calls the user refused as posed (the
  result records the refusal). The unit is calls, because a refused
  call never decomposes into answered questions. Refusal is a
  steering act in its own right, so it ships as a field rather than
  only as coverage.

Coverage companions, always printed beside the fields (the
`unmeasured_segments` precedent): `coverage.errored_decision_calls`
(the tool call failed and the question never reached the user),
`coverage.dismissed_decision_calls` (the user dismissed the question
with no response), `coverage.input_unparseable_decision_calls` (the
recorded call input could not yield a question list), and
`coverage.unparseable_answers` (answered questions whose answer
could not be classified, with `decision_points` counting them). A receipt
whose decision coverage is thin discounts itself.

**Scope label.** `decisions.scope` states what the counts may be
read as. Decision fields count the structured questions the agent
asked and the user answered. Followed and diverged are defined only
where the agent marked a recommended option, and
`decisions_with_recommendation` is their denominator: agents mark
inconsistently (4% of questions in one validated corpus, 40% in
another), so a listed pick on an unmarked question is not evidence
about recommendations. Free-text answers mean the user left the
offered options entirely. Sessions where the agent never asks have
zero decision points, which says nothing about steering through
ordinary turns. For Codex receipts the label states instead that
decision events are an interactive Claude Code phenomenon: the
validated Codex rollouts are unattended runs and contain none, so
the block reads zero rather than being omitted, so absence is
visible and not silent.

**The steering mark does not use these fields.** In this build the
mark is computed exactly as before, from the presence-level impact
fields only. The decisions block is reported evidence for the
reader, not a mark input.

Validation (decision-points spike, Oct 2026): 10,763 answered
questions pooled across SWE-chat (12,418 Claude Code sessions) and
trace-commons (28 sessions), with 3.08% unparseable. All 24
trace-commons questions were hand-checked against the raw records
and agreed with the extractor. Decision points appear in 26 to 30%
of interactive sessions with at least five turns. Within questions
where a recommendation was marked, users followed it 70.7% of the
time, picked a different listed option 16.2%, and answered in free
text 12.8%. Whether the never-diverged pattern predicts low
reshaping could not be tested with the corpora in hand, and no
such claim is made.

Honest limits: the fields measure behavior at offered forks only,
and an agent that never asks produces no decision points however
steered the session was. Free-text answers are heterogeneous
(premise corrections, fetched values, pasted material, and
counter-questions all land there) and reliably mean only that the
user left the menu. Taking the recommended option is not proof of
passivity, and diverging is not proof that the choice changed the
artifact.

### Capture-time steering records (capture adoption)

Everything above this section is reconstructed after the fact: the
transcript is replayed, one commit per segment is rebuilt, and line
provenance is joined against git blame. That join is inference, and
the receipts say so. Capture is the opposite direction. At commit
time, while the session is live or just finished, the tool writes a
steering record as the commit's git note under `refs/notes/steer`,
stating which segments landed in that commit and what each segment
measurably did. A later receipt then separates captured segments
from inferred ones and prints the split always.

The record format (schema id
`proof-of-steering/steering-record@0.1-spike`, frozen by the
capture spike and unchanged by this adoption):

| Field | Meaning |
|---|---|
| `schema` | Always `proof-of-steering/steering-record@0.1-spike`. |
| `commit` | The commit the record is anchored to. A record claims its segments only for the commit named here. |
| `harness` | The harness the session ran in (`claude-code` in this build). |
| `captured_at` | UTC timestamp of the attach that wrote the record. |
| `tool` | The tool and version that wrote the record. |
| `segments[]` | One entry per recorded human-turn segment: `turn` (the segment index in the transcript), `impact_class`, `redirect`, and `overlap_earlier_lines` (the same effect-based classification the receipt computes, measured at capture time), `decisions` (decision entries in the shape below), `hunks` (the spans below), and `transcript_sha256` (the SHA-256 of that segment's raw transcript bytes). |

A segment's `decisions` entries mirror the receipt's decision
classification at capture time: each entry carries a `status`, and
answered entries carry `questions`, one per question, each with a
`class` (one of followed_recommendation, diverged_to_listed,
free_text, unparseable) and `with_recommendation` (whether the agent
marked a recommended option). Only the class and the flag are
stored. The classifier computes the chosen answer text and the
recorder discards it before writing.

A segment's `hunks` entries carry `file`, `start`, and `lines` for
the new side of the commit's diff, and `removed_start` and
`removed_lines` for the old side, in the span conventions of
`git diff -U0`: a side with zero lines names the line before the
span. Hunk attribution at attach time is deliberately conservative.
Additions are claimed only for segments the session replay assigns
the surviving lines to, removals only where a segment's replay
removed the same line text, and anything else in the diff (hand
edits, other sessions, pre-existing content) is claimed by nobody.
Records under-claim rather than over-claim.

Privacy, absolute: a record holds ids, hashes, counts, timestamps,
and line spans only. Never transcript text, never prompt text, never
file contents, never question or answer text. The one string from
the work itself is a file path in a hunk entry, and that path is
already in the commit the record rides on.

#### The capture block on code receipts

The block is emitted only when a capture repo is in play, so
receipts built without one are exactly as before. Its fields:
`method`, `segments_total` (the receipt's human segments),
`captured_segments`, `inferred_segments`, and `unmeasured_segments`
(the coverage split, which always sums to `segments_total` and is
always printed, in the block and in STEERING.md),
`commits_with_records` (commits carrying a note under
`refs/notes/steer`), `session_match`, `verification` (below),
`per_segment` (one row per human segment: `origin`, one of captured,
inferred, or unmeasured, and for captured rows the `commit` and the
`impact_class_recorded`, printed beside the receipt's own inferred
class and never substituted for it), and `scope`. If the capture
analysis itself fails, the block carries the zero counts plus a
`capture_error` string rather than failing the receipt.

A segment counts as captured only when all three hold: a record
claims its turn, the record is anchored to the commit that carries
it (and that commit is in the receipt repo's current history), and
the recorded segment hash equals the hash of this transcript's
segment bytes. Counting is per segment, so a receipt can mix
captured and inferred segments from one session recorded across
several commits.

#### The two verification tiers

Verification language keeps two tiers distinct, in this schema, in
STEERING.md, and in the notes-only receipt. The tiers are never
blurred, and the tier a receipt or record set carries is always the
strongest tier whose checks all pass.

- **Verified against the transcript.** The segment hashes were
  recomputed from the held transcript bytes and matched, the
  recorded classes were compared against a full replay of the
  transcript, and the recorded hunks were checked against the
  commit diffs. This tier needs the transcript, which is the
  private material: it never leaves the machine, and the receipt
  travels without it.
- **Verified against the commit.** Only the diff-side checks ran:
  the records parse, their anchors name the commits that carry
  them, no segment is claimed twice within the current history, and
  every recorded hunk is span-consistent with its commit's diff.
  Class claims get only necessary-condition shape checks at this
  tier: a segment recorded as procedural must carry no hunks, and a
  segment recorded as reshaping must remove lines in a file an
  earlier recorded segment touched, a condition evaluated only
  where the commit's diff carries removal evidence for the
  segment's files. This tier proves the recorded hunks are really
  in the commit. It does not prove the recorded classes are right:
  a class lie passes this tier and fails the transcript tier, and
  the spike demonstrated both directions.

Span-consistency is a subset check, not an equality check: every
position a recorded hunk claims must appear among the diff's
positions for that file, and the record never has to exhaust the
diff, because one commit can carry several segments, hand edits,
and work from other sessions. Verification reports the claimed and
total diff positions per commit, so incompleteness is visible
rather than hidden.

#### The notes-only partial receipt

`proof-of-steer notes REPO` builds a partial receipt from records
alone, with no transcript read. It carries `notes_only: true`, the
same schema id, per-commit blocks (recorded classes, decision
outcomes, and a per-commit mark over that commit's recorded
segments), an aggregate `mark` labelled by `mark_scope` as an
aggregate over recorded segments only, an aggregate `decisions`
block counted from the recorded entries, and a `capture` block with
the record count and the verification tier, which is verified
against the commit at most. Transcript-derived fields
(`transcript_sha256`, `mechanistic`, `git_join`) are present as
null and named in `unavailable_fields`: unavailable rather than
zero. The markdown is headed as a notes-only partial receipt and
says the same. Output files are `<label>.notes.receipt.json` and
`<label>.notes.STEERING.md`.

#### Rewrites: what happens to records

`capture init` writes `notes.rewriteRef` covering
`refs/notes/steer`, so where git supports note rewriting it copies
a commit's record onto the rewritten commit on amend and rebase.
Three consequences, all verified against the shipped code:

- The copied record still names the pre-rewrite commit inside
  itself. That anchor is stale, verification flags it at the anchor
  check, and the next `capture attach` on the rewritten commit
  re-anchors the record and reports that it did so.
- A rewrite that changes the commit's diff (a content amend, a
  rebase that resolves differently) can move lines out from under
  the recorded hunks. The record follows, the anchor is repaired by
  the next attach, and the diff check then flags the hunks whose
  claimed positions no longer exist in the new diff. That flagging
  is the honest outcome: the record described the pre-rewrite diff.
- The pre-rewrite commit keeps its note. Orphaned notes stay in the
  notes ref's own history, claim nothing in the current history, and
  still verify against their own commit.

Out of scope in this build: whether git copies notes on squash and
cherry-pick depends on the git version and the exact command shape,
and no claim is made either way. A deleted note reads as not
captured, indistinguishable from a commit that never had one.
Records are only as trustworthy as the repo carrying them: anyone
with write access to the notes ref can rewrite a record, and the
transcript tier is the check that catches class and hunk lies,
because the segment hashes bind each record to transcript bytes
the rewriter would also need.

How sessions map to commits in this build: one attach writes one
record on one commit, attributing to that commit whatever of the
session's work its diff contains. Attaching at several commits
during a session yields per-commit records. Work that was never
committed is in no commit's diff, so no record can claim it.

## The steering mark (v1.4)

The `mark` field distils a receipt into one category word plus its
basis. The vocabulary is fixed: **One-shot**, **Prompted**, **Steered**,
**Closely steered**. The definitions are mechanical, computed only
from the presence-level fields above (never from survival or keyword
shares):

Code mode:

- **One-shot**: no follow-up human segment changed the artifact (every
  follow-up is procedural or unmeasured).
- **Prompted**: follow-ups changed the artifact, but `reshaping_turns`
  is 0: the follow-up work only ever added.
- **Steered**: `reshaping_turns` is at least 1.
- **Closely steered**: `reshaping_turns` is at least 3 and
  `reshaping_share_pct` is at least 20.

Document mode (a section counts as reshaped when it existed in the
first version, some of its first-version lines survive, and later
revisions also introduced lines into it):

- **One-shot**: a single revision.
- **Prompted**: later revisions only added sections; no existing
  section was reshaped.
- **Steered**: at least one section was reshaped.
- **Closely steered**: reshaped sections are at least half of all
  sections, or the unchanged floor is under 50%.

The mark names the process shape and is not a grade. It ranks nothing:
One-shot work can be exactly right and Closely steered work can still
be wrong. It exists so a reader can price their attention in one word
and then read the receipt for the evidence. STEERING.md renders the
mark as a header line with its basis, and `steering_viz.py --badge`
emits it as a small SVG badge (word plus the mini Steerprint strip for
code receipts, word plus revision count for document receipts).

## Document receipts (`kind: "document"`)

Source: the revision history of one document, read through a **history
provider** (v1.4). The `harness` field names the provider for this
kind: `"git"` for a git history, `"gdrive-doc"` or `"folder"` for the
other registered providers. No pushback/survival field is computed for
documents.

Providers live in `providers/`, one module plus one registration line
per source (see `../gdocs-spike/PROVIDER-DESIGN.md` for the contract):
`git` (a file's `git log --follow` history in a local repo), `gdrive-doc`
(Google Docs revisions via the Drive API, with an injectable transport
seam for offline tests), and `folder` (a directory of versioned files,
`notes.v1.md`, `notes.v2.md`, ...). The CLI's `doc` subcommand takes
`--provider`; by default the provider is inferred from the reference
(a document path means git, a directory means folder, a bare id means
gdrive-doc), and the git path stays the default UX.

| Field | Type | Meaning |
|---|---|---|
| `source` | string | `<repo> :: <relative path>` for git; `folder :: <dir>` or `gdrive-doc :: <file id>` for the other providers. |
| `provider` | string | (v1.4, additive) The history provider that produced the snapshots: `git`, `gdrive-doc`, or `folder`. |
| `history_complete` | bool\|null | (v1.4, additive) Whether the provider can promise the snapshot list is the artifact's full history. Git promises it for a full clone and reports `false` for a shallow clone (checked with `git rev-parse --is-shallow-repository`); the folder provider promises it (the directory is the whole source of record); gdrive-doc reports `false` because the Drive API warns its revision list may be truncated. A receipt computed over an incomplete history baselines at the first available revision, and its unchanged floor must be read with that caveat. |
| `authors` | array | (v1.4, additive) Distinct snapshot authors in first-appearance order, when the provider knows them (per-commit authors for git, `lastModifyingUser` for gdrive-doc; the folder provider knows none and the field is empty). Coverage metadata, never a join input. |
| `section_strategy` | string | (v1.4, additive) The sectioning strategy that actually produced the per-section map: `markdown`, `heuristic`, or `whole`. See the sectioning note below. |
| `revisions` | int | Committed versions of the file. 1 = one-shot document. |
| `revision_count` | int | (v1.2, additive) The number of revisions the unchanged shares below were computed over — the same count as `revisions`, recorded alongside the headline because the headline floor is only interpretable together with it (see below). |
| `revision_shas` | array | Short SHAs, oldest first. |
| `final_nonblank_lines` | int | Non-blank lines in the final version. |
| `overall_pct_unchanged_from_first_version` | float\|null | **Headline — a floor, not a point estimate.** At least this share of final lines survives verbatim from the first version: the exact-line rule only ever marks a line rewritten (any edit, even one word, counts as rewritten), and finer revision granularity only lowers the number. Read it as "at least X% of the final text survives verbatim from the first version", and only alongside `revision_count` — the level is strongly granularity-sensitive (CoAuthor, identical writing: 36.7% / 17.1% / 10.0% at 2 / 4 / 6 snapshots; MAE 13.0 pp against keystroke ground truth). It is a steering-presence signal, not a dose measure. |
| `unchanged_sentence_share_pct` | float\|null | (v1.2, additive) Share of final-version sentences appearing verbatim (exact string) among the first version's sentences, splitting both versions into sentences (split after terminal punctuation; heading lines and fragments count as one sentence each). The less granularity-sensitive prose measure: on CoAuthor the sentence-level labels agreed with keystroke ground truth at 88.3% with a false-untouched rate of ~0.05%, where the paragraph-line measure's dominant error is collateral (one edited word marks a whole line rewritten). The line-based share above remains the headline for code-like or short-line documents. |
| `per_section[]` | array | **Headline.** Per heading-delimited section of the final version: `section`, `final_lines`, `pct_unchanged_from_first_version`, `pct_introduced_after_first_version`, `introduced_by_revision` (map of `revN (sha)` → distinct final lines first appearing in that revision). The per-section unchanged shares carry the same floor semantics as the overall headline; their "unchanged" labels are the high-precision part of the map (CoAuthor false-untouched rate ~0.05%). |
| `labels.method` | string | Exact-line provenance; conservative — any edit marks a line rewritten; a moved-but-identical line still counts as unchanged (generous direction, noted in the spike report). |

A "revision" is a commit (or the provider's equivalent snapshot). The
map proves which parts changed after the first draft and when —
steering evidence when revisions correspond to review rounds, not
proof of who typed what.

### Sectioning strategies (v1.4)

Plain-text exports (the Google Docs shape) drop markdown heading
markers, and a heading-less export fed to the markdown sectioner
collapses into one "(preamble)" section, losing the per-section map.
The join therefore sections the final version by a strategy, selected
with `--section-strategy` (default `auto`) and recorded in the
receipt's `section_strategy` field and `labels.method`:

- `markdown`: split on `#{1,3}` heading lines (v1 behaviour).
- `heuristic`: conservative heading-like line detection over plain
  text. A line qualifies when it is short (at most 80 characters and
  12 words), contains a letter, does not end in terminal punctuation
  (`. ! ? ; :`), follows a blank line or the start of the text, and is
  not a list item, table row, blockquote, or code fence. Tuned on a
  real heading-less export (the Personal-Guard findings draft with its
  markers stripped), where it recovered 17 of 18 headings with zero
  false positives; the one miss is the 103-character title, over the
  length cap by design. A heuristic map is softer evidence than a
  marked one, and `labels.method` says so whenever this strategy ran.
- `whole`: one "(whole document)" section. The fallback when nothing
  qualifies; the overall floor and sentence share are still computed.

`auto` resolves to `markdown` when heading markers exist, else
`heuristic` when at least two heading-like lines qualify, else
`whole`. Below two candidates the evidence for a map is too thin, so
the whole-document fallback is the default behaviour and the heuristic
is reachable per run with `--section-strategy heuristic`.

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

## Emitted behind a flag: `commitment` (v1.4)

An optional top-level `commitment` block, emitted only when the
receipt was generated with `--commitment` (both subcommands; default
off, because the binding to one exact byte stream is a deliberate act:
re-exported or redacted transcripts change the hash and orphan every
receipt committed against the earlier bytes). It records SHA-256
hashes of the exact material the receipt was derived from, computed by
the CLI in the same run from the same in-memory material it parsed;
there is no mode that adds a commitment to an existing receipt.

Fields (all digests lowercase hex, never truncated in the JSON):

- `algorithm`: always `"sha256"`.
- Code mode: `transcript_sha256` (over the exact session bytes the CLI
  read; deliberately duplicates the top-level field so the block is
  verifiable as a unit, and a receipt where they differ is malformed),
  `repo_head_sha` (HEAD of the reconstructed repo), `seed_repo_head_sha`
  (only when `--repo` was supplied and resolves to a commit), and
  `artifact_file_sha256` (a map of every reconstructed HEAD file's
  path to the SHA-256 of its blob bytes; this build always emits it).
- Document mode: `revision_content_sha256` (one digest per revision,
  oldest first, parallel to `revision_shas`; for git, over the stored
  blob bytes from `git cat-file`; for other providers, over the
  snapshot text as UTF-8, the only byte string those sources define)
  and `final_content_sha256` (the last digest, duplicated as an
  anchor).

Under the flag, reconstructed-repo commits are created with author
and committer dates pinned to each segment's first transcript
timestamp (fallback chain: the first parseable timestamp in the
transcript, then the epoch), and the reconstructed repo is rebuilt
from scratch, so a verifier's re-run reproduces `repo_head_sha`
exactly. STEERING.md renders exactly one commitment line with
12-character truncated digests.

Verification, in brief (full procedure in the project's
`specs/hash-commitment.md` section 6; worked walkthrough in
BUILD-NOTES.md): the sender reveals the material; the verifier hashes
it and stops on any mismatch, re-runs the CLI with `--commitment` and
the same seeding inputs, and diffs every field (volatile exceptions:
`label`, and `git_join.reconstructed_repo_local_path`, which is
machine-local). A full match proves the receipt was derived by this
CLI from exactly that material and was not edited after the fact. It
does not prove the material itself is authentic: a fabricated
transcript committed early is still fabricated. The commitment is not
a signature, and must not be described as one.
