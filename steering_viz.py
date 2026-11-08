#!/usr/bin/env python3
"""Proof of Steering — Collaboration Map generator. Stdlib only.

Reads one or more receipt JSON files (spike format: code receipts carry
git_join.per_segment + per_file; doc receipts carry per_section with
introduced_by_revision) and emits ONE self-contained HTML page:
inline CSS/JS, zero external assets, no network.

Usage:
  python3 steering_viz.py receipt.json [more.json ...] -o out.html
  python3 steering_viz.py doc.receipt.json --disclosure -o disclosure.md
  python3 steering_viz.py --shadow steered.jsonl control.jsonl [--doc doc.receipt.json] -o shadow.html
  python3 steering_viz.py --replay session.jsonl [--receipt receipt.json] -o replay.html
  python3 steering_viz.py --rework session.jsonl [--receipt receipt.json] -o rework-web-3d.html
  python3 steering_viz.py --dual-timeline session.jsonl [--receipt receipt.json] -o dual-timeline.html
  python3 steering_viz.py --making-of making-of-dual-timeline.json -o making-of-dual-timeline.html

Visual model:
  - Code receipts render as a steering timeline (one block per human-turn
    segment, width proportional to lines introduced, coloured by segment
    category; the surviving share of each block is solid, the discarded
    share hatched) plus per-file first-segment vs later bars. Multiple code
    receipts render adjacently so a one-prompt control (a single block)
    contrasts with a steered session at a glance.
  - Doc receipts render as a stack of section blocks, height proportional
    to final lines, each a proportion bar split by the revision that
    introduced its lines: rev 1 in first-draft blue, later revisions in
    stepped warm shades. Sections absent from rev 1 are badged as additions.
No prompt text exists in receipts and none is rendered.
"""
import html, json, sys
from datetime import datetime
from collections import Counter
from pathlib import Path

CSS = """
:root{
  --ink:#17222e; --muted:#5c6b7a; --line:#dde4ea; --card:#ffffff;
  --first:#46689e; --follow:#2f8f83; --corr:#e07a3f; --err:#c94f5e;
  --bg:#f6f8fa;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
.wrap{max-width:1120px;margin:0 auto;padding:34px 22px 46px}
h1{font-size:30px;margin:0 0 4px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:15px;margin:0 0 18px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:var(--muted);
  padding:10px 14px;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:22px}
.legend b{color:var(--ink);font-weight:600}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.sw.hatched{background:repeating-linear-gradient(45deg,#b9c4cf 0 3px,#eef2f5 3px 6px)}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:18px;align-items:start}
@media(max-width:840px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:20px 20px 16px;margin-bottom:18px;box-shadow:0 1px 2px rgba(23,34,46,.04)}
.card h2{font-size:19px;margin:0 0 2px;letter-spacing:-.01em}
.card .kind{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.headline{font-size:14.5px;margin:8px 0 14px;color:var(--ink)}
.headline b{font-size:17px}
.caption{font-size:13px;color:var(--muted);margin-top:10px;font-style:italic}
h3{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:18px 0 8px}
/* steering timeline */
.timeline{display:flex;gap:2px;height:64px;align-items:stretch}
.seg{position:relative;border-radius:4px;overflow:hidden;cursor:pointer;min-width:3px;
  background:repeating-linear-gradient(45deg,rgba(70,80,95,.28) 0 4px,rgba(70,80,95,.10) 4px 8px)}
.seg .alive{position:absolute;top:0;bottom:0;left:0}
.seg.tick{flex:0 0 3px;background:#cdd6df}
.seg:hover{outline:2px solid var(--ink);outline-offset:1px;z-index:2}
/* per-file bars */
.frow{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:12.5px}
.fname{flex:0 0 46%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink)}
.fname .dir{color:var(--muted)}
.fbar{flex:1;height:13px;border-radius:4px;overflow:hidden;display:flex;background:#edf1f4}
.fbar .ff{background:var(--first)} .fbar .fl{background:var(--follow)}
.fnum{flex:0 0 118px;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
/* doc sections */
.drow{display:flex;gap:12px;align-items:stretch;margin:7px 0}
.dlabel{flex:0 0 218px;padding-top:2px}
.dlabel .sname{font-size:13.5px;font-weight:600;line-height:1.25}
.dlabel .smeta{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.dbar{flex:1;border-radius:6px;overflow:hidden;display:flex;cursor:pointer;min-height:16px}
.dbar:hover{outline:2px solid var(--ink);outline-offset:1px}
.dbar div{height:100%}
.badge{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;
  background:#fdeee1;color:#a34d12;border-radius:20px;padding:1px 8px;margin-left:7px;vertical-align:1px}
@media(max-width:640px){.dlabel{flex-basis:130px}.fname{flex-basis:38%}.fnum{flex-basis:96px}}
/* tooltip */
#tip{position:fixed;pointer-events:none;background:#17222e;color:#fff;border-radius:9px;
  padding:9px 12px;font-size:12.5px;line-height:1.5;max-width:290px;opacity:0;transition:opacity .12s;z-index:50;
  box-shadow:0 6px 18px rgba(23,34,46,.25)}
#tip b{font-size:13px}
#tip .tt-dim{color:#aeb9c4}
footer{color:var(--muted);font-size:12px;margin-top:8px;line-height:1.6}
"""

JS = """
const tip=document.getElementById('tip');
function show(e){const t=e.currentTarget.dataset.tip;if(!t)return;tip.innerHTML=t;
  tip.style.opacity=1;move(e);}
function move(e){const x=Math.min(e.clientX+14,innerWidth-310),y=Math.min(e.clientY+16,innerHeight-150);
  tip.style.left=x+'px';tip.style.top=y+'px';}
function hide(){tip.style.opacity=0;}
document.querySelectorAll('[data-tip]').forEach(el=>{
  el.addEventListener('mouseenter',show);el.addEventListener('mousemove',move);
  el.addEventListener('mouseleave',hide);
  el.addEventListener('click',e=>{show(e);setTimeout(hide,2600);});
});
"""

REV_SHADES = ["#f2b879", "#eda154", "#e8893a", "#e06f24", "#c85a17", "#a34d12", "#7e3a0d"]

def esc(s): return html.escape(str(s), quote=True)

def seg_category(seg, first_idx):
    if seg["segment"] == first_idx: return "first"
    if seg.get("correction_keyword"): return "correction"
    if seg.get("after_error"): return "after_error"
    return "followup"

CAT = {
    "first":      ("var(--first)", "First prompt"),
    "followup":   ("var(--follow)", "Follow-up prompt"),
    "correction": ("var(--corr)", "Correction prompt"),
    "after_error": ("var(--err)", "Prompt after an error"),
}

def code_title(r):
    files = r["git_join"].get("per_file") or []
    if files:
        top = files[0]["file"].replace("\\", "/").split("/")[0]
        if top: return top
    return r["label"]

def headline_pct(g):
    """post_first_prompt_share_pct lives flat in spike-format receipts
    and under git_join.headline_fields in v1 receipts; read both."""
    if g.get("post_first_prompt_share_pct") is not None:
        return g["post_first_prompt_share_pct"]
    return (g.get("headline_fields") or {}).get("post_first_prompt_share_pct")

def code_card(r, control=False):
    m, g = r["mechanistic"], r["git_join"]
    first_idx = g.get("first_artifact_segment", 0)
    segs = g["per_segment"]
    total_gross = sum(s["lines_introduced_gross"] for s in segs) or 1
    blocks = []
    for s in segs:
        gross, alive = s["lines_introduced_gross"], s["lines_surviving_to_head"]
        cat = seg_category(s, first_idx)
        colour, catname = CAT[cat]
        flags = []
        if s.get("correction_keyword"): flags.append("correction keywords")
        if s.get("after_error"): flags.append("followed an error")
        tip = (f"<b>Segment {s['segment']} — {catname}</b><br>"
               f"{gross:,} lines introduced · {alive:,} survive to the final artifact"
               + (f"<br><span class='tt-dim'>{', '.join(flags)}</span>" if flags else "")
               + f"<br><span class='tt-dim'>{s['edit_write_ops']} edits/writes · prompt {s['prompt_chars']:,} chars</span>")
        if gross == 0:
            blocks.append(f'<div class="seg tick" data-tip="{esc(tip)}"></div>')
        else:
            pct_alive = 100 * alive / gross
            blocks.append(
                f'<div class="seg" style="flex:{gross} 1 0" data-tip="{esc(tip)}">'
                f'<div class="alive" style="width:{pct_alive:.1f}%;background:{colour}"></div></div>')
    frows = []
    for f in g["per_file"]:
        p = f["file"].replace("\\", "/")
        base = p.rsplit("/", 1)[-1]; d = p[: len(p) - len(base)]
        fs = f["first_segment_share_pct"]
        tip = (f"<b>{esc(p)}</b><br>{f['final_lines']:,} final lines<br>"
               f"{fs:.1f}% from the first segment · {100 - fs:.1f}% arrived later")
        frows.append(
            f'<div class="frow"><div class="fname" data-tip="{esc(tip)}"><span class="dir">{esc(d)}</span>{esc(base)}</div>'
            f'<div class="fbar" data-tip="{esc(tip)}"><div class="ff" style="width:{fs:.1f}%"></div>'
            f'<div class="fl" style="width:{100 - fs:.1f}%"></div></div>'
            f'<div class="fnum">{f["final_lines"]:,} lines · {fs:.0f}% first</div></div>')
    turns = m["human_turns"]
    caption = ("One prompt. One block. Nothing arrived after the first draft."
               if turns <= 1 else
               f"{turns} human turns. Most of what shipped did not exist after the first prompt.")
    return f"""
<article class="card">
  <div class="kind">Code · {'one-prompt control' if control else 'steered session'}</div>
  <h2>{esc(code_title(r))}</h2>
  <p class="headline"><b>{turns} human turn{'s' if turns != 1 else ''}</b> ·
    <b>{headline_pct(g)}%</b> of shipped lines arrived after the first prompt ·
    {g['files_at_head']} files, {g['final_nonblank_lines']:,} lines</p>
  <h3>Steering timeline — each block is one human turn</h3>
  <div class="timeline">{''.join(blocks)}</div>
  <h3>Files — first segment vs everything after</h3>
  {''.join(frows)}
  <p class="caption">{esc(caption)}</p>
</article>"""

def doc_card(r):
    src = (r.get("source") or "").split("::")[-1].strip()
    name = Path(src).name if src else r["label"]
    revs = sorted({int(k.split()[0].replace("rev", "")): k for s in r["per_section"]
                   for k in s["introduced_by_revision"]}.items())
    rev_colour = {}
    for n, key in revs:
        rev_colour[key] = "var(--first)" if n == 1 else REV_SHADES[min(n - 2, len(REV_SHADES) - 1)]
    rows = []
    for s in r["per_section"]:
        total = s["final_lines"] or 1
        parts, tips = [], []
        added_later = True
        for key in sorted(s["introduced_by_revision"], key=lambda k: int(k.split()[0].replace("rev", ""))):
            n_lines = s["introduced_by_revision"][key]
            if n_lines <= 0: continue
            n_rev = int(key.split()[0].replace("rev", ""))
            if n_rev == 1: added_later = False
            w = 100 * n_lines / total
            parts.append(f'<div style="width:{w:.1f}%;background:{rev_colour[key]}"></div>')
            tips.append(f"{key}: {n_lines} lines")
        height = max(16, min(58, round(10 + s["final_lines"] * 1.35)))
        badge = '<span class="badge">ADDED LATER — NOT IN V1</span>' if added_later and s["final_lines"] >= 3 else ""
        tip = (f"<b>{esc(s['section'])}</b><br>{s['final_lines']} final lines · "
               f"{s['pct_unchanged_from_first_version']}% unchanged from the first version<br>"
               + "<br>".join(esc(t) for t in tips))
        rows.append(
            f'<div class="drow"><div class="dlabel"><div class="sname">{esc(s["section"])}{badge}</div>'
            f'<div class="smeta">{s["final_lines"]} lines · {s["pct_unchanged_from_first_version"]:.0f}% untouched</div></div>'
            f'<div class="dbar" style="height:{height}px" data-tip="{esc(tip)}">{"".join(parts)}</div></div>')
    return f"""
<article class="card">
  <div class="kind">Document · {r['revisions']} revisions in git history</div>
  <h2>{esc(name)}</h2>
  <p class="headline"><b>{r['overall_pct_unchanged_from_first_version']}%</b> of the final document is unchanged
    from its first version · {r['final_nonblank_lines']} lines · the rest was shaped by later revisions</p>
  <h3>Section map — blue is the first draft, warm colours are later revisions</h3>
  {''.join(rows)}
  <p class="caption">Read it like a reviewer: the warm sections carry human judgment applied after the first
    draft. The all-blue sections were never touched again.</p>
</article>"""

