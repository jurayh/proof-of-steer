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

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
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
