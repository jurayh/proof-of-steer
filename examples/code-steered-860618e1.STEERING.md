# STEERING.md — code-steered-860618e1 (code)

_Schema proof-of-steering/receipt@1.0. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._
_Harness: claude-code._
_Validation scope: Validated on trace-commons (28 sessions, full transcript-to-git join, blame agreement ~100%) and local repositories; at-scale validation on SWE-chat (SALT-NLP, 17,968 sessions) completed Oct 2026 with a partial pass: bimodality reproduced approximately (agent-all mode 40.9% vs published 41%), pushback reproduced on the dominant agent (49.2% vs ~50% for Claude Code excluding first turns; pooled 39.6-40.7% and agent-mix-sensitive), survival not reproduced (metric-v2 aggregate 53.4% vs published 59%; per-agent survival 25-97%, so survival stays a context field, stratified by agent where known). post_first_prompt_share is validated as a steering-presence detector (SWE-chat medians: 0.0 one-prompt, 0.75 continued no-pushback, 0.97 pushback sessions), not a steering-dose measure; at SWE-chat scale it was computed as the gross-added-lines analogue of this field's final-lines definition (see swe-chat/VALIDATION.md section 6). Document mode ground-truth-tested on CoAuthor (1,447 human-GPT-3 writing sessions, CHI 2022): per-part 'unchanged from first version' labels validated (sentence-level agreement 88.3%, false-untouched rate ~0.05%); the doc headline % unchanged is a floor on the untouched share, not a dose estimate (mean absolute error 13.0 pp against keystroke truth, sensitive to revision granularity). Document receipts contain no rejection evidence: material rejected or dismissed before it ever entered a revision is invisible to doc mode, so doc-mode steering evidence is a lower bound on interaction (see coauthor/VALIDATION-coauthor.md). Impact classification (v1.4, from the Oct 2026 impact spike): segments are also classified by measured effect on the artifact (procedural, continuation, reshaping, unmeasured) from line provenance alone. Reshaping share separated steered sessions from near-one-prompt controls at AUC 0.929, against 0.602 for the keyword correction segment share and 0.616 for the keyword line share; every control session measured exactly 0 reshaping segments. In interactive Claude Code sessions 52.8% of human turns are procedural (no file effect), so raw turn counts overstate steering roughly twofold. Scope caveat: reshaping detects inter-segment rework, and reads as human steering only when the segments are genuine human turns; in the headless Codex batch the follow-up prompts were a pre-written escalation ladder fired on schedule, and reshaping there (median share 66.7%) measures the scripted schedule and agent self-repair, not a human steering._
- Steering mark: **Closely steered**. 40 human turns; 11 of them reshaped earlier work (27.5% of turns, 344 earlier lines rewritten). The mark names the process shape, not a grade.

- Human turns: **40** (correction-keyword: 12, after-error: 6, rubber-stamp: 0)
- Injected user records filtered: 0
- Active time: 111.3 min (wall 121.2 min)
- Tokens (deduped by message id): in 563, out 102921
- Verification lanes: test-like shell 0, shell total 38, browser-lane 0
- Coverage: 22 writes, 48 edits — applied on transcript base 19, applied on repo-seeded base 0 (0 files seeded), unapplied no-base 13, unapplied no-match 16. A low-coverage receipt should be discounted by its reader.

## Git join (the part authorship cannot tell you)