def build(receipts, title="Proof of Steering — Collaboration Maps"):
    codes = [r for r in receipts if r["kind"] == "code"]
    docs = [r for r in receipts if r["kind"] == "document"]
    codes.sort(key=lambda r: -r["mechanistic"]["human_turns"])
    out = [f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Collaboration Maps</h1>
<p class="sub">Which parts of an artifact the human actually shaped — and how. Drawn from Proof of Steering receipts.</p>
<div class="legend"><b>Legend</b>
<span><span class="sw" style="background:var(--first)"></span>First prompt / first draft</span>
<span><span class="sw" style="background:var(--follow)"></span>Follow-up steering</span>
<span><span class="sw" style="background:var(--corr)"></span>Correction</span>
<span><span class="sw" style="background:var(--err)"></span>After an error</span>
<span><span class="sw hatched"></span>Introduced, later discarded</span>
<span>Hover or tap any block for its numbers</span></div>"""]
    if codes:
        cards = [code_card(codes[0], control=codes[0]["mechanistic"]["human_turns"] <= 1)]
        if len(codes) > 1:
            out.append('<div class="grid"><div>' + cards[0] + "</div><div>"
                       + "".join(code_card(c, control=True) for c in codes[1:]) + "</div></div>")
        else:
            out.append(cards[0])
    for d in docs:
        out.append(doc_card(d))
    schemas = ", ".join(sorted({r.get("schema", "?") for r in receipts}))
    out.append(f"""<footer>Computed locally from Proof of Steering receipts ({esc(schemas)}).
Counts and categories only — no prompt text is ever included. Line provenance cross-checked against git blame.
Descriptive evidence, not a certified grade.</footer>
</div><div id="tip"></div><script>{JS}</script></body></html>""")
    return "".join(out)

# ---------------------------------------------------------------- badge mode
# A small self-contained SVG badge for one receipt (v1.4): the steering
# mark's category word plus, for code receipts, the Steerprint mini
# strip (one block per human turn, coloured by impact class) and, for
# doc receipts, the revision count. Suitable for README / PR embedding:
#   python3 steering_viz.py receipt.json --badge -o badge.svg
MARK_COLOURS = {"One-shot": "#5c6b7a", "Prompted": "#46689e",
                "Steered": "#2f8f83", "Closely steered": "#e07a3f"}
IMPACT_COLOURS = {"procedural": "#cdd6df", "continuation": "#2f8f83",
                  "reshaping": "#e07a3f", "unmeasured": "#ffffff"}

# ---------------------------------------------------------------- disclosure mode
# A short, paste-ready disclosure block for a DOCUMENT receipt, generated
# from the receipt JSON only. No receipt computation is repeated here: every
# number below is read from the receipt, so the block cannot drift from it.
#   python3 steering_viz.py doc.receipt.json --disclosure -o disclosure.md
# Sections are grouped, never listed as a full table: unchanged since the
# first version, arrived in later revisions, reshaped after first appearing.
# The reshaped group reproduces the receipt's own mark count. The mark's
# rule (see steering_receipt.doc_mark) requires the section heading to
# survive unchanged, so when more sections gained lines later than the mark
# counts as reshaped, the block says so instead of claiming the larger
# number. The block's own prose uses no em-dashes and no semicolons;
# section titles are quoted verbatim from the receipt and may contain
# either character as data.

def _rev_num(key):
    import re
    m = re.match(r"rev(\d+)", key)
    return int(m.group(1)) if m else 0

def _rev_split(section):
    """(lines from revision 1, {later revision number: lines}) for one section."""
    first = 0
    later = {}
    for key, n in (section.get("introduced_by_revision") or {}).items():
        num = _rev_num(key)
        if num == 1:
            first += n
        elif num > 1:
            later[num] = later.get(num, 0) + n
    return first, later

def _plural(n, singular, plural=None):
    return singular if n == 1 else (plural or singular + "s")

def _later_detail(later):
    """'1 line added in revision 2' or '5 lines added in revisions 2 and 3'."""
    total = sum(later.values())
    nums = sorted(later)
    if len(nums) == 1:
        where = f"revision {nums[0]}"
    elif len(nums) == 2:
        where = f"revisions {nums[0]} and {nums[1]}"
    else:
        where = "revisions " + ", ".join(str(n) for n in nums[:-1]) + f" and {nums[-1]}"
    return f"{total} {_plural(total, 'line')} added in {where}"

def disclosure_md(r):
    if r.get("kind") != "document":
        raise ValueError("--disclosure takes a document receipt, "
                         f"not a {r.get('kind', 'unknown')} receipt")
    mark = r.get("mark") or {}
    category = mark.get("category", "Unmarked")
    revs = r.get("revision_count", r.get("revisions", 0))
    floor = r["overall_pct_unchanged_from_first_version"]
    sentence = r.get("unchanged_sentence_share_pct")
    sections = r.get("per_section") or []

    unchanged, arrived, multi = [], [], []
    for s in sections:
        first, later = _rev_split(s)
        if s.get("pct_unchanged_from_first_version") == 100.0:
            unchanged.append(s)
        if first == 0:
            arrived.append(s)
        if first > 0 and later:
            multi.append((s, later))

    lines = []
    lines.append("## Steering disclosure")
    lines.append("")
    lines.append("This document was written with an AI agent, and its revision history carries "
                 "a steering receipt. The receipt reports what observably happened across "
                 "revisions: how much of the final text survives verbatim from the first "
                 "version, which sections arrived later, and which sections were reshaped "
                 "after they first appeared.")
    lines.append("")
    lines.append(f"- Steering mark: {category}, {revs} {_plural(revs, 'revision')}")
    floor_line = (f"- First version to final: at least {floor:.1f}% of the final text "
                  f"survives verbatim from the first version")
    if sentence is not None:
        floor_line += (f" ({sentence:.1f}% of final sentences, the less "
                       f"granularity-sensitive measure)")
    lines.append(floor_line)
    if unchanged:
        lines.append("- Sections unchanged since the first version:")
        for s in unchanged:
            lines.append(f"  - {s['section']}")
    if arrived:
        lines.append("- Sections that arrived in later revisions:")
        for s in arrived:
            _, later = _rev_split(s)
            lines.append(f"  - {s['section']} ({_rev_label(later)})")
    reshaped_count = mark.get("reshaped_sections")
    if reshaped_count:
        if len(multi) == reshaped_count:
            lines.append("- Sections reshaped after first appearing:")
            for s, later in multi:
                lines.append(f"  - {s['section']} ({_later_detail(later)})")
        else:
            lines.append(f"- Sections reshaped after first appearing: {reshaped_count} of "
                         f"{len(sections)} {_plural(len(sections), 'section')}.")
            lines.append(f"Note: {len(multi)} {_plural(len(multi), 'section')} gained lines in "
                         f"later revisions, but the mark counts {reshaped_count} as reshaped. "
                         f"The mark's rule requires the section heading to survive unchanged, "
                         f"so a section whose heading changed between versions is not counted "
                         f"as reshaped even when it gained lines.")
    history_complete = r.get("history_complete", True)
    provider = r.get("provider")
    if history_complete:
        hist = f"complete, {revs} {_plural(revs, 'revision')}"
        if provider:
            hist += f" from {provider}"
        lines.append(f"- History: {hist}")
    else:
        lines.append(f"- History: truncated at the first available revision, {revs} "
                     f"{_plural(revs, 'revision')} observed. Anything before that baseline "
                     f"is unmeasured, and the shares above are relative to that baseline.")
    lines.append("- Full section map: see the STEERING.md that travels with this receipt.")
    lines.append("")
    lines.append("Generated from the document receipt with "
                 "`steerprint <receipt.json> --disclosure`. The receipt carries counts and "
                 "categories only, never prompt text, and the revisions never leave your "
                 "machine. Descriptive evidence, never a certified grade. Material rejected "
                 "or dismissed before it ever entered a revision is invisible to this "
                 "receipt, so what it shows is a lower bound on interaction.")
    lines.append("")
    lines.append("Delete this section if no agent was involved.")
    return "\n".join(lines) + "\n"

def _rev_label(later):
    """'revision 2' or 'revisions 2 and 3', for an arrived section's introducer."""
    nums = sorted(later)
    if len(nums) == 1:
        return f"revision {nums[0]}"
    if len(nums) == 2:
        return f"revisions {nums[0]} and {nums[1]}"
    return "revisions " + ", ".join(str(n) for n in nums[:-1]) + f" and {nums[-1]}"

def badge_svg(r):
    mark = r.get("mark") or {}
    word = mark.get("category", "Unmarked")
    colour = MARK_COLOURS.get(word, "#5c6b7a")
    if r["kind"] == "code":
        g = r["git_join"]
        segs = [s for s in g["per_segment"] if s["segment"] >= 0]
        turns = r["mechanistic"]["human_turns"]
        strip_w = 158
        gross = [max(1, s["lines_introduced_gross"]) for s in segs] or [1]
        total = sum(gross)
        blocks, x = [], 186.0
        for s, wgt in zip(segs, gross):
            w = max(3.0, strip_w * wgt / total)
            cls = s.get("impact_class", "continuation")
            fill = IMPACT_COLOURS.get(cls, "#2f8f83")
            stroke = ' stroke="#8fa1b3" stroke-width="0.7"' if cls == "unmeasured" else ""
            blocks.append(f'<rect x="{x:.1f}" y="13" width="{max(1.5, w - 1.5):.1f}" height="18" rx="2.5" fill="{fill}"{stroke}/>')
            x += w
        right = ("".join(blocks)
                 + f'<text x="344" y="46" font-size="11.5" fill="#5c6b7a" text-anchor="end">'
                   f'{turns} human turn{"s" if turns != 1 else ""}</text>')
    else:
        revs = r.get("revision_count", r["revisions"])
        nsec = len(r.get("per_section", []))
        right = (f'<text x="344" y="34" font-size="13" fill="#5c6b7a" text-anchor="end">'
                 f'{revs} revision{"s" if revs != 1 else ""} · {nsec} section{"s" if nsec != 1 else ""}</text>')
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="352" height="56" viewBox="0 0 352 56" role="img" aria-label="proof-of-steer steering mark: {esc(word)}">
<rect x="0.5" y="0.5" width="351" height="55" rx="9" fill="#f6f8fa" stroke="#dde4ea"/>
<circle cx="18" cy="28" r="6" fill="{colour}"/>
<text x="32" y="24" font-size="9.5" letter-spacing="1.6" fill="#5c6b7a" font-weight="700">PROOF-OF-STEER</text>
<text x="32" y="43" font-size="16.5" font-weight="700" fill="#17222e">{esc(word.upper())}</text>
{right}
</svg>
"""

SHADOW_CSS = """
.sh-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start}
@media(max-width:840px){.sh-grid{grid-template-columns:1fr}}
.sh-panel{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:20px 20px 16px;box-shadow:0 1px 2px rgba(23,34,46,.04)}
.sh-panel h2{font-size:19px;margin:0 0 2px;letter-spacing:-.01em}
.sh-panel .kind{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.sh-row{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:12.5px}
.sh-name{flex:0 0 46%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink)}
.sh-name .dir{color:var(--muted)}
.sh-track{flex:1;height:13px;border-radius:4px;overflow:hidden;display:flex;background:#20262e}
.sh-lit{background:var(--first)}
.sh-num{flex:0 0 118px;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.sh-note{font-size:12.5px;color:var(--muted);margin:10px 0 0;line-height:1.5}
.sh-caption{font-size:16px;line-height:1.55;margin:20px 0 4px}
.sh-foot{color:var(--muted);font-size:12px;margin-top:14px;line-height:1.6}
@media(max-width:640px){.sh-name{flex-basis:38%}.sh-num{flex-basis:96px}}
"""

def shadow_rows_from_files(files, fas_idx):
    """Per-file first-segment line counts from a replay's files dict
    (path -> list of (line, origin segment)), the same in-memory
    provenance the receipt headline is computed from. Sorted largest
    first. Only non-blank lines count, matching the receipt."""
    rows = []
    for fp, v in files.items():
        final = sum(1 for l, _ in v if l.strip())
        lit = sum(1 for l, o in v if l.strip() and o == fas_idx)
        rows.append({"file": fp, "final_lines": final, "lit_lines": lit})
    rows.sort(key=lambda r: -r["final_lines"])
    return rows

def shadow_replay_session(session_path):
    """Replay one session with the shipped tool's own functions and
    return (rows, summary). No new provenance logic is introduced here."""
    import steering_receipt as sr
    fmt = sr.detect_format(session_path)
    if fmt == "codex":
        segments, meta = sr.parse_codex_session(session_path)
    else:
        segments, meta = sr.parse_session(session_path)
    files, stats, introduced, seeded_bases = sr.apply_ops(segments, None)
    fas_idx = segments[0]["idx"]
    rows = shadow_rows_from_files(files, fas_idx)
    turns = sum(1 for s in segments if not s.get("pre_prompt"))
    return rows, {"turns": turns,
                  "final_lines": sum(r["final_lines"] for r in rows),
                  "lit_lines": sum(r["lit_lines"] for r in rows)}

def shadow_doc_rows(doc_receipt):
    """Per-section first-version line counts for a document receipt.
    Lit lines are exactly the lines introduced by revision 1, taken
    from the receipt's own introduced_by_revision maps, in document
    order (not sorted: a document reads top to bottom)."""
    rows = []
    for s in doc_receipt["per_section"]:
        lit = sum(n for k, n in s["introduced_by_revision"].items()
                  if k.split()[0] == "rev1")
        rows.append({"section": s["section"], "final_lines": s["final_lines"],
                     "lit_lines": lit})
    return rows

def _shadow_row_html(name, final, lit, scale_max, lit_noun):
    p = name.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    d = p[: len(p) - len(base)]
    outer_w = 100 * final / scale_max if scale_max else 0
    lit_w = 100 * lit / final if final else 0
    tip = (f"<b>{esc(p)}</b><br>{final:,} final lines<br>"
           f"{lit:,} {lit_noun} · {final - lit:,} arrived later")
    pct = 100 * lit / final if final else 0
    return (
        f'<div class="sh-row"><div class="sh-name" data-tip="{esc(tip)}">'
        f'<span class="dir">{esc(d)}</span>{esc(base)}</div>'
        f'<div class="sh-track" style="width:{outer_w:.2f}%" data-tip="{esc(tip)}">'
        f'<div class="sh-lit" style="width:{lit_w:.1f}%"></div></div>'
        f'<div class="sh-num">{final:,} lines · {pct:.0f}% first</div></div>')

def _shadow_panel(title, kind, summary, rows, scale_max, note):
    total_final, total_lit = summary["final_lines"], summary["lit_lines"]
    lit_pct = 100 * total_lit / total_final if total_final else 0
    body = "".join(_shadow_row_html(r["file"], r["final_lines"], r["lit_lines"],
                                    scale_max, "from the first prompt")
                     for r in rows)
    return f"""
<div class="sh-panel">
  <div class="kind">{esc(kind)}</div>
  <h2>{esc(title)}</h2>
  <p class="headline"><b>{total_lit:,}</b> of <b>{total_final:,}</b> lines lit
    (<b>{lit_pct:.1f}%</b>) · {summary["turns"]} human turn{'s' if summary['turns'] != 1 else ''}</p>
  {body}
  <p class="sh-note">{esc(note)}</p>
</div>"""

def shadow_html(steered, control, doc=None):
    """Build the counterfactual shadow figure. steered and control are
    dicts with title, turns, rows; doc is an optional dict with title,
    rows, and totals. All numbers come from the caller's measured data;
    this function only lays them out."""
    scale_max = max([r["final_lines"] for r in steered["rows"] + control["rows"]] or [1])
    s_lit_files = [r for r in steered["rows"] if r["lit_lines"] > 0]
    if steered["lit_lines"] == steered["final_lines"]:
        s_note = "Every line in every file is lit."
    else:
        s_note = ("Lit lines live in %d of %d files: " % (len(s_lit_files), len(steered["rows"]))
                  + ", ".join(f"{r['file']} ({r['lit_lines']})" for r in s_lit_files) + ".")
    if control["lit_lines"] == control["final_lines"]:
        c_note = "Every line in every file is lit."
    else:
        c_lit_files = [r for r in control["rows"] if r["lit_lines"] > 0]
        c_note = ("Lit lines live in %d of %d files: " % (len(c_lit_files), len(control["rows"]))
                  + ", ".join(f"{r['file']} ({r['lit_lines']})" for r in c_lit_files) + ".")
    s = steered
    c = control
    caption = (
        "The lit part is what the first prompt built. In the steered session only "
        f"{s['lit_lines']:,} of {s['final_lines']:,} lines survive from the first prompt. "
        "Everything dark arrived in later turns. In the one-prompt control the shadow "
        "equals the artifact, because nothing arrived after the first prompt. "
        "Line authorship calls both artifacts identical. The shadow shows they are not.")
    doc_section = ""
    if doc is not None:
        d_scale = max([r["final_lines"] for r in doc["rows"]] or [1])
        d_rows = "".join(_shadow_row_html(r["section"], r["final_lines"], r["lit_lines"],
                                          d_scale, "from the first version")
                           for r in doc["rows"])
        d_lit_pct = 100 * doc["lit_lines"] / doc["final_lines"] if doc["final_lines"] else 0
        d_with = sum(1 for r in doc["rows"] if r["lit_lines"] > 0)
        doc_section = f"""
<h3 style="margin-top:26px">The same shadow on a document</h3>
<div class="sh-panel">
  <div class="kind">Document · {esc(doc['title'])}</div>
  <p class="headline"><b>{doc['lit_lines']:,}</b> of <b>{doc['final_lines']:,}</b> lines lit
    (<b>{d_lit_pct:.1f}%</b>) · {d_with} of {len(doc['rows'])} sections carry lines from the first version</p>
  {d_rows}
  <p class="sh-note">Lit lines survive verbatim from the first version. Dark lines arrived in later revisions.</p>
</div>
<p class="sh-caption">The same shadow falls on a document. In {esc(doc['title'])}
  {doc['lit_lines']:,} of {doc['final_lines']:,} lines survive from the first version. Lit sections
  carry judgment from the first draft. Dark sections arrived in later revisions.</p>"""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Counterfactual shadow</title><style>{CSS}{SHADOW_CSS}</style></head><body><div class="wrap">
<h1>Counterfactual shadow</h1>
<p class="sub">Each strip is one file, length proportional to its final lines on a shared scale.
Blue is lit: lines the first prompt introduced that survive to the final artifact.
Dark is everything that arrived in later turns.</p>
<div class="legend"><span><span class="sw" style="background:var(--first)"></span><b>Lit</b> · from the first prompt</span>
<span><span class="sw" style="background:#20262e"></span><b>Dark</b> · arrived in later turns</span></div>
<div class="sh-grid">
{_shadow_panel("Steered session", "Code · steered", s, s["rows"], scale_max, s_note)}
{_shadow_panel("One-prompt control", "Code · control", c, c["rows"], scale_max, c_note)}
</div>
<p class="sh-caption">{esc(caption)}</p>
{doc_section}
<p class="sh-foot">Method: a lit line is a line the first segment introduced that survives to the
final artifact, measured by the same line provenance behind the receipt headline. The document
panel lights lines that survive from the first version. Only non-blank lines count. No external
assets. No prompt text.</p>
<div id="tip"></div><script>{JS}</script>
</div></body></html>"""

def shadow_main(argv):
    """CLI: steerprint --shadow steered.jsonl control.jsonl [--doc doc.receipt.json] -o shadow.html.
    Sessions are replayed with the shipped tool's own functions; the doc
    panel, when given, reads its rows from the doc receipt itself."""
    args = list(argv)
    out_path = Path("counterfactual-shadow.html")
    if "-o" in args:
        out_path = Path(args[args.index("-o") + 1])
    doc_path = None
    if "--doc" in args:
        doc_path = args[args.index("--doc") + 1]
    pos = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ("-o", "--doc"):
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        pos.append(a)
    if len(pos) != 2:
        sys.exit("--shadow takes exactly two sessions: steered, then control")
    s_rows, s_sum = shadow_replay_session(Path(pos[0]))
    c_rows, c_sum = shadow_replay_session(Path(pos[1]))
    steered = {"title": "Steered session", "rows": s_rows, **s_sum}
    control = {"title": "One-prompt control", "rows": c_rows, **c_sum}
    doc = None
    if doc_path:
        r = json.loads(Path(doc_path).read_text(encoding="utf-8"))
        d_rows = shadow_doc_rows(r)
        src = (r.get("source") or "").split("::")[-1].strip()
        doc_title = Path(src).name if src else r["label"]
        doc = {"title": doc_title, "rows": d_rows,
               "final_lines": sum(x["final_lines"] for x in d_rows),
               "lit_lines": sum(x["lit_lines"] for x in d_rows)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(shadow_html(steered, control, doc), encoding="utf-8")
    print(f"wrote shadow {out_path} ({out_path.stat().st_size:,} bytes)")

REPLAY_CLASS_ORDER = ["preexisting", "continuation", "reshaping",
                      "procedural", "unmeasured"]
REPLAY_COLOURS = dict(IMPACT_COLOURS)
REPLAY_COLOURS["preexisting"] = "#46689e"

REPLAY_CAPTION = (
    "Each row is one file. The strip grows as lines arrive. Color shows "
    "the kind of turn that introduced each line. Teal lines came from "
    "continuation turns. Orange lines came from reshaping turns that "
    "rewrote earlier work. Pale gray lines came from procedural turns. "
    "White lines with a gray edge came from turns the replay could not "
    "measure. A gray tail shows lines removed or replaced in the last "
    "two turns. It fades as the replay moves on. The last frame matches "
    "the receipt exactly.")

REPLAY_METHOD = (
    "Frames come from the tool's own replay. Frame zero shows the "
    "artifact before the first human turn. Each later frame shows the "
    "artifact after one more human turn. Counts cover non-blank lines "
    "only, matching the receipt.")


def _replay_file_state(files, fp, impact_per):
    """One file's state in one frame: non-blank lines present, their
    composition by the impact class of the introducing turn, and the
    multiset of (line, origin) pairs the discard count is computed from.
    Origins the impact map does not cover read as unmeasured."""
    import steering_receipt as sr
    lines = files.get(fp, [])
    comp = Counter()
    pairs = Counter()
    for ln, org in lines:
        if not ln.strip():
            continue
        if org == sr.PREEXISTING:
            comp["preexisting"] += 1
        else:
            comp[(impact_per.get(org) or {}).get("impact_class",
                                                "unmeasured")] += 1
        pairs[(ln, org)] += 1
    present = sum(comp.values())
    return present, dict(comp), pairs


def replay_frames(session_path):
    """Frame data for the artifact replay. Frames are the shipped tool's
    own prefix replays, the same snapshots code_receipt builds for the
    reconstructed repo: frame 0 is the state before the first human
    turn, frame k is the state after human turn k. No new provenance
    logic is introduced here. Returns (frames, meta)."""
    import steering_receipt as sr
    fmt = sr.detect_format(session_path)
    if fmt == "codex":
        segments, meta = sr.parse_codex_session(session_path)
    else:
        segments, meta = sr.parse_session(session_path)
    track = {}
    sr.apply_ops(segments, None, track=track)
    _, impact_per = sr.classify_impact(segments, track)
    first_human = next((i for i, s in enumerate(segments)
                        if not s.get("pre_prompt")), len(segments))
    cuts = [first_human]
    cuts += [i + 1 for i, s in enumerate(segments)
             if not s.get("pre_prompt")]
    human = [s for s in segments if not s.get("pre_prompt")]
    # First pass: per-frame file states, so row order can follow the
    # final frame (largest file first, files gone by the end last).
    states = []
    for cut in cuts:
        files, _, introduced, _ = sr.apply_ops(segments[:cut], None)
        states.append((files, introduced))
    final_files, _ = states[-1]
    final_present = {}
    for fp in set().union(*[set(f) for f, _ in states]):
        final_present[fp] = _replay_file_state(final_files, fp,
                                               impact_per)[0]
    order = sorted(final_present, key=lambda fp: (-final_present[fp], fp))
    frames = []
    prev_pairs = {}
    prev_discards = {}
    for k, (files, introduced) in enumerate(states):
        rows = []
        for fp in order:
            present, comp, pairs = _replay_file_state(files, fp,
                                                      impact_per)
            old = prev_pairs.get(fp, Counter())
            dnow = sum(max(0, old[p] - pairs[p]) for p in old)
            rows.append({"file": fp, "present": present, "comp": comp,
                         "dnow": dnow, "dprev": prev_discards.get(fp, 0)})
            prev_pairs[fp] = pairs
            prev_discards[fp] = dnow
        if k == 0:
            seg_idx, cls, ops, intr, over = None, None, 0, 0, 0
        else:
            s = human[k - 1]
            seg_idx = s["idx"]
            t = track.get(seg_idx) or Counter()
            cls = (impact_per.get(seg_idx) or {}).get("impact_class")
            ops = t["ops_applied"]
            intr = introduced.get(seg_idx, 0)
            over = (t["overlap_earlier_lines"]
                    + t["overlap_delete_lines"])
        frames.append({"turn": k, "segment": seg_idx, "impact": cls,
                       "ops": ops, "introduced": intr, "overlap": over,
                       "lines": sum(r["present"] for r in rows),
                       "files": len(files), "rows": rows})
    scale = max([final_present[fp] for fp in order] or [1])
    meta = {"turns": len(human),
            "final_lines": frames[-1]["lines"] if frames else 0,
            "final_files": frames[-1]["files"] if frames else 0,
            "scale_max": scale}
    return frames, meta


def replay_html(frames, meta):
    """Build the artifact replay page. All frame data is embedded as
    JSON; the page has no external assets and plays nothing on load."""
    title = meta.get("title", "Artifact replay")
    subtitle = meta.get("subtitle", "")
    data = json.dumps({"frames": frames, "scale": meta["scale_max"],
                       "colours": REPLAY_COLOURS,
                       "order": REPLAY_CLASS_ORDER})
    data = data.replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;color:#17222e;background:#f6f8fa;margin:0;padding:24px}}
main{{max-width:900px;margin:0 auto;background:#fff;border:1px solid #dde4ea;border-radius:8px;padding:24px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#5c6b7a;margin:0 0 16px}}
.counters{{display:flex;gap:24px;font-size:15px;margin:12px 0}}
.counters b{{font-size:20px}}
.controls{{display:flex;gap:12px;align-items:center;margin:12px 0 20px;flex-wrap:wrap}}
.controls button{{font-size:15px;padding:6px 16px;cursor:pointer}}
.controls input[type=range]{{flex:1;min-width:200px}}
.event{{color:#5c6b7a;min-height:20px;margin:0 0 16px}}
.rp-row{{display:flex;align-items:center;gap:10px;margin:5px 0}}
.rp-name{{width:220px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}}
.rp-name.pending{{opacity:.45}}
.rp-track{{flex:1;height:14px;background:#e8edf2;border-radius:3px;overflow:hidden;display:flex}}
.rp-seg{{height:100%}} .rp-seg.unmeasured{{border-right:1px solid #9aa7b4;box-sizing:border-box}}
.rp-ghost-now{{height:100%;background:#8a97a5;opacity:.85}}
.rp-ghost-prev{{height:100%;background:#8a97a5;opacity:.3}}
.rp-num{{width:110px;flex:none;font-size:12px;color:#5c6b7a;text-align:right}}
.caption,.method{{font-size:14px;line-height:1.5;color:#37424e}}
.method{{color:#5c6b7a}}
</style></head><body><main>
<h1>{esc(title)}</h1>
<p class="sub">{esc(subtitle)}</p>
<div class="counters">
<div><b id="c-turn">0</b><br>turn</div>
<div><b id="c-lines">0</b><br>lines present</div>
<div><b id="c-files">0</b><br>files present</div>
</div>
<div class="controls">
<button id="play" type="button">Play</button>
<input id="scrub" type="range" min="0" max="{len(frames) - 1}" value="0" step="1" aria-label="Scrub through turns">
<label>Speed <select id="speed" aria-label="Playback speed">
<option value="0.5">0.5x</option><option value="1" selected>1x</option>
<option value="2">2x</option><option value="4">4x</option></select></label>
<span id="frame-label">Frame 0</span>
</div>
<p class="event" id="event"></p>
<div id="rows"></div>
<p class="caption">{esc(REPLAY_CAPTION)}</p>
<p class="method">{esc(REPLAY_METHOD)}</p>
</main>
<script id="replay-data" type="application/json">{data}</script>
<script>
const D = JSON.parse(document.getElementById('replay-data').textContent);
const ORDER = D.order, COL = D.colours, SCALE = D.scale;
const rowsEl = document.getElementById('rows');
const rowEls = {{}};
D.frames[0].rows.forEach(r => {{
  const div = document.createElement('div');
  div.className = 'rp-row';
  div.innerHTML = '<div class="rp-name pending"></div><div class="rp-track"></div><div class="rp-num"></div>';
  div.querySelector('.rp-name').textContent = r.file;
  div.querySelector('.rp-name').title = r.file;
  rowsEl.appendChild(div);
  rowEls[r.file] = div;
}});
let cur = 0, timer = null;
function fmt(n) {{ return n.toLocaleString('en-US'); }}
function eventText(f) {{
  if (f.turn === 0) return 'Before the first prompt. The artifact is empty.';
  let s = 'Turn ' + f.turn + ': ' + (f.impact || 'unknown');
  s += ', ' + f.ops + (f.ops === 1 ? ' op' : ' ops');
  s += ', ' + fmt(f.introduced) + ' lines introduced';
  if (f.overlap) s += ', ' + fmt(f.overlap) + ' earlier lines rewritten';
  return s + '.';
}}
function render(k) {{
  cur = k;
  const f = D.frames[k];
  document.getElementById('c-turn').textContent = f.turn;
  document.getElementById('c-lines').textContent = fmt(f.lines);
  document.getElementById('c-files').textContent = fmt(f.files);
  document.getElementById('frame-label').textContent = 'Frame ' + k + ' of ' + (D.frames.length - 1);
  document.getElementById('event').textContent = eventText(f);
  document.getElementById('scrub').value = k;
  f.rows.forEach(r => {{
    const el = rowEls[r.file];
    if (r.present > 0) {{ el.querySelector('.rp-name').classList.remove('pending'); }}
    const track = el.querySelector('.rp-track');
    track.innerHTML = '';
    ORDER.forEach(cls => {{
      const n = r.comp[cls] || 0;
      if (!n) return;
      const d = document.createElement('div');
      d.className = 'rp-seg' + (cls === 'unmeasured' ? ' unmeasured' : '');
      d.style.width = (100 * n / SCALE) + '%';
      d.style.background = COL[cls];
      track.appendChild(d);
    }});
    if (r.dnow) {{
      const d = document.createElement('div');
      d.className = 'rp-ghost-now';
      d.style.width = (100 * r.dnow / SCALE) + '%';
      track.appendChild(d);
    }}
    if (r.dprev) {{
      const d = document.createElement('div');
      d.className = 'rp-ghost-prev';
      d.style.width = (100 * r.dprev / SCALE) + '%';
      track.appendChild(d);
    }}
    el.querySelector('.rp-num').textContent = fmt(r.present) + ' lines';
  }});
}}
function stop() {{ if (timer) {{ clearInterval(timer); timer = null; }} document.getElementById('play').textContent = 'Play'; }}
function startTimer() {{
  const speed = parseFloat(document.getElementById('speed').value);
  timer = setInterval(() => {{
    if (cur >= D.frames.length - 1) {{ stop(); return; }}
    render(cur + 1);
  }}, 900 / speed);
}}
document.getElementById('play').addEventListener('click', () => {{
  if (timer) {{ stop(); return; }}
  if (cur >= D.frames.length - 1) render(0);
  document.getElementById('play').textContent = 'Pause';
  startTimer();
}});
document.getElementById('speed').addEventListener('change', () => {{
  if (!timer) return;
  clearInterval(timer);
  startTimer();
}});
document.getElementById('scrub').addEventListener('input', e => render(parseInt(e.target.value, 10)));
render(0);
</script>
</body></html>"""


def replay_main(argv):
    """CLI: steerprint --replay session.jsonl [--receipt receipt.json]
    -o replay.html. Frames come from the shipped replay; the receipt,
    when given, supplies only the header label, mark, and post-first
    share, never frame data."""
    args = list(argv)
    out_path = Path("artifact-replay.html")
    if "-o" in args:
        out_path = Path(args[args.index("-o") + 1])
    receipt_path = None
    if "--receipt" in args:
        receipt_path = args[args.index("--receipt") + 1]
    pos = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ("-o", "--receipt"):
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        pos.append(a)
    if len(pos) != 1:
        sys.exit("--replay takes exactly one session")
    frames, meta = replay_frames(Path(pos[0]))
    title = "Artifact replay"
    subtitle = (f"{meta['turns']} human turns. "
                f"{meta['final_lines']:,} lines in {meta['final_files']} files.")
    if receipt_path:
        r = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        title = f"Artifact replay: {r.get('label', 'session')}"
        mark = (r.get("mark") or {}).get("category")
        pct = headline_pct(r.get("git_join") or {})
        extra = []
        if mark:
            extra.append(f"mark {mark}")
        if pct is not None:
            extra.append(f"{pct}% of lines arrived after the first prompt")
        if extra:
            subtitle += " " + ", ".join(extra) + "."
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(replay_html(frames, {**meta, "title": title,
                                             "subtitle": subtitle}),
                        encoding="utf-8")
    print(f"wrote replay {out_path} ({out_path.stat().st_size:,} bytes, "
          f"{len(frames)} frames)")


REWORK_CAPTION = (
    "Each node is one human turn, placed left to right in turn order "
    "and in the lane for its kind, so kind reads by position as well "
    "as by color. An edge from "
    "a later turn to an earlier turn means the later turn removed "
    "lines the earlier turn introduced. Edge thickness grows with the "
    "number of lines removed. Long arcs reach far back in time. Short "
    "arcs join neighbouring turns. The same graph in 3D sits behind "
    "the 3D spiral toggle. Edges count discards in the replay. They "
    "are not a claim about what the author meant. The one-prompt "
    "control has a single turn and therefore no rework to show.")

REWORK_HEAVY_THRESHOLD = 50

REWORK_METHOD = (
    "The graph comes from the shipped prefix replays, the same "
    "snapshots the artifact replay uses. For each turn, the lines of "
    "each earlier turn present before the turn but absent after it "
    "become one edge, weighted by the count. Counts cover non-blank "
    "lines only, matching the receipt.")

REWORK_LANE_ORDER = ["first", "followup", "correction", "after_error"]

REWORK_KIND_LABELS = {
    "first": "First prompt",
    "followup": "Follow-up prompt",
    "correction": "Correction prompt",
    "after_error": "Prompt after an error",
}

REWORK_KIND_COLOURS = {
    "first": "#46689e",
    "followup": "#2f8f83",
    "correction": "#e07a3f",
    "after_error": "#c94f5e",
}


def _rework_kind(turn, seg):
    if turn == 1:
        return "first"
    if seg.get("correction_keyword"):
        return "correction"
    if seg.get("after_error"):
        return "after_error"
    return "followup"


def rework_graph(session_path):
    """The rework graph of one session, derived only from the shipped
    tool's own prefix replays, the same snapshots the artifact replay
    uses. For each frame transition, lines of an earlier turn present
    before the turn but absent after it become one directed edge from
    the later turn to the earlier turn, weighted by the count. No new
    provenance logic is introduced here. Node labels carry turn numbers
    and kinds only, never prompt text. Returns a graph dict."""
    import math
    import steering_receipt as sr
    fmt = sr.detect_format(session_path)
    if fmt == "codex":
        segments, meta = sr.parse_codex_session(session_path)
    else:
        segments, meta = sr.parse_session(session_path)
    human = [s for s in segments if not s.get("pre_prompt")]
    idx_to_turn = {s["idx"]: k + 1 for k, s in enumerate(human)}
    first_human = next((i for i, s in enumerate(segments)
                        if not s.get("pre_prompt")), len(segments))
    cuts = [first_human]
    cuts += [i + 1 for i, s in enumerate(segments)
             if not s.get("pre_prompt")]
    nodes = {}
    edges = Counter()
    prev = {}
    for k, cut in enumerate(cuts):
        files, _, introduced, _ = sr.apply_ops(segments[:cut], None)
        cur = {}
        for fp, lines in files.items():
            c = Counter()
            for ln, org in lines:
                if ln.strip():
                    c[(ln, org)] += 1
            cur[fp] = c
        if k > 0:
            s = human[k - 1]
            nodes[k] = {"turn": k, "segment": s["idx"],
                        "kind": _rework_kind(k, s),
                        "introduced": introduced.get(s["idx"], 0)}
            for fp in set(prev) | set(cur):
                old, new = prev.get(fp, Counter()), cur.get(fp, Counter())
                for (ln, org), n in old.items():
                    lost = n - new.get((ln, org), 0)
                    if lost > 0 and org in idx_to_turn:
                        edges[(k, idx_to_turn[org])] += lost
        prev = cur
    outgoing = Counter()
    incoming = Counter()
    for (later, earlier), w in edges.items():
        outgoing[later] += w
        incoming[earlier] += w
    for t, node in nodes.items():
        node["removed_from_earlier"] = outgoing[t]
        node["removed_by_later"] = incoming[t]
        node["surviving"] = node["introduced"] - incoming[t]
    edge_list = [{"from": later, "to": earlier, "weight": w,
                  "span": later - earlier}
                 for (later, earlier), w in sorted(edges.items())]
    layout = {}
    for t in range(1, len(nodes) + 1):
        ang = (t - 1) * 0.9
        rad = 90 + 3.2 * t
        layout[t] = {"x": rad * math.cos(ang),
                     "y": (t - 1) * 14.0 - 7.0 * len(nodes),
                     "z": rad * math.sin(ang)}
    total_weight = sum(edges.values())
    return {"nodes": [nodes[t] for t in sorted(nodes)],
            "edges": edge_list, "layout": layout,
            "turns": len(nodes), "edge_count": len(edge_list),
            "total_weight": total_weight,
            "final_lines": sum(n["surviving"] for n in nodes.values())}


def rework_html(graph, meta):
    """Build the rework web page. All graph data is embedded as
    JSON. The page opens on a lanes diagram: turns in order left to
    right, one horizontal lane per kind, arcs back to the turn each
    later turn rewrote. The 3D spiral of the same graph sits behind
    a toggle.
    The page has no external assets, plays nothing on load, and is
    driven by click for detail, with drag to orbit and scroll to zoom
    in the spiral view only."""
    title = meta.get("title", "Rework web")
    subtitle = meta.get("subtitle", "")
    data = json.dumps({"nodes": graph["nodes"], "edges": graph["edges"],
                       "layout": {str(k): v for k, v in
                                  graph["layout"].items()},
                       "kinds": REWORK_KIND_LABELS,
                       "colours": REWORK_KIND_COLOURS})
    data = data.replace("<", "\\u003c")
    if graph["edges"]:
        heavy = max(graph["edges"], key=lambda e: e["weight"])
        reworker = max(graph["nodes"],
                       key=lambda n: n["removed_from_earlier"])
        callouts = (f"Look first at turn {heavy['from']}, which removed "
                    f"{heavy['weight']:,} lines from turn {heavy['to']}, "
                    "the single biggest rewrite. "
                    f"Turn {reworker['turn']} removed "
                    f"{reworker['removed_from_earlier']:,} lines from "
                    "earlier turns, more than any other turn.")
    else:
        callouts = "A single turn has no rework to show."
    css = """
body{font-family:system-ui,-apple-system,sans-serif;color:#17222e;background:#f6f8fa;margin:0;padding:24px}
main{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #dde4ea;border-radius:8px;padding:24px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#5c6b7a;margin:0 0 16px}
.howto{font-size:15px;margin:0 0 12px}
.hint{font-size:14px;color:#5c6b7a;margin:0 0 12px}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 12px}
button{font-size:14px;padding:6px 14px;cursor:pointer}
.viewbtn{background:#fff;color:#17222e;border:1px solid #dde4ea;border-radius:6px}
.viewbtn.active{background:#17222e;color:#fff;border-color:#17222e}
.heavy{font-size:14px}
.stage{display:flex;gap:20px;flex-wrap:wrap}
canvas{background:#fbfcfe;border:1px solid #dde4ea;border-radius:8px;cursor:pointer;flex:1;min-width:320px}
.panel{width:280px;flex:none;border:1px solid #dde4ea;border-radius:8px;padding:16px;height:fit-content}
.panel h2{font-size:17px;margin:0 0 8px}
.panel p{font-size:14px;line-height:1.6;margin:6px 0}
.panel .big{font-size:24px;font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:#5c6b7a;margin:14px 0}
.legend .sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.callouts,.caption,.method{font-size:14px;line-height:1.5;color:#37424e}
.method{color:#5c6b7a}
"""
    body = f"""<main>
<h1>{esc(title)}</h1>
<p class="sub">{esc(subtitle)}</p>
<p class="howto">How to read this: find turn 1, follow an arc back to the turn it rewrote, click a node for its detail.</p>
<div class="controls">
<button id="view-timeline" type="button" class="viewbtn active">Timeline</button>
<button id="view-spiral" type="button" class="viewbtn">3D spiral</button>
<label class="heavy"><input id="heavy" type="checkbox"> Heavy edges only (at least {REWORK_HEAVY_THRESHOLD} lines each)</label>
<button id="reset" type="button">Reset view</button>
</div>
<p class="hint" id="hint">Turns run left to right in order, one lane per kind. Arcs join a turn to the earlier turn it rewrote.</p>
<div class="stage">
<canvas id="web" width="1000" height="700"></canvas>
<div class="panel" id="panel">
<h2>Pick a turn</h2>
<p>Click any node to see what that turn introduced, what it removed
from earlier turns, and what later turns removed of it.</p>
</div>
</div>
<div class="legend">
<span><span class="sw" style="background:#46689e"></span>First prompt</span>
<span><span class="sw" style="background:#2f8f83"></span>Follow-up prompt</span>
<span><span class="sw" style="background:#e07a3f"></span>Correction prompt</span>
<span><span class="sw" style="background:#c94f5e"></span>Prompt after an error</span>
<span><span class="sw" style="background:#8a97a5"></span>Short arc, nearby turn</span>
<span><span class="sw" style="background:#2f8f83"></span>Medium arc</span>
<span><span class="sw" style="background:#e07a3f"></span>Long arc, far back in time</span>
<span><span class="sw" style="background:#17222e;width:15px;height:15px;border-radius:50%"></span>Bigger node: more lines introduced</span>
</div>
<p class="callouts">{esc(callouts)}</p>
<p class="caption">{esc(REWORK_CAPTION)}</p>
<p class="method">{esc(REWORK_METHOD)}</p>
</main>
"""
    js = """
const D = JSON.parse(document.getElementById('rework-data').textContent);
const canvas = document.getElementById('web');
const ctx = canvas.getContext('2d');
const W = canvas.width, H = canvas.height;
const HEAVY = HEAVY_THRESHOLD;
let view = 'timeline';
let heavyOnly = false;
let yaw = -0.6, pitch = 0.45, zoom = 1.0, selected = null;
function spanColour(span) {
  if (span <= 3) return '#8a97a5';
  if (span <= 15) return '#2f8f83';
  return '#e07a3f';
}
function nodeRadius(n) {
  return 5 + Math.min(9, Math.sqrt(n.introduced) * 0.45);
}
function visibleEdges() {
  return heavyOnly ? D.edges.filter(e => e.weight >= HEAVY) : D.edges;
}
function project(p) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const x1 = p.x * cy + p.z * sy;
  const z1 = -p.x * sy + p.z * cy;
  const y1 = p.y * cp - z1 * sp;
  const z2 = p.y * sp + z1 * cp;
  const s = zoom * 620 / (620 + z2);
  return {x: W / 2 + x1 * s, y: H / 2 - y1 * s, z: z2, s: s};
}
const LANES = LANE_ORDER_JSON;
function laneGeom() {
  return {gutter: 170, top: 30, band: 150, right: W - 30};
}
function lanePos(n) {
  const g = laneGeom();
  const count = D.nodes.length;
  const x = count > 1 ? g.gutter + (n.turn - 1) / (count - 1) * (g.right - g.gutter) : (g.gutter + g.right) / 2;
  const y = g.top + LANES.indexOf(n.kind) * g.band + g.band / 2;
  return {x: x, y: y, r: nodeRadius(n)};
}
function drawTimeline() {
  ctx.clearRect(0, 0, W, H);
  const g = laneGeom();
  const pos = {};
  D.nodes.forEach(n => { pos[n.turn] = lanePos(n); });
  LANES.forEach((kind, i) => {
    const y0 = g.top + i * g.band;
    if (i % 2 === 0) {
      ctx.fillStyle = '#f4f7f9';
      ctx.fillRect(0, y0, W, g.band);
    }
    ctx.strokeStyle = '#dde4ea';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y0);
    ctx.lineTo(W, y0);
    ctx.stroke();
    const count = D.nodes.filter(m => m.kind === kind).length;
    ctx.fillStyle = '#5c6b7a';
    ctx.font = '13px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(D.kinds[kind] + ' (' + count + ')', 12, y0 + g.band / 2 + 4);
  });
  ctx.strokeStyle = '#dde4ea';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, g.top + LANES.length * g.band);
  ctx.lineTo(W, g.top + LANES.length * g.band);
  ctx.stroke();
  visibleEdges().forEach(e => {
    const a = pos[e.from], b = pos[e.to];
    const incident = selected !== null && (e.from === selected || e.to === selected);
    ctx.globalAlpha = selected === null ? 0.55 : (incident ? 0.95 : 0.10);
    ctx.strokeStyle = spanColour(e.span);
    ctx.lineWidth = 1 + Math.min(3, e.weight / 80);
    const mx = (a.x + b.x) / 2;
    const lift = Math.min(30 + Math.min(160, e.span * 6), Math.min(a.y, b.y) - 12);
    const top = Math.min(a.y, b.y) - lift;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo(mx, top, b.x, b.y);
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
  D.nodes.forEach(n => {
    const p = pos[n.turn];
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = D.colours[n.kind];
    ctx.fill();
    if (selected === n.turn) {
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = '#17222e';
      ctx.stroke();
    }
    ctx.fillStyle = '#17222e';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(String(n.turn), p.x, p.y + p.r + 14);
  });
  ctx.textAlign = 'left';
}
function drawSpiral() {
  ctx.clearRect(0, 0, W, H);
  const pts = {};
  D.nodes.forEach(n => { pts[n.turn] = project(D.layout[String(n.turn)]); });
  const edges = visibleEdges().map(e => {
    const a = pts[e.from], b = pts[e.to];
    return {e: e, depth: (a.z + b.z) / 2, a: a, b: b};
  });
  edges.sort((p, q) => q.depth - p.depth);
  edges.forEach(item => {
    const e = item.e, a = item.a, b = item.b;
    const incident = selected !== null && (e.from === selected || e.to === selected);
    ctx.globalAlpha = selected === null ? 0.55 : (incident ? 0.95 : 0.10);
    ctx.strokeStyle = spanColour(e.span);
    ctx.lineWidth = 1 + Math.min(3, e.weight / 80);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const lift = 18 + Math.min(90, e.span * 4);
    const cx = mx - dy / len * lift, cy = my + dx / len * lift;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo(cx, cy, b.x, b.y);
    ctx.stroke();
  });
  ctx.globalAlpha = 1;
  const nodes = D.nodes.map(n => ({n: n, p: pts[n.turn]}));
  nodes.sort((p, q) => q.p.z - p.p.z);
  nodes.forEach(item => {
    const n = item.n, p = item.p;
    const r = nodeRadius(n);
    ctx.beginPath();
    ctx.arc(p.x, p.y, r * p.s, 0, Math.PI * 2);
    ctx.fillStyle = D.colours[n.kind];
    ctx.fill();
    if (selected === n.turn) {
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = '#17222e';
      ctx.stroke();
    }
    ctx.fillStyle = '#17222e';
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillText(String(n.turn), p.x + r * p.s + 4, p.y + 4);
  });
}
function draw() {
  if (view === 'timeline') drawTimeline(); else drawSpiral();
}
function showPanel(n) {
  const panel = document.getElementById('panel');
  panel.innerHTML = '<h2>Turn ' + n.turn + '</h2>'
    + '<p class="big">' + D.kinds[n.kind] + '</p>'
    + '<p>Introduced ' + n.introduced.toLocaleString('en-US') + ' lines.</p>'
    + '<p>Removed ' + n.removed_from_earlier.toLocaleString('en-US')
    + ' lines from earlier turns.</p>'
    + '<p>Later turns removed ' + n.removed_by_later.toLocaleString('en-US')
    + ' lines of this turn.</p>'
    + '<p>' + n.surviving.toLocaleString('en-US')
    + ' lines of this turn survive to the final artifact.</p>';
}
function nodeAt(mx, my) {
  let best = null, bestD = 20;
  D.nodes.forEach(n => {
    const p = view === 'timeline' ? lanePos(n) : project(D.layout[String(n.turn)]);
    const d = Math.hypot(p.x - mx, p.y - my);
    if (d < bestD) { bestD = d; best = n; }
  });
  return best;
}
function setView(v) {
  view = v;
  document.getElementById('view-timeline').className = v === 'timeline' ? 'viewbtn active' : 'viewbtn';
  document.getElementById('view-spiral').className = v === 'spiral' ? 'viewbtn active' : 'viewbtn';
  document.getElementById('hint').textContent = v === 'timeline'
    ? 'Turns run left to right in order, one lane per kind. Arcs join a turn to the earlier turn it rewrote.'
    : 'Drag to orbit. Scroll to zoom. Click a node for its detail.';
  draw();
}
document.getElementById('view-timeline').addEventListener('click', () => setView('timeline'));
document.getElementById('view-spiral').addEventListener('click', () => setView('spiral'));
document.getElementById('heavy').addEventListener('change', e => { heavyOnly = e.target.checked; draw(); });
let drag = null, dragged = false;
canvas.addEventListener('pointerdown', e => {
  if (view !== 'spiral') return;
  drag = {x: e.clientX, y: e.clientY, yaw: yaw, pitch: pitch};
  dragged = false;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 6) dragged = true;
  yaw = drag.yaw + (e.clientX - drag.x) * 0.01;
  pitch = Math.max(-1.2, Math.min(1.2, drag.pitch + (e.clientY - drag.y) * 0.01));
  draw();
});
canvas.addEventListener('pointerup', () => { drag = null; });
canvas.addEventListener('wheel', e => {
  if (view !== 'spiral') return;
  e.preventDefault();
  zoom = Math.max(0.4, Math.min(3.0, zoom * (e.deltaY < 0 ? 1.1 : 0.9)));
  draw();
}, {passive: false});
canvas.addEventListener('click', e => {
  if (dragged) { dragged = false; return; }
  const rect = canvas.getBoundingClientRect();
  const mx = (e.clientX - rect.left) * (W / rect.width);
  const my = (e.clientY - rect.top) * (H / rect.height);
  const best = nodeAt(mx, my);
  if (best) { selected = best.turn; showPanel(best); draw(); }
});
document.getElementById('reset').addEventListener('click', () => {
  yaw = -0.6; pitch = 0.45; zoom = 1.0; selected = null; draw();
});
draw();
"""
    js = js.replace("HEAVY_THRESHOLD", str(REWORK_HEAVY_THRESHOLD))
    js = js.replace("LANE_ORDER_JSON", json.dumps(REWORK_LANE_ORDER))
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{esc(title)}</title>\n<style>{css}</style></head><body>"
            + body +
            f"<script id=\"rework-data\" type=\"application/json\">{data}</script>\n"
            f"<script>{js}</script>\n</body></html>")


def rework_main(argv):
    """CLI: steerprint --rework session.jsonl [--receipt receipt.json]
    -o rework-web-3d.html. The graph comes from the shipped rework
    builder; the receipt, when given, supplies only the header label,
    mark, and post-first share, never graph data."""
    args = list(argv)
    out_path = Path("rework-web-3d.html")
    if "-o" in args:
        out_path = Path(args[args.index("-o") + 1])
    receipt_path = None
    if "--receipt" in args:
        receipt_path = args[args.index("--receipt") + 1]
    pos = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ("-o", "--receipt"):
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        pos.append(a)
    if len(pos) != 1:
        sys.exit("--rework takes exactly one session")
    graph = rework_graph(Path(pos[0]))
    title = "Rework web"
    subtitle = (f"{graph['turns']} human turns. {graph['edge_count']} "
                f"rework edges covering {graph['total_weight']:,} lines.")
    if receipt_path:
        r = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        title = f"Rework web: {r.get('label', 'session')}"
        mark = (r.get("mark") or {}).get("category")
        pct = headline_pct(r.get("git_join") or {})
        extra = []
        if mark:
            extra.append(f"mark {mark}")
        if pct is not None:
            extra.append(f"{pct}% of lines arrived after the first prompt")
        if extra:
            subtitle += " " + ", ".join(extra) + "."
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rework_html(graph, {"title": title,
                                            "subtitle": subtitle}),
                        encoding="utf-8")
    print(f"wrote rework {out_path} ({out_path.stat().st_size:,} bytes, "
          f"{graph['edge_count']} edges)")


# ---------------------------------------------------------------- dual timeline
# One shared turn axis, two lanes: the human on top (one shape-coded
# mark per turn, decision dots above the turns where the agent asked
# a question) and the artifact below (lines present after each turn,
# from the replay frames). Vertical alignment is the point: a
# correction mark lines up with the dip it caused.

DUAL_W = 1000
DUAL_H = 640
DUAL_X_GUTTER = 90
DUAL_X_RIGHT = 970
DUAL_TOP_Y = 120
DUAL_AXIS_Y = 170
DUAL_ART_TOP = 210
DUAL_ART_BOT = 560

DUAL_KIND_SHAPES = {
    "first": "circle",
    "followup": "square",
    "correction": "triangle",
    "after_error": "diamond",
}

DUAL_SHAPE_GLYPHS = {
    "first": "\u25cf",
    "followup": "\u25a0",
    "correction": "\u25b2",
    "after_error": "\u25c6",
}

DUAL_KIND_NOUNS = {
    "first": "first prompt",
    "followup": "follow-up",
    "correction": "correction",
    "after_error": "prompt after an error",
}

DUAL_CAPTION = (
    "Top lane: one mark per human turn, shaped by its kind. "
    "A dot above a mark means the agent asked the human a question "
    "there. Bottom lane: lines in the artifact after each turn, from "
    "the replay frames. Decision markers show the human answering "
    "the agent's questions. They do not show who thought of what.")

DUAL_CAPTION_NO_DECISIONS = (
    "Top lane: one mark per human turn, shaped by its kind. The "
    "agent asked no questions in this session, so there are no "
    "decision markers. Bottom lane: lines in the artifact after "
    "each turn, from the replay frames.")

DUAL_METHOD = (
    "Turns, kinds, and removals come from the shipped prefix "
    "replays, the same snapshots the artifact replay uses. Decision "
    "markers come from the receipt's own AskUserQuestion parsing, "
    "classified the same way and aligned to turns by the same "
    "segmentation. Counts and categories only, no question text.")


def _dual_zero_decisions():
    return {"calls": 0, "points": 0, "followed": 0, "diverged": 0,
            "free_text": 0, "unparseable": 0, "rejected": 0,
            "dismissed": 0, "errored": 0, "input_unparseable": 0}


def dual_x(turn, turns):
    """Shared horizontal position of one turn, used by both lanes so
    a mark in the top lane lines up exactly with the artifact state
    below it."""
    if turns <= 1:
        return (DUAL_X_GUTTER + DUAL_X_RIGHT) / 2
    return (DUAL_X_GUTTER
            + (turn - 1) / (turns - 1) * (DUAL_X_RIGHT - DUAL_X_GUTTER))


def dual_timeline_decisions(session_path):
    """Attribute the receipt's AskUserQuestion events to human turns.

    Re-walks the transcript with the same segmentation parse_session
    uses (a user text record opens a segment), pairing each call with
    its tool result by tool use id, and classifies each call with the
    receipt's own _classify_decision_call. The result is checked
    against the receipt's own decision_events (same calls, same
    decision points), so a drift in either parser fails loudly
    instead of misplacing a marker. Codex sessions have no
    AskUserQuestion events by construction, so they return zeros."""
    import steering_receipt as sr
    empty = {"turns": {}, "total_points": 0, "total_calls": 0,
             "turns_with_decisions": []}
    if sr.detect_format(session_path) == "codex":
        return empty
    segments, meta = sr.parse_session(session_path)
    idx_to_turn = {s["idx"]: k + 1 for k, s in
                   enumerate(s for s in segments if not s.get("pre_prompt"))}
    calls = {}
    call_seg = {}
    results = {}
    cur = None
    seg_count = 0
    for line in Path(session_path).read_text(encoding="utf-8",
                                            errors="replace").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = r.get("message") or {}
        if r.get("type") == "user":
            content = msg.get("content")
            blocks = content if isinstance(content, list) else (
                [{"type": "text", "text": content}]
                if isinstance(content, str) else [])
            for blk in blocks:
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    results[blk.get("tool_use_id")] = (
                        sr._decision_result_text(blk.get("content")),
                        bool(blk.get("is_error")))
            texts = [b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(texts).strip()
            if joined:
                if r.get("isMeta") or joined.startswith(
                        ("<command-", "<local-command", "Caveat:")):
                    continue
                cur = seg_count
                seg_count += 1
        if r.get("type") == "assistant":
            if cur is None:
                cur = seg_count
                seg_count += 1
            for blk in [b for b in (msg.get("content") or [])
                        if isinstance(b, dict)]:
                if blk.get("type") == "tool_use" and \
                        blk.get("name") == "AskUserQuestion":
                    cid = blk.get("id")
                    calls[cid] = blk.get("input") or {}
                    if cid not in call_seg:
                        call_seg[cid] = cur
    if seg_count != len(segments):
        raise ValueError("dual timeline decision walk opened "
                         f"{seg_count} segments, the receipt parser "
                         f"opened {len(segments)}")
    if len(calls) != len(meta["decision_events"]):
        raise ValueError("dual timeline decision walk found "
                         f"{len(calls)} AskUserQuestion calls, the "
                         "receipt parser found "
                         f"{len(meta['decision_events'])}")
    if [c for c in calls.values()] != \
            [e[0] for e in meta["decision_events"]]:
        raise ValueError("dual timeline decision walk disagrees with "
                         "the receipt parser on the calls themselves")
    per_turn = {}
    total_points = 0
    for cid, call_input in calls.items():
        res = results.get(cid)
        cls = sr._classify_decision_call(
            call_input, res[0] if res else None, res[1] if res else False)
        turn = idx_to_turn.get(call_seg[cid])
        if turn is None:
            continue
        d = per_turn.setdefault(turn, _dual_zero_decisions())
        d["calls"] += 1
        if cls["status"] == "answered":
            for q in cls["questions"]:
                d["points"] += 1
                total_points += 1
                if q["class"] == "followed_recommendation":
                    d["followed"] += 1
                elif q["class"] == "diverged_to_listed":
                    d["diverged"] += 1
                elif q["class"] == "free_text":
                    d["free_text"] += 1
                else:
                    d["unparseable"] += 1
        elif cls["status"] in d:
            d[cls["status"]] += 1
    receipt_points = sr.build_decisions(
        meta["decision_events"])["decision_points"]
    if total_points != receipt_points:
        raise ValueError("dual timeline decision walk counted "
                         f"{total_points} decision points, the receipt "
                         f"counts {receipt_points}")
    return {"turns": per_turn, "total_points": total_points,
            "total_calls": len(calls),
            "turns_with_decisions": sorted(per_turn)}


def _join_turns(turns):
    names = [str(t) for t in turns]
    if len(names) == 1:
        return "turn " + names[0]
    if len(names) == 2:
        return "turns " + " and ".join(names)
    return "turns " + ", ".join(names[:-1]) + ", and " + names[-1]


def dual_timeline_data(session_path):
    """One row per human turn, carrying both lanes: the human's mark
    (kind, lines introduced, lines removed from earlier turns) and
    the artifact's state after the turn (lines and files present),
    plus the turn's decision counts. Both lanes share one x per turn.
    The story callout is computed from the rows, never hardcoded."""
    graph = rework_graph(session_path)
    frames, fmeta = replay_frames(session_path)
    turns = graph["turns"]
    if len(frames) != turns + 1:
        raise ValueError("dual timeline: the replay produced "
                         f"{len(frames)} frames for {turns} turns")
    decisions = dual_timeline_decisions(session_path)
    nodes = {n["turn"]: n for n in graph["nodes"]}
    step = ((DUAL_X_RIGHT - DUAL_X_GUTTER) / (turns - 1)
            if turns > 1 else 0)
    rows = []
    for t in range(1, turns + 1):
        n = nodes[t]
        rows.append({"turn": t, "kind": n["kind"], "x": dual_x(t, turns),
                     "introduced": n["introduced"],
                     "removed": n["removed_from_earlier"],
                     "lines_after": frames[t]["lines"],
                     "files_after": frames[t]["files"],
                     "decisions": decisions["turns"].get(
                         t, _dual_zero_decisions())})
    final_lines = rows[-1]["lines_after"] if rows else 0
    final_files = rows[-1]["files_after"] if rows else 0
    if final_lines != fmeta["final_lines"] or \
            final_lines != graph["final_lines"]:
        raise ValueError("dual timeline: final lines disagree between "
                         "the replay frames and the rework graph")
    if final_files != fmeta["final_files"]:
        raise ValueError("dual timeline: final file count disagrees "
                         "with the replay frames")
    drops = []
    for i, row in enumerate(rows):
        before = rows[i - 1]["lines_after"] if i else 0
        drops.append((row["lines_after"] - before, row["turn"]))
    drop, drop_turn = min(drops)
    if drop < 0:
        drow = rows[drop_turn - 1]
        callout = (f"Turn {drop_turn} is the biggest dip. The artifact "
                   f"fell by {abs(drop):,} lines after a "
                   f"{DUAL_KIND_NOUNS[drow['kind']]} turn that removed "
                   f"{drow['removed']:,} lines from earlier turns.")
    else:
        callout = ("The artifact never shrank after a turn. Every turn "
                   "left it at least as large as before.")
    if decisions["turns_with_decisions"]:
        callout += (" The agent asked the human a question on "
                    + _join_turns(decisions["turns_with_decisions"])
                    + ".")
    else:
        callout += " The agent asked no questions in this session."
    max_lines = max([r["lines_after"] for r in rows] or [1])
    tick_step = 1000 if max_lines <= 5000 else 5000
    ticks = list(range(0, max_lines + 1, tick_step))
    return {"turns": rows, "x0": dual_x(1, turns) - step,
            "max_lines": max_lines, "ticks": ticks,
            "final_lines": final_lines, "final_files": final_files,
            "total_points": decisions["total_points"],
            "total_calls": decisions["total_calls"],
            "turns_with_decisions": decisions["turns_with_decisions"],
            "biggest_drop": {"turn": drop_turn, "net": drop},
            "callout": callout,
            "has_decisions": bool(decisions["turns_with_decisions"])}


def dual_timeline_html(data, meta):
    """Build the dual timeline page. All data is embedded as JSON.
    The page has no external assets, plays nothing on load, and is
    driven by click for detail."""
    title = meta.get("title", "Dual timeline")
    subtitle = meta.get("subtitle", "")
    caption = (DUAL_CAPTION if data["has_decisions"]
               else DUAL_CAPTION_NO_DECISIONS)
    payload = json.dumps({"turns": data["turns"], "x0": data["x0"],
                          "max_lines": data["max_lines"],
                          "ticks": data["ticks"],
                          "kinds": REWORK_KIND_LABELS,
                          "colours": REWORK_KIND_COLOURS,
                          "shapes": DUAL_KIND_SHAPES})
    payload = payload.replace("<", "\\u003c")
    css = """
body{font-family:system-ui,-apple-system,sans-serif;color:#17222e;background:#f6f8fa;margin:0;padding:24px}
main{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #dde4ea;border-radius:8px;padding:24px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#5c6b7a;margin:0 0 16px}
.howto{font-size:15px;margin:0 0 12px}
.stage{display:flex;gap:20px;flex-wrap:wrap}
canvas{background:#fbfcfe;border:1px solid #dde4ea;border-radius:8px;cursor:pointer;flex:1;min-width:320px}
.panel{width:280px;flex:none;border:1px solid #dde4ea;border-radius:8px;padding:16px;height:fit-content}
.panel h2{font-size:17px;margin:0 0 8px}
.panel p{font-size:14px;line-height:1.6;margin:6px 0}
.panel .big{font-size:24px;font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:#5c6b7a;margin:14px 0}
.legend .shape{font-size:15px;margin-right:6px}
.callouts,.caption,.method{font-size:14px;line-height:1.5;color:#37424e}
.method{color:#5c6b7a}
"""
    legend = "".join(
        f"<span><span class=\"shape\" style=\"color:"
        f"{REWORK_KIND_COLOURS[k]}\">{DUAL_SHAPE_GLYPHS[k]}</span>"
        f"{REWORK_KIND_LABELS[k]}</span>"
        for k in REWORK_LANE_ORDER)
    if data["has_decisions"]:
        legend += ("<span><span class=\"shape\" style=\"color:#17222e\">"
                   "\u25cf</span>Decision point (agent asked, human "
                   "answered)</span>")
    legend += ("<span><span class=\"shape\" style=\"color:#2f8f83\">"
               "\u25a0</span>Area: lines in the artifact after each "
               "turn</span>")
    body = f"""<main>
<h1>{esc(title)}</h1>
<p class="sub">{esc(subtitle)}</p>
<p class="howto">How to read this: the top lane is the human, the bottom lane is the artifact, and both share one turn axis. Click any mark or point for that turn.</p>
<div class="stage">
<canvas id="dual" width="{DUAL_W}" height="{DUAL_H}"></canvas>
<div class="panel" id="panel">
<h2>Pick a turn</h2>
<p>Click any mark in the top lane or any point in the bottom lane to see what that turn introduced, what it removed from earlier turns, how large the artifact stood after it, and whether the agent asked a question there.</p>
</div>
</div>
<div class="legend">{legend}</div>
<p class="callouts">{esc(data["callout"])}</p>
<p class="caption">{esc(caption)}</p>
<p class="method">{esc(DUAL_METHOD)}</p>
</main>
"""
    js = """
const D = JSON.parse(document.getElementById('dual-data').textContent);
const canvas = document.getElementById('dual');
const ctx = canvas.getContext('2d');
const W = 1000, H = 640;
const TOP_Y = 120, AXIS_Y = 170, ART_TOP = 210, ART_BOT = 560;
let selected = null;
function yLines(v) { return ART_BOT - (v / D.max_lines) * (ART_BOT - ART_TOP); }
function drawShape(shape, x, y, r) {
  ctx.beginPath();
  if (shape === 'circle') { ctx.arc(x, y, r, 0, Math.PI * 2); }
  else if (shape === 'square') { ctx.rect(x - r, y - r, 2 * r, 2 * r); }
  else if (shape === 'triangle') {
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y + r * 0.8);
    ctx.lineTo(x - r, y + r * 0.8);
    ctx.closePath();
  } else if (shape === 'diamond') {
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
  } else {
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }
}
function drawHuman() {
  ctx.fillStyle = '#5c6b7a';
  ctx.font = '13px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Human', 12, 64);
  D.turns.forEach(t => {
    if (t.decisions.calls > 0) {
      ctx.strokeStyle = '#8a97a5';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(t.x, TOP_Y - 36);
      ctx.lineTo(t.x, TOP_Y - 14);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(t.x, TOP_Y - 40, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#17222e';
      ctx.fill();
    }
    drawShape(D.shapes[t.kind], t.x, TOP_Y, 10);
    ctx.fillStyle = D.colours[t.kind];
    ctx.fill();
    if (selected === t.turn) {
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = '#17222e';
      ctx.stroke();
    }
    ctx.fillStyle = '#17222e';
    ctx.font = '10px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(String(t.turn), t.x, TOP_Y + 28);
  });
  ctx.textAlign = 'left';
  ctx.strokeStyle = '#dde4ea';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, AXIS_Y);
  ctx.lineTo(W, AXIS_Y);
  ctx.stroke();
}
function drawArtifact() {
  ctx.fillStyle = '#5c6b7a';
  ctx.font = '13px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Artifact', 12, ART_TOP - 8);
  ctx.font = '12px system-ui, sans-serif';
  ctx.textAlign = 'right';
  D.ticks.forEach(tick => {
    const y = yLines(tick);
    if (tick > 0) {
      ctx.strokeStyle = '#e8edf2';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(90, y);
      ctx.lineTo(W - 30, y);
      ctx.stroke();
    }
    ctx.fillStyle = '#5c6b7a';
    ctx.fillText(tick.toLocaleString('en-US'), 84, tick === 0 ? y + 14 : y + 4);
  });
  ctx.beginPath();
  ctx.moveTo(D.x0, yLines(0));
  let prev = 0;
  D.turns.forEach(t => {
    ctx.lineTo(t.x, yLines(prev));
    ctx.lineTo(t.x, yLines(t.lines_after));
    prev = t.lines_after;
  });
  ctx.lineTo(D.turns[D.turns.length - 1].x, yLines(0));
  ctx.closePath();
  ctx.fillStyle = 'rgba(47, 143, 131, 0.18)';
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(D.x0, yLines(0));
  prev = 0;
  D.turns.forEach(t => {
    ctx.lineTo(t.x, yLines(prev));
    ctx.lineTo(t.x, yLines(t.lines_after));
    prev = t.lines_after;
  });
  ctx.strokeStyle = '#2f8f83';
  ctx.lineWidth = 2;
  ctx.stroke();
  const last = D.turns[D.turns.length - 1];
  ctx.fillStyle = '#17222e';
  ctx.font = '13px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(last.lines_after.toLocaleString('en-US') + ' lines in ' + last.files_after + ' files', W - 30, yLines(last.lines_after) - 10);
  ctx.textAlign = 'left';
  if (selected !== null) {
    const t = D.turns[selected - 1];
    ctx.beginPath();
    ctx.arc(t.x, yLines(t.lines_after), 5, 0, Math.PI * 2);
    ctx.fillStyle = '#17222e';
    ctx.fill();
  }
}
function draw() {
  ctx.clearRect(0, 0, W, H);
  drawHuman();
  drawArtifact();
}
function decisionText(d) {
  if (!d.calls) return 'The agent asked no questions on this turn.';
  let s;
  if (d.points) {
    s = 'The agent asked ' + d.points + (d.points === 1 ? ' question' : ' questions') + ' here.';
  } else {
    s = 'The agent asked, but no question was answered here.';
  }
  if (d.followed) s += ' The human followed the marked recommendation ' + d.followed + (d.followed === 1 ? ' time.' : ' times.');
  if (d.diverged) s += ' The human picked a listed option ' + d.diverged + (d.diverged === 1 ? ' time.' : ' times.');
  if (d.free_text) s += ' The human answered in free text ' + d.free_text + (d.free_text === 1 ? ' time.' : ' times.');
  if (d.unparseable) s += ' ' + d.unparseable + (d.unparseable === 1 ? ' answer' : ' answers') + ' could not be classified.';
  if (d.rejected) s += ' ' + d.rejected + (d.rejected === 1 ? ' call' : ' calls') + ' refused as posed.';
  if (d.dismissed) s += ' ' + d.dismissed + (d.dismissed === 1 ? ' call' : ' calls') + ' dismissed.';
  if (d.errored) s += ' ' + d.errored + (d.errored === 1 ? ' call' : ' calls') + ' errored.';
  if (d.input_unparseable) s += ' ' + d.input_unparseable + (d.input_unparseable === 1 ? ' call' : ' calls') + ' could not be read.';
  return s;
}
function showPanel(t) {
  const panel = document.getElementById('panel');
  panel.innerHTML = '<h2>Turn ' + t.turn + '</h2>'
    + '<p class="big">' + D.kinds[t.kind] + '</p>'
    + '<p>Introduced ' + t.introduced.toLocaleString('en-US') + ' lines.</p>'
    + '<p>Removed ' + t.removed.toLocaleString('en-US') + ' lines from earlier turns.</p>'
    + '<p>Artifact after this turn: ' + t.lines_after.toLocaleString('en-US') + ' lines in ' + t.files_after + ' files.</p>'
    + '<p>' + decisionText(t.decisions) + '</p>';
}
function turnAt(mx, my) {
  if (!((my >= 40 && my <= AXIS_Y + 5) || (my >= ART_TOP - 10 && my <= ART_BOT + 10))) return null;
  let best = null, bestD = 16;
  D.turns.forEach(t => {
    const d = Math.abs(t.x - mx);
    if (d < bestD) { bestD = d; best = t; }
  });
  return best;
}
canvas.addEventListener('click', e => {
  const rect = canvas.getBoundingClientRect();
  const mx = (e.clientX - rect.left) * (W / rect.width);
  const my = (e.clientY - rect.top) * (H / rect.height);
  const t = turnAt(mx, my);
  if (t) { selected = t.turn; showPanel(t); draw(); }
});
draw();
"""
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{esc(title)}</title>\n<style>{css}</style></head><body>"
            + body +
            f"<script id=\"dual-data\" type=\"application/json\">{payload}</script>\n"
            f"<script>{js}</script>\n</body></html>")


def dual_timeline_main(argv):
    """CLI: steerprint --dual-timeline session.jsonl [--receipt receipt.json]
    -o dual-timeline.html. Both lanes come from the shipped prefix
    replays and the receipt's own decision parsing; the receipt, when
    given, supplies only the header label, mark, and post-first share."""
    args = list(argv)
    out_path = Path("dual-timeline.html")
    if "-o" in args:
        out_path = Path(args[args.index("-o") + 1])
    receipt_path = None
    if "--receipt" in args:
        receipt_path = args[args.index("--receipt") + 1]
    pos = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ("-o", "--receipt"):
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        pos.append(a)
    if len(pos) != 1:
        sys.exit("--dual-timeline takes exactly one session")
    data = dual_timeline_data(Path(pos[0]))
    title = "Dual timeline"
    subtitle = (f"{len(data['turns'])} human turns. "
                f"{data['final_lines']:,} lines in "
                f"{data['final_files']} files at the end.")
    if data["total_points"]:
        subtitle += (f" {data['total_points']} answered questions across "
                     f"{len(data['turns_with_decisions'])} turns.")
    else:
        subtitle += " The agent asked no questions."
    if receipt_path:
        r = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
        title = f"Dual timeline: {r.get('label', 'session')}"
        mark = (r.get("mark") or {}).get("category")
        pct = headline_pct(r.get("git_join") or {})
        extra = []
        if mark:
            extra.append(f"mark {mark}")
        if pct is not None:
            extra.append(f"{pct}% of lines arrived after the first prompt")
        if extra:
            subtitle += " " + ", ".join(extra) + "."
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dual_timeline_html(data, {"title": title,
                                                  "subtitle": subtitle}),
                        encoding="utf-8")
    print(f"wrote dual timeline {out_path} "
          f"({out_path.stat().st_size:,} bytes, "
          f"{len(data['turns'])} turns, "
          f"{data['total_points']} decision points)")


MAKING_W = 1000
MAKING_H = 520
MAKING_LANES = ["Yuriy", "Levko", "Subagent"]
MAKING_LANE_COLOURS = {"Yuriy": "#46689e", "Levko": "#2f8f83",
                        "Subagent": "#e07a3f"}
MAKING_CAPTION = ("This is a hand-built record of one chat, not a "
                  "computed receipt. Each step cites the message that "
                  "records it, and only steps found in the transcript "
                  "are shown. Nothing here was measured from a session.")
MAKING_ACTORS = ("Yuriy", "Levko", "Subagent")


def making_of_load(path):
    """Read a making-of JSON file: a list of steps, each with actor,
    action, time, and evidence. Finished steps carry an ISO time.
    The final open step carries no time and unfinished true."""
    steps = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(steps, list) or not steps:
        raise ValueError("making-of data must be a non-empty list")
    for s in steps:
        if s.get("actor") not in MAKING_ACTORS:
            raise ValueError("unknown actor: %r" % (s.get("actor"),))
        for key in ("action", "evidence"):
            if not s.get(key):
                raise ValueError("step missing %s: %r" % (key, s))
        if not s.get("unfinished") and not s.get("time"):
            raise ValueError("finished step missing time: %r" % (s,))
    return steps


def making_of_time_display(iso):
    """Nov 5, 11:06 AM from an ISO time with a fixed offset."""
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%b %-d, %-I:%M %p")


def making_of_data(steps):
    """Layout for the chain: one column per step, time left to right,
    one lane per actor. Handoffs run step to step in time order.
    The callout is computed from the step times, not written by
    hand: the build minutes and the wait for the push approval."""
    n = len(steps)
    span = MAKING_W - 250
    step_x = span / (n - 1) if n > 1 else 0
    lane_y = {a: 110 + 130 * i for i, a in enumerate(MAKING_LANES)}
    rows = []
    for i, s in enumerate(steps):
        rows.append({
            "index": i,
            "actor": s["actor"],
            "action": s["action"],
            "time": s.get("time"),
            "display": (making_of_time_display(s["time"])
                        if s.get("time") else "not yet"),
            "evidence": s["evidence"],
            "gate": bool(s.get("gate")),
            "unfinished": bool(s.get("unfinished")),
            "x": round(150 + i * step_x),
            "y": lane_y[s["actor"]],
            "colour": MAKING_LANE_COLOURS[s["actor"]],
        })
    timed = [r for r in rows if r["time"]]
    callout = ""
    if len(timed) >= 7:
        build = (datetime.fromisoformat(timed[4]["time"])
                 - datetime.fromisoformat(timed[3]["time"]))
        wait = (datetime.fromisoformat(timed[6]["time"])
                - datetime.fromisoformat(timed[5]["time"]))
        minutes = int(round(build.total_seconds() / 60))
        hours = int(wait.total_seconds() // 3600)
        if any(r["unfinished"] for r in rows):
            tail = "The demos link is still open."
        else:
            closed = datetime.fromisoformat(timed[-1]["time"])
            tail = ("The demos link closed on %s."
                    % closed.strftime("%B %-d"))
        callout = (f"The subagent built the figure in {minutes} minutes. "
                   f"The push approval came {hours} hours after "
                   f"verification. {tail}")
    return {"steps": rows, "callout": callout}


def making_of_html(data, meta):
    """Build the making-of page. All data is embedded as JSON. The
    page has no external assets, plays nothing on load, and is
    driven by click for detail."""
    title = meta.get("title", "Making of the dual timeline")
    subtitle = meta.get("subtitle", "")
    payload = json.dumps({"steps": data["steps"]})
    payload = payload.replace("<", "\\u003c")
    css = """
body{font-family:system-ui,-apple-system,sans-serif;color:#17222e;background:#f6f8fa;margin:0;padding:24px}
main{max-width:1000px;margin:0 auto;background:#fff;border:1px solid #dde4ea;border-radius:8px;padding:24px}
h1{font-size:22px;margin:0 0 4px} .sub{color:#5c6b7a;margin:0 0 16px}
.howto{font-size:15px;margin:0 0 12px}
.stage{display:flex;gap:20px;flex-wrap:wrap}
canvas{background:#fbfcfe;border:1px solid #dde4ea;border-radius:8px;cursor:pointer;flex:1;min-width:320px}
.panel{width:280px;flex:none;border:1px solid #dde4ea;border-radius:8px;padding:16px;height:fit-content}
.panel h2{font-size:17px;margin:0 0 8px}
.panel p{font-size:14px;line-height:1.6;margin:6px 0}
.panel .big{font-size:24px;font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:#5c6b7a;margin:14px 0}
.legend .shape{font-size:15px;margin-right:6px}
.callouts,.caption,.method{font-size:14px;line-height:1.5;color:#37424e}
.method{color:#5c6b7a}
"""
    legend = "".join(
        f"<span><span class=\"shape\" style=\"color:"
        f"{MAKING_LANE_COLOURS[a]}\">\u25cf</span>{a}</span>"
        for a in MAKING_LANES)
    legend += ("<span><span class=\"shape\" style=\"color:#17222e\">"
               "\u25c7</span>Approval gate (human)</span>")
    legend += ("<span><span class=\"shape\" style=\"color:#8a97a5\">"
               "\u25cb</span>Still open</span>")
    body = f"""<main>
<h1>{esc(title)}</h1>
<p class="sub">{esc(subtitle)}</p>
<p class="howto">How to read this: time runs left to right, one column per step, one lane per actor. A diamond is an approval gate. An open outline is a step that has not happened yet. Click any node for that step.</p>
<div class="stage">
<canvas id="making" width="{MAKING_W}" height="{MAKING_H}"></canvas>
<div class="panel" id="panel">
<h2>Pick a step</h2>
<p>Click any node to see what happened at that step, when it happened, and the message that records it.</p>
</div>
</div>
<div class="legend">{legend}</div>
<p class="callouts">{esc(data["callout"])}</p>
<p class="caption">{esc(MAKING_CAPTION)}</p>
</main>
"""
    js = """
const D = JSON.parse(document.getElementById('making-data').textContent);
const canvas = document.getElementById('making');
const ctx = canvas.getContext('2d');
const W = 1000, H = 520;
const LANE_Y = {Yuriy: 110, Levko: 240, Subagent: 370};
let selected = null;
function drawLanes() {
  ctx.font = '13px system-ui, sans-serif';
  Object.keys(LANE_Y).forEach(a => {
    const y = LANE_Y[a];
    ctx.fillStyle = '#5c6b7a';
    ctx.textAlign = 'left';
    ctx.fillText(a, 12, y + 5);
    ctx.strokeStyle = '#eef2f5';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(100, y);
    ctx.lineTo(W - 20, y);
    ctx.stroke();
  });
}
function drawArrow(x0, y0, x1, y1) {
  ctx.strokeStyle = '#8a97a5';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  const ang = Math.atan2(y1 - y0, x1 - x0);
  ctx.fillStyle = '#8a97a5';
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - 10 * Math.cos(ang - 0.4), y1 - 10 * Math.sin(ang - 0.4));
  ctx.lineTo(x1 - 10 * Math.cos(ang + 0.4), y1 - 10 * Math.sin(ang + 0.4));
  ctx.closePath();
  ctx.fill();
}
function drawNode(s) {
  ctx.beginPath();
  if (s.gate) {
    ctx.moveTo(s.x, s.y - 14);
    ctx.lineTo(s.x + 14, s.y);
    ctx.lineTo(s.x, s.y + 14);
    ctx.lineTo(s.x - 14, s.y);
    ctx.closePath();
    ctx.fillStyle = s.colour;
    ctx.fill();
  } else if (s.unfinished) {
    ctx.arc(s.x, s.y, 11, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.fill();
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = s.colour;
    ctx.stroke();
    ctx.setLineDash([]);
  } else {
    ctx.arc(s.x, s.y, 11, 0, Math.PI * 2);
    ctx.fillStyle = s.colour;
    ctx.fill();
  }
  if (selected === s.index) {
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = '#17222e';
    ctx.stroke();
  }
  ctx.fillStyle = '#17222e';
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'center';
  const labelW = ctx.measureText(s.display).width;
  ctx.fillStyle = '#fbfcfe';
  ctx.fillRect(s.x - labelW / 2 - 3, s.y + 18, labelW + 6, 16);
  ctx.fillStyle = '#17222e';
  ctx.fillText(s.display, s.x, s.y + 30);
}
function draw() {
  ctx.clearRect(0, 0, W, H);
  drawLanes();
  const steps = D.steps;
  for (let i = 1; i < steps.length; i++) {
    drawArrow(steps[i - 1].x, steps[i - 1].y, steps[i].x, steps[i].y);
  }
  steps.forEach(drawNode);
  ctx.fillStyle = '#5c6b7a';
  ctx.font = '13px system-ui, sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('Nov 5, 2026', 12, 490);
}
function showPanel(s) {
  const panel = document.getElementById('panel');
  const when = s.unfinished ? 'No time yet. This step is still open.'
    : s.display + ', Nov 5, 2026';
  const gate = s.gate ? '<p><b>Approval gate.</b> The human held this step.</p>' : '';
  panel.innerHTML = '<h2>' + s.action + '</h2>'
    + '<p class="big">' + s.actor + '</p>'
    + '<p>' + when + '</p>'
    + gate
    + '<p>' + s.evidence + '</p>';
}
canvas.addEventListener('click', function(e) {
  const r = canvas.getBoundingClientRect();
  const mx = (e.clientX - r.left) * (W / r.width);
  const my = (e.clientY - r.top) * (H / r.height);
  let best = null, bestD = 20;
  D.steps.forEach(s => {
    const d = Math.hypot(s.x - mx, s.y - my);
    if (d < bestD) { bestD = d; best = s; }
  });
  if (best) { selected = best.index; draw(); showPanel(best); }
});
draw();
"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{esc(title)}</title><style>{css}</style></head><body>
<script id="making-data" type="application/json">{payload}</script>
{body}
<script>{js}</script>
</body></html>
"""


def making_of_main(argv):
    """CLI: steerprint --making-of making-of-dual-timeline.json
    -o making-of-dual-timeline.html. The JSON is a hand-built list
    of steps from the chat transcript, not a computed receipt."""
    args = list(argv)
    out_path = Path("making-of-dual-timeline.html")
    if "-o" in args:
        out_path = Path(args[args.index("-o") + 1])
    pos = [a for a in args
           if not a.startswith("-") and a != str(out_path)]
    if len(pos) != 1:
        sys.exit("--making-of takes exactly one JSON data file")
    steps = making_of_load(Path(pos[0]))
    data = making_of_data(steps)
    finished = [s for s in steps if not s.get("unfinished")]
    title = "Making of the dual timeline"
    subtitle = (f"How the dual timeline was made. {len(steps)} steps "
                f"by one human and two AIs, Nov 5, 2026. "
                f"{len(finished)} done, "
                f"{len(steps) - len(finished)} still open.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(making_of_html(data, {"title": title,
                                              "subtitle": subtitle}),
                        encoding="utf-8")
    print(f"wrote making of {out_path} "
          f"({out_path.stat().st_size:,} bytes, "
          f"{len(steps)} steps)")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--making-of" in argv:
        making_of_main(argv)
        return
    if "--dual-timeline" in argv:
        dual_timeline_main(argv)
        return
    if "--rework" in argv:
        rework_main(argv)
        return
    if "--replay" in argv:
        replay_main(argv)
        return
    if "--shadow" in argv:
        shadow_main(argv)
        return
    args = [a for a in argv if not a.startswith("-")]
    out_path = Path("collaboration-map.html")
    if "-o" in argv:
        out_path = Path(argv[argv.index("-o") + 1])
        args = [a for a in args if a != str(out_path)]
    receipts = [json.loads(Path(a).read_text(encoding="utf-8")) for a in args]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if "--disclosure" in argv:
        if len(receipts) != 1:
            sys.exit("--disclosure takes exactly one receipt")
        if "-o" not in argv:
            out_path = Path("disclosure.md")
            out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = disclosure_md(receipts[0])
        except ValueError as e:
            sys.exit(str(e))
        out_path.write_text(text, encoding="utf-8")
        print(f"wrote disclosure {out_path} ({out_path.stat().st_size:,} bytes)")
    elif "--badge" in argv:
        if len(receipts) != 1:
            sys.exit("--badge takes exactly one receipt")
        out_path.write_text(badge_svg(receipts[0]), encoding="utf-8")
        print(f"wrote badge {out_path} ({out_path.stat().st_size:,} bytes)")
    else:
        out_path.write_text(build(receipts), encoding="utf-8")
        print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes) from {len(receipts)} receipts")

if __name__ == "__main__":
    main()
