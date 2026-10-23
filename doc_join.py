"""The document-mode join, consuming snapshots from any history provider.

Adopted into v1 in the v1.4 build from the gdocs spike's join.py. The
math is v1's original doc_receipt math with the git fetch cut out:
versions arrive as (snapshot_id, text) pairs, oldest first, and the
numbers for the git path are unchanged (parity-gated against the
published findings-draft receipt: 36.0% overall, all 18 section
percentages).

Sectioning is a strategy, per the provider design (the join's second
seam). Plain-text exports (Google Docs) drop markdown heading markers,
so a heading-less export fed to the markdown sectioner collapses into
one "(preamble)" section and the per-section map, the headline, is
lost. Strategies:

  markdown   v1 behaviour: split on ^#{1,3} heading lines.
  heuristic  conservative heading-like line detection over plain text
             (see is_heading_like). Softer evidence; the receipt says
             so in labels.method whenever this strategy produced the map.
  whole      one "(whole document)" section: the honest fallback when
             nothing qualifies. The overall floor and sentence share
             are still computed.

`auto` (the CLI default) resolves markdown when heading markers exist,
else heuristic when at least two heading-like lines qualify, else
whole. Naming the strategy explicitly (`--section-strategy`) overrides.
"""
from __future__ import annotations

import re
from collections import Counter

import steering_receipt as v1  # same directory; SCHEMA + split_sentences

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)")

SECTION_STRATEGIES = ("auto", "markdown", "heuristic", "whole")
WHOLE_TITLE = "(whole document)"
PREAMBLE_TITLE = "(preamble)"


def _sections_markdown(final: str):
    sections, cur_title, cur_lines = [], PREAMBLE_TITLE, []
    for line in final.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if cur_lines or cur_title != PREAMBLE_TITLE:
                sections.append((cur_title, cur_lines))
            cur_title, cur_lines = m.group(2).strip(), [line]
        else:
            cur_lines.append(line)
    sections.append((cur_title, cur_lines))
    return sections


# ------------------------------------------------------- heuristic sectioning
# A heading-like line in a plain-text export. The rules were tuned
# against a real heading-less export (the Personal-Guard findings draft
# with its '#' markers stripped): sentence-case headings defeat any
# Title-Case test, so the working discriminators are structural:
#   - short (<= 80 chars, <= 12 words) and contains a letter
#   - does NOT end in terminal punctuation (. ! ? ; :) -- body
#     sentences in prose exports end in punctuation; headings do not
#   - preceded by a blank line or the start of the text (exports put a
#     paragraph break before a heading; a wrapped continuation line of
#     a body paragraph never follows a blank line)
#   - not a list item, table row, blockquote, or code fence
# On that real export the rules recovered 17 of 18 headings with zero
# false positives (the one miss is the 103-char title, over the length
# cap). See BUILD-NOTES v1.4 for the full accounting.
_HEADING_TERMINAL = set(".!?;:")
_LIST_PREFIX_RE = re.compile(r"^([-*•+]|\d+[.)])\s")


def is_heading_like(lines: list[str], i: int) -> bool:
    s = lines[i].strip()
    if not s or len(s) > 80:
        return False
    if s[-1] in _HEADING_TERMINAL:
        return False
    if i > 0 and lines[i - 1].strip():
        return False  # must follow a blank line (or start of text)
    if _LIST_PREFIX_RE.match(s) or s.startswith(("|", ">", "`")):
        return False
    words = s.split()
    if not (1 <= len(words) <= 12):
        return False
    return bool(re.search(r"[A-Za-z]", s))


def heuristic_candidates(final: str) -> list[int]:
    lines = final.splitlines()
    return [i for i in range(len(lines)) if is_heading_like(lines, i)]


def _sections_heuristic(final: str, candidates: list[int]):
    lines = final.splitlines()
    cand = set(candidates)
    sections, cur_title, cur_lines = [], PREAMBLE_TITLE, []
    for i, line in enumerate(lines):
        if i in cand:
            if cur_lines or cur_title != PREAMBLE_TITLE:
                sections.append((cur_title, cur_lines))
            cur_title, cur_lines = line.strip(), [line]
        else:
            cur_lines.append(line)
    sections.append((cur_title, cur_lines))
    return sections