- Final artifact: 21 files, 2907 non-blank lines
- First artifact-producing segment: segment 0
- Share of HEAD introduced after that segment (headline): **86.4%**
- Share of HEAD that is pre-existing (seeded from repo): 0.0%
- First-segment survival into HEAD (context; saturates on greenfield corpora): 100.0%
- Share of HEAD from correction / after-error segments (supporting; noisy, read with turn count): 35.1%
- Blame vs in-memory provenance agreement: 99.5%
- Impact classes (measured effect from line provenance, never prompt wording): 16 procedural, 5 continuation, 11 reshaping (344 earlier lines rewritten), 8 unmeasured, 9 redirect
- Impact scope: Impact classes measure inter-segment rework. The segments of this receipt are the human's own typed inputs in an interactive Claude Code session, so reshaping reads as human steering: a later input changed what an earlier input produced.
- Decisions (structured questions the agent asked and the user answered): 5 answered questions, of which 0 followed the marked recommendation (marked on 0 questions), 5 chose a different listed option, and 0 were answered in free text. 0 question calls were rejected as posed.
- Decision coverage: 0 errored calls, 0 dismissed calls, 0 calls with unparseable recorded input, 0 unparseable answers.
- Decision scope: Decision fields count the structured questions the agent asked and the user answered. Followed and diverged are defined only where the agent marked a recommended option, and decisions_with_recommendation is their denominator: agents mark inconsistently (4% of questions in one validated corpus, 40% in another). A listed pick on an unmarked question counts as diverged_to_listed and means only that the user chose among the offered options. Free-text answers mean the user left the offered options entirely. Sessions where the agent never asks have zero decision points, which says nothing about steering through ordinary turns.

## Per-segment attribution

| segment | prompt chars | correction? | after error? | ops | lines introduced | lines surviving to HEAD |
|---|---|---|---|---|---|---|
| 0 | 16 | — | — | 2 | 395 | 395 |
| 1 | 6630 | yes | yes | 3 | 0 | 0 |
| 2 | 42 | — | yes | 0 | 0 | 0 |
| 3 | 47 | — | — | 5 | 403 | 174 |
| 4 | 41 | — | — | 0 | 0 | 0 |
| 5 | 392 | yes | — | 1 | 221 | 221 |
| 6 | 48 | — | — | 0 | 0 | 0 |
| 7 | 494 | — | — | 1 | 2 | 1 |
| 8 | 9801 | yes | yes | 4 | 280 | 280 |
| 9 | 52 | yes | — | 0 | 0 | 0 |
| 10 | 53 | — | — | 0 | 0 | 0 |
| 11 | 126 | — | — | 1 | 1 | 1 |
| 12 | 17193 | yes | — | 4 | 520 | 513 |
| 13 | 180 | — | — | 11 | 685 | 680 |
| 14 | 37 | — | — | 0 | 0 | 0 |
| 15 | 18 | yes | — | 2 | 2 | 2 |
| 16 | 56 | — | — | 0 | 0 | 0 |
| 17 | 38 | — | — | 0 | 0 | 0 |
| 18 | 17 | — | — | 0 | 0 | 0 |
| 19 | 145 | — | — | 4 | 238 | 233 |
| 20 | 36 | — | — | 1 | 0 | 0 |
| 21 | 26 | — | — | 0 | 0 | 0 |
| 22 | 1093 | yes | — | 1 | 0 | 0 |
| 23 | 800 | yes | — | 0 | 0 | 0 |
| 24 | 544 | — | — | 2 | 156 | 153 |
| 25 | 65 | yes | — | 0 | 0 | 0 |
| 26 | 35 | — | — | 0 | 0 | 0 |
| 27 | 59 | — | — | 7 | 105 | 105 |
| 28 | 58 | — | yes | 2 | 5 | 5 |
| 29 | 18123 | yes | — | 0 | 0 | 0 |
| 30 | 96 | — | — | 6 | 11 | 11 |
| 31 | 86 | yes | — | 1 | 0 | 0 |
| 32 | 54 | yes | — | 2 | 0 | 0 |
| 33 | 47 | — | — | 3 | 0 | 0 |
| 34 | 58 | — | — | 2 | 0 | 0 |
| 35 | 88 | — | — | 0 | 0 | 0 |
| 36 | 47 | — | yes | 0 | 0 | 0 |
| 37 | 39 | — | yes | 1 | 0 | 0 |
| 38 | 63 | — | — | 2 | 53 | 53 |
| 39 | 43 | — | — | 2 | 80 | 80 |
