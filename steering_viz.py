#!/usr/bin/env python3
"""proof-of-steer — Steerprint generator. Stdlib only.

Reads one or more receipt JSON files (spike format: code receipts carry
git_join.per_segment + per_file; doc receipts carry per_section with
introduced_by_revision) and emits ONE self-contained HTML page:
inline CSS/JS, zero external assets, no network.

Usage:
  python3 steering_viz.py receipt.json [more.json ...] -o out.html

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
    <b>{g['post_first_prompt_share_pct']}%</b> of shipped lines arrived after the first prompt ·
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

def build(receipts, title="Steerprint — proof-of-steer"):
    codes = [r for r in receipts if r["kind"] == "code"]
    docs = [r for r in receipts if r["kind"] == "document"]
    codes.sort(key=lambda r: -r["mechanistic"]["human_turns"])
    out = [f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Steerprint</h1>
<p class="sub">Which parts of an artifact the human actually shaped, and how. Generated by proof-of-steer from steering receipts.</p>
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
    out.append(f"""<footer>Computed locally by proof-of-steer from steering receipts ({esc(schemas)}).
Counts and categories only — no prompt text is ever included. Line provenance cross-checked against git blame.
Descriptive evidence, not a certified grade.</footer>
</div><div id="tip"></div><script>{JS}</script></body></html>""")
    return "".join(out)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    out_path = Path("collaboration-map.html")
    if "-o" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("-o") + 1])
        args = [a for a in args if a != str(out_path)]
    receipts = [json.loads(Path(a).read_text(encoding="utf-8")) for a in args]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build(receipts), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes) from {len(receipts)} receipts")