def resolve_sections(final: str, strategy: str = "auto"):
    """Return (sections, resolved_strategy). sections: [(title, lines)]."""
    if strategy == "markdown":
        return _sections_markdown(final), "markdown"
    if strategy == "whole":
        return [(WHOLE_TITLE, final.splitlines())], "whole"
    if strategy == "heuristic":
        cands = heuristic_candidates(final)
        if cands:
            return _sections_heuristic(final, cands), "heuristic"
        return [(WHOLE_TITLE, final.splitlines())], "whole"
    # auto: markdown markers win, then heuristic (>= 2 candidates),
    # else the whole-document fallback.
    if any(HEADING_RE.match(l) for l in final.splitlines()):
        return _sections_markdown(final), "markdown"
    cands = heuristic_candidates(final)
    if len(cands) >= 2:
        return _sections_heuristic(final, cands), "heuristic"
    return [(WHOLE_TITLE, final.splitlines())], "whole"


# ---------------------------------------------------------------- the join
def doc_join(versions: list[tuple[str, str]], *, label: str, source: str,
             provider: str, history_complete: bool | None,
             section_strategy: str = "auto",
             authors: list[str | None] | None = None) -> dict:
    """versions: [(snapshot_id, text)], oldest first. Returns a receipt
    dict in v1's document shape, plus the additive fields `provider`,
    `history_complete`, `section_strategy` (the strategy that actually
    produced the map) and, when `authors` is given, `authors` (distinct
    snapshot authors in first-appearance order: snapshot metadata
    carried into the receipt, never a join input)."""
    if not versions:
        raise ValueError("no snapshots")
    final = versions[-1][1]
    sections, resolved_strategy = resolve_sections(final, section_strategy)
    first_lines = Counter(l for l in versions[0][1].splitlines() if l.strip())
    # section titles present in the first version (for the mark's
    # reshaped test: a section that existed at v1 AND gained lines later)
    first_sections, _ = resolve_sections(versions[0][1], section_strategy)
    first_titles = {t for t, _ in first_sections}
    out_sections = []
    for title, lines in sections:
        nb = [l for l in lines if l.strip()]
        if not nb:
            continue
        survived = sum(1 for l in nb if first_lines.get(l, 0) > 0)
        intro_rev = Counter()
        for l in set(nb):
            for vi, (_, vtxt) in enumerate(versions):
                if l in vtxt.splitlines():
                    intro_rev[vi] += 1
                    break
        out_sections.append({
            "section": title, "final_lines": len(nb),
            "pct_unchanged_from_first_version": round(100 * survived / len(nb), 1),
            "pct_introduced_after_first_version": round(100 * (len(nb) - survived) / len(nb), 1),
            "introduced_by_revision": {
                f"rev{i+1} ({versions[i][0]})": c
                for i, c in sorted(intro_rev.items())},
            "_first_titles": first_titles,
        })
    total_nb = sum(s["final_lines"] for s in out_sections)
    survived_total = sum(round(s["final_lines"] * s["pct_unchanged_from_first_version"] / 100)
                         for s in out_sections)
    first_sentences = set(v1.split_sentences(versions[0][1]))
    final_sentences = v1.split_sentences(final)
    unchanged_sentence_share = (
        round(100 * sum(1 for s in final_sentences if s in first_sentences) / len(final_sentences), 1)
        if final_sentences else None)
    mark = v1.doc_mark(out_sections, len(versions),
                       round(100 * survived_total / total_nb, 1) if total_nb else None)
    for s in out_sections:
        del s["_first_titles"]
    method = (f"provider snapshots ({provider}); exact-line provenance "
              f"per section (conservative: any edit marks the line "
              f"rewritten); section strategy: {resolved_strategy}")
    if resolved_strategy == "heuristic":
        method += (" (heading-like lines detected heuristically in a "
                   "heading-less export; softer evidence than marked "
                   "headings)")
    receipt = {
        "schema": v1.SCHEMA, "label": label, "kind": "document",
        "harness": "git" if provider == "git" else provider,
        "provider": provider,
        "history_complete": history_complete,
        "section_strategy": resolved_strategy,
        "mark": mark,
        "validation_scope": v1.VALIDATION_SCOPE,
        "source": source, "revisions": len(versions),
        "revision_count": len(versions),
        "revision_shas": [sid for sid, _ in versions],
        "final_nonblank_lines": total_nb,
        "overall_pct_unchanged_from_first_version": (
            round(100 * survived_total / total_nb, 1) if total_nb else None),
        "unchanged_sentence_share_pct": unchanged_sentence_share,
        "per_section": out_sections,
        "labels": {
            "method": method,
            "receipt_nature": "descriptive evidence, not a certified grade"},
    }
    if authors is not None:
        receipt["authors"] = list(dict.fromkeys(a for a in authors if a))
    return receipt
