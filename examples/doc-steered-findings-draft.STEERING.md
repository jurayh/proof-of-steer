# STEERING.md — doc-steered-findings-draft (document)

_Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._

- Revisions in git history: 3 (bde19aa5, 643f5743, a58f7e5e)
- Final size: 242 non-blank lines
- Unchanged from first committed version: **36.0%**

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
