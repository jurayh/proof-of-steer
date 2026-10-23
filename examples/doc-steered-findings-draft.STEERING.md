# STEERING.md — doc-steered-findings-draft (document)

_Schema proof-of-steering/receipt@1.0. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._
_Harness: git._
_Validation scope: Validated on trace-commons (28 sessions, full transcript-to-git join, blame agreement ~100%) and local repositories; at-scale validation on SWE-chat (SALT-NLP, 17,968 sessions) completed Oct 2026 with a partial pass: bimodality reproduced approximately (agent-all mode 40.9% vs published 41%), pushback reproduced on the dominant agent (49.2% vs ~50% for Claude Code excluding first turns; pooled 39.6-40.7% and agent-mix-sensitive), survival not reproduced (metric-v2 aggregate 53.4% vs published 59%; per-agent survival 25-97%, so survival stays a context field, stratified by agent where known). post_first_prompt_share is validated as a steering-presence detector (SWE-chat medians: 0.0 one-prompt, 0.75 continued no-pushback, 0.97 pushback sessions), not a steering-dose measure; at SWE-chat scale it was computed as the gross-added-lines analogue of this field's final-lines definition (see swe-chat/VALIDATION.md section 6). Document mode ground-truth-tested on CoAuthor (1,447 human-GPT-3 writing sessions, CHI 2022): per-part 'unchanged from first version' labels validated (sentence-level agreement 88.3%, false-untouched rate ~0.05%); the doc headline % unchanged is a floor on the untouched share, not a dose estimate (mean absolute error 13.0 pp against keystroke truth, sensitive to revision granularity). Document receipts contain no rejection evidence: material rejected or dismissed before it ever entered a revision is invisible to doc mode, so doc-mode steering evidence is a lower bound on interaction (see coauthor/VALIDATION-coauthor.md)._
- Steering mark: **Closely steered**. 3 revisions; 1 of 18 sections were reshaped after introduction, and at least 36.0% of the final text survives verbatim from the first version. The mark names the process shape, not a grade.

- History provider: git (history complete: True; section strategy: markdown)
- Authors: Yuriy H
- Revisions in git history: 3 (bde19aa5, 643f5743, a58f7e5e)
- Final size: 242 non-blank lines
- Unchanged from first committed version: **at least 36.0%** of the final text survives verbatim from the first version (a floor, computed over 3 revisions: the exact-line rule only ever marks a line rewritten, so finer revision granularity only lowers this number)
- Sentence-level unchanged share (the less granularity-sensitive prose measure): **38.3%** of final sentences appear verbatim in the first version

## Per-section steering map

| section | final lines | % unchanged from v1 | % introduced after v1 | introduced by revision |
|---|---|---|---|---|
| personal-guard — findings draft (phase 1: instrument validation; phase 2: GPU-free real-model runs) | 4 | 75.0 | 25.0 | rev1 (bde19aa5): 3, rev3 (a58f7e5e): 1 |
| What was built and verified (executed, not assumed) | 10 | 100.0 | 0.0 | rev1 (bde19aa5): 10 |
| The one honest caveat that governs everything below | 8 | 100.0 | 0.0 | rev1 (bde19aa5): 8 |
| Instrument results (scripted models, seed 0, n=200/category) | 26 | 100.0 | 0.0 | rev1 (bde19aa5): 26 |
| Calibration findings (the useful phase-1 output) | 19 | 100.0 | 0.0 | rev1 (bde19aa5): 19 |
| Verdict against the kill criteria (phase 1) | 10 | 100.0 | 0.0 | rev1 (bde19aa5): 10 |
| Rented-GPU cost estimate (checked 2026-10-17, secondary pricing pages) | 17 | 0.0 | 100.0 | rev2 (643f5743): 17 |
| Next, in order | 12 | 91.7 | 8.3 | rev1 (bde19aa5): 11, rev3 (a58f7e5e): 1 |
| Phase 2 (2026-10-17): GPU-free — real adapters, prompt arm, hardened gate | 9 | 0.0 | 100.0 | rev3 (a58f7e5e): 9 |
| What actually ran | 11 | 0.0 | 100.0 | rev3 (a58f7e5e): 11 |
| Real probe items (new in phase 2) | 12 | 0.0 | 100.0 | rev3 (a58f7e5e): 12 |
| Prompt-personalization arm (the PERG-for-prompts result) | 25 | 0.0 | 100.0 | rev3 (a58f7e5e): 25 |
| Real-adapter instrument validation | 22 | 0.0 | 100.0 | rev3 (a58f7e5e): 22 |
| Two instrument bugs found and fixed (both would have faked results) | 16 | 0.0 | 100.0 | rev3 (a58f7e5e): 16 |
| Battery hardening (gate v2) | 15 | 0.0 | 100.0 | rev3 (a58f7e5e): 15 |
| Manifest as a standalone deliverable | 9 | 0.0 | 100.0 | rev3 (a58f7e5e): 9 |
| Still stubbed, and why | 11 | 0.0 | 100.0 | rev3 (a58f7e5e): 11 |
| Next, in order (phase 3, unchanged blockers) | 6 | 0.0 | 100.0 | rev3 (a58f7e5e): 6 |
