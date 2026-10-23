# STEERING.md — code-oneprompt-4130c9a7 (code)

_Schema proof-of-steering/receipt@1.0. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._
_Harness: claude-code._
_Validation scope: Validated on trace-commons (28 sessions, full transcript-to-git join, blame agreement ~100%) and local repositories; at-scale validation on SWE-chat (SALT-NLP, 17,968 sessions) completed Oct 2026 with a partial pass: bimodality reproduced approximately (agent-all mode 40.9% vs published 41%), pushback reproduced on the dominant agent (49.2% vs ~50% for Claude Code excluding first turns; pooled 39.6-40.7% and agent-mix-sensitive), survival not reproduced (metric-v2 aggregate 53.4% vs published 59%; per-agent survival 25-97%, so survival stays a context field, stratified by agent where known). post_first_prompt_share is validated as a steering-presence detector (SWE-chat medians: 0.0 one-prompt, 0.75 continued no-pushback, 0.97 pushback sessions), not a steering-dose measure; at SWE-chat scale it was computed as the gross-added-lines analogue of this field's final-lines definition (see swe-chat/VALIDATION.md section 6). Document mode ground-truth-tested on CoAuthor (1,447 human-GPT-3 writing sessions, CHI 2022): per-part 'unchanged from first version' labels validated (sentence-level agreement 88.3%, false-untouched rate ~0.05%); the doc headline % unchanged is a floor on the untouched share, not a dose estimate (mean absolute error 13.0 pp against keystroke truth, sensitive to revision granularity). Document receipts contain no rejection evidence: material rejected or dismissed before it ever entered a revision is invisible to doc mode, so doc-mode steering evidence is a lower bound on interaction (see coauthor/VALIDATION-coauthor.md). Impact classification (v1.4, from the Oct 2026 impact spike): segments are also classified by measured effect on the artifact (procedural, continuation, reshaping, unmeasured) from line provenance alone. Reshaping share separated steered sessions from near-one-prompt controls at AUC 0.929, against 0.602 for the keyword correction segment share and 0.616 for the keyword line share; every control session measured exactly 0 reshaping segments. In interactive Claude Code sessions 52.8% of human turns are procedural (no file effect), so raw turn counts overstate steering roughly twofold. Scope caveat: reshaping detects inter-segment rework, and reads as human steering only when the segments are genuine human turns; in the headless Codex batch the follow-up prompts were a pre-written escalation ladder fired on schedule, and reshaping there (median share 66.7%) measures the scripted schedule and agent self-repair, not a human steering._
- Steering mark: **One-shot**. 1 human turn; no follow-up turn changed the artifact. The mark names the process shape, not a grade.

- Human turns: **1** (correction-keyword: 0, after-error: 0, rubber-stamp: 0)
- Injected user records filtered: 2
- Active time: 16.3 min (wall 16.3 min)
- Tokens (deduped by message id): in 128, out 61371
- Verification lanes: test-like shell 0, shell total 8, browser-lane 0
- Coverage: 28 writes, 11 edits — applied on transcript base 10, applied on repo-seeded base 0 (0 files seeded), unapplied no-base 1, unapplied no-match 0. A low-coverage receipt should be discounted by its reader.

## Git join (the part authorship cannot tell you)

- Final artifact: 28 files, 3113 non-blank lines
- First artifact-producing segment: segment 0
- Share of HEAD introduced after that segment (headline): **0.0%**
- Share of HEAD that is pre-existing (seeded from repo): 0.0%
- First-segment survival into HEAD (context; saturates on greenfield corpora): 100.0%
- Share of HEAD from correction / after-error segments (supporting; noisy, read with turn count): 0.0%
- Blame vs in-memory provenance agreement: 100.0%
- Impact classes (measured effect from line provenance, never prompt wording): 0 procedural, 1 continuation, 0 reshaping (0 earlier lines rewritten), 0 unmeasured, 0 redirect
- Impact scope: Impact classes measure inter-segment rework. The segments of this receipt are the human's own typed inputs in an interactive Claude Code session, so reshaping reads as human steering: a later input changed what an earlier input produced.

## Per-segment attribution

| segment | prompt chars | correction? | after error? | ops | lines introduced | lines surviving to HEAD |
|---|---|---|---|---|---|---|
| 0 | 818 | — | — | 39 | 3123 | 3113 |
