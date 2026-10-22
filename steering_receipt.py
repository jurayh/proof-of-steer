"""proof-of-steer v1 — steering receipt CLI. Stdlib only, local only.

Evolved from the spike prototype (../steering_join.py). Changes in v1:
  - Receipt schema frozen as proof-of-steering/receipt@1.0 (see SCHEMA.md).
  - Adapter hardening: `code --repo DIR` seeds the base content of files
    that an Edit targets but the session never Wrote, reading them from a
    real repo directory (suffix path match). Seeded lines carry origin
    segment -1 ("pre-existing") so they never inflate steering shares,
    and coverage splits applied edits into transcript-base vs seeded-base.
  - v1.1 (additive, schema stays receipt@1.0): top-level `harness` field
    ("claude-code" for code receipts, "git" for doc receipts) — survival
    and pushback-derived context fields are per-harness values and must
    not be pooled across harnesses (SWE-chat §7); and `code --repo-ref
    REF`, which seeds bases from `git show REF:<path>` instead of the
    working tree (session-time content rather than today's content).
    Coverage records the seed source.
  - v1.2 (additive, schema stays receipt@1.0): CoAuthor ground-truth
    results folded in — validation_scope records them; doc mode gains a
    sentence-granularity unchanged share and a revision_count field, and
    the doc headline is phrased as a floor ("at least X%"), per
    coauthor/VALIDATION-coauthor.md §5.
  - v1.3 (additive, schema stays receipt@1.0): Codex adapter — rollout
    JSONL (session_meta / turn_context / response_item / event_msg) is
    parsed into the same segment model as Claude Code sessions, so Codex
    receipts carry git-join fields with `harness: "codex"` (a new value
    of the existing field, not a new field). File ops come from
    apply_patch payloads (Add/Update/Delete/Move sections; hunks become
    the edit ops the join consumes); patches whose tool output reports
    failure are dropped whole (apply_patch is atomic) and counted in
    coverage. Shell-side writes via exec_command are extracted only when
    unambiguous (a lone heredoc `cat >` write, a bare `rm <path>`) and
    otherwise counted as unparsed in coverage — never guessed.
  - Survival and correction-segment share are demoted to context /
    supporting fields, per the spike verdict; every receipt carries a
    validation_scope field.

Miscounting guards (from the exploration, kept):
  - injected user-role records filtered (isMeta, <command-, <local-command,
    Caveat: prefixes)
  - assistant records deduped by message.id before token math
  - active time = wall clock with gaps > 300s capped at 300s
  - receipts carry counts and categories only, NEVER raw prompt text.

Usage:
  python3 steering_receipt.py code SESSION.jsonl --label L [--repo DIR [--repo-ref REF]] [--format auto|claude-code|codex] [--out DIR]
  python3 steering_receipt.py doc  REPO_DIR REL_MD_PATH --label L [--out DIR]
"""
import argparse, hashlib, json, re, subprocess, sys
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

SCHEMA = "proof-of-steering/receipt@1.0"
VALIDATION_SCOPE = (
    "Validated on trace-commons (28 sessions, full transcript-to-git join, "
    "blame agreement ~100%) and local repositories; at-scale validation on "
    "SWE-chat (SALT-NLP, 17,968 sessions) completed Oct 2026 with a partial "
    "pass: bimodality reproduced approximately (agent-all mode 40.9% vs "
    "published 41%), pushback reproduced on the dominant agent (49.2% vs "
    "~50% for Claude Code excluding first turns; pooled 39.6-40.7% and "
    "agent-mix-sensitive), survival not reproduced (metric-v2 aggregate "
    "53.4% vs published 59%; per-agent survival 25-97%, so survival stays a "
    "context field, stratified by agent where known). "
    "post_first_prompt_share is validated as a steering-presence detector "
    "(SWE-chat medians: 0.0 one-prompt, 0.75 continued no-pushback, 0.97 "
    "pushback sessions), not a steering-dose measure; at SWE-chat scale it "
    "was computed as the gross-added-lines analogue of this field's "
    "final-lines definition (see swe-chat/VALIDATION.md section 6). "
    "Document mode ground-truth-tested on CoAuthor (1,447 human-GPT-3 "
    "writing sessions, CHI 2022): per-part 'unchanged from first version' "
    "labels validated (sentence-level agreement 88.3%, false-untouched "
    "rate ~0.05%); the doc headline % unchanged is a floor on the "
    "untouched share, not a dose estimate (mean absolute error 13.0 pp "
    "against keystroke truth, sensitive to revision granularity). "
    "Document receipts contain no rejection evidence: material rejected "
    "or dismissed before it ever entered a revision is invisible to doc "
    "mode, so doc-mode steering evidence is a lower bound on interaction "
    "(see coauthor/VALIDATION-coauthor.md)."
)
PREEXISTING = -1  # origin segment index for lines seeded from --repo

TEST_RE = re.compile(r"(pytest|npm (run )?test|yarn test|pnpm test|cargo test|go test|jest|vitest|mocha|make test|\btox\b|rspec|phpunit|ctest|gradle\w* test|mvn test|unittest|node --test)", re.I)
CORRECTION_RE = re.compile(r"\b(no|don't|do not|wrong|fix|instead|actually|stop|revert|undo|still|again|broken|fails?|failed|error|not what|doesn't work|didn't work|remove|change|should be|shouldn't|never|avoid|missed|forgot)\b", re.I)
RUBBER_RE = re.compile(r"^\s*(ok|okay|yes|yeah|yep|sure|good|great|nice|perfect|continue|go ahead|proceed|lgtm|thanks|thank you|ship it|do it|next)[.! ]*$", re.I)
BROWSER_TOOLS = ("browser", "preview", "computer", "navigate", "screenshot")

def parse_ts(s):
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError: return None

def active_minutes(ts_list, cap_s=300):
    if len(ts_list) < 2: return 0.0
    ts = sorted(ts_list); total = 0.0
    for a, b in zip(ts, ts[1:]):
        total += min((b - a).total_seconds(), cap_s)
    return round(total / 60, 1)

def norm_path(p):
    p = p.replace("\\", "/")
    parts = [seg for seg in p.split("/") if seg and seg not in (".",)]
    if len(parts) > 1 and ":" in parts[0]:
        parts = parts[1:]
    return "/".join(parts[-4:]) if parts else "unnamed"

# ---------------------------------------------------------------- repo seeding
class SeedIndex:
    """Index of a real repo's text files for base-content seeding.

    Lookup matches by normalized path suffix: a transcript path matches a
    repo file when either is a suffix of the other (transcript paths are
    truncated to their last 4 components by norm_path, and carry the
    original machine's project prefix). Shortest repo path wins ties.

    Without a ref, content comes from the working tree. With `ref`
    (``--repo-ref``), the file list comes from ``git ls-tree`` at that ref
    and content from ``git show REF:<path>`` — the session-time content
    when the ref names the commit the session ran against, rather than
    whatever the working tree holds today.
    """
    def __init__(self, repo_dir, ref=None):
        self.repo = Path(repo_dir)
        self.ref = ref
        self.index = {}  # posix rel path -> Path (working tree) or None (ref mode)
        if ref:
            out = subprocess.run(["git", "-C", str(self.repo), "ls-tree", "-r",
                                  "--name-only", ref],
                                 capture_output=True, text=True)
            for rel in out.stdout.splitlines():
                if rel.strip():
                    self.index[rel.strip()] = None
        else:
            for p in sorted(self.repo.rglob("*")):
                if ".git" in p.parts or not p.is_file():
                    continue
                rel = p.relative_to(self.repo).as_posix()
                self.index[rel] = p

    @property
    def seed_source(self):
        return f"ref:{self.ref}" if self.ref else "working-tree"

    def lookup(self, fp):
        cands = [rel for rel in self.index
                 if rel == fp or rel.endswith("/" + fp) or fp.endswith("/" + rel)]
        if not cands:
            return None
        rel = min(cands, key=len)
        if self.ref:
            r = subprocess.run(["git", "-C", str(self.repo), "show", f"{self.ref}:{rel}"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            return r.stdout if r.returncode == 0 else None
        try:
            return self.index[rel].read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

# ---------------------------------------------------------------- session parsing
def parse_session(path):
    segments = []
    cur = None
    seen_msg_ids = set()
    tokens_in = tokens_out = 0
    injected = 0
    pending_error = False
    ts_all = []
    transcript_bytes = Path(path).read_bytes()
    for line in transcript_bytes.decode("utf-8", errors="replace").splitlines():
        try: r = json.loads(line)
        except json.JSONDecodeError: continue
        t = parse_ts(r.get("timestamp"))
        if t: ts_all.append(t)
        msg = r.get("message") or {}
        if r.get("type") == "user":
            content = msg.get("content")
            blocks = content if isinstance(content, list) else (
                [{"type": "text", "text": content}] if isinstance(content, str) else [])
            for blk in blocks:
                if isinstance(blk, dict) and blk.get("type") == "tool_result" and blk.get("is_error"):
                    pending_error = True
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(texts).strip()
            if joined:
                if r.get("isMeta") or joined.startswith(("<command-", "<local-command", "Caveat:")):
                    injected += 1
                else:
                    cur = {
                        "idx": len(segments), "prompt_chars": len(joined),
                        "correction_keyword": bool(CORRECTION_RE.search(joined)),
                        "rubber_stamp": bool(RUBBER_RE.match(joined)),
                        "after_error": pending_error,
                        "ops": [], "tools": Counter(), "test_bash": 0,
                        "browser_actions": 0, "shell_calls": 0, "errors_seen": 0,
                    }
                    segments.append(cur)
                    pending_error = False
        if r.get("type") == "assistant":
            mid = msg.get("id")
            if mid and mid in seen_msg_ids: continue
            if mid: seen_msg_ids.add(mid)
            u = msg.get("usage") or {}
            tokens_in += u.get("input_tokens", 0); tokens_out += u.get("output_tokens", 0)
            if cur is None:
                cur = {"idx": len(segments), "prompt_chars": 0, "correction_keyword": False,
                       "rubber_stamp": False, "after_error": False, "pre_prompt": True,
                       "ops": [], "tools": Counter(), "test_bash": 0,
                       "browser_actions": 0, "shell_calls": 0, "errors_seen": 0}
                segments.append(cur)
            for blk in (msg.get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    name = blk.get("name", "?"); inp = blk.get("input") or {}
                    cur["tools"][name] += 1
                    if name in ("Bash", "PowerShell"):
                        cur["shell_calls"] += 1
                        if TEST_RE.search(inp.get("command", "") or ""): cur["test_bash"] += 1
                    if any(k in name.lower() for k in BROWSER_TOOLS): cur["browser_actions"] += 1
                    if name == "Write":
                        cur["ops"].append(("write", norm_path(inp.get("file_path", "?")), inp.get("content", "")))
                    elif name == "Edit":
                        cur["ops"].append(("edit", norm_path(inp.get("file_path", "?")),
                                            (inp.get("old_string", ""), inp.get("new_string", ""))))
    return segments, {
        "injected_filtered": injected, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "active_min": active_minutes(ts_all),
        "wall_min": round((max(ts_all) - min(ts_all)).total_seconds() / 60, 1) if len(ts_all) > 1 else 0.0,
        "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
    }

# ---------------------------------------------------------------- Codex adapter
# Rollout JSONL records: session_meta, turn_context, response_item
# (message / function_call / function_call_output / custom_tool_call /
# custom_tool_call_output / reasoning) and event_msg (user_message,
# token_count, patch_apply_end, task_started, ...). Genuine human input
# arrives on TWO channels: event_msg user_message events (the canonical
# one) and response_item user-role messages, which DUPLICATE those events
# and additionally carry injected wrappers (<environment_context>,
# developer text). Segment boundaries therefore come from user_message
# events only; response_item user messages are ignored except that
# wrapper texts starting with "<" count as injected records filtered.
PATCH_SECTION_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$")
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$")
EXIT_CODE_RE = re.compile(r"Process exited with code (\d+)")
HEREDOC_WRITE_RE = re.compile(
    r"\s*cat\s+>\s*(\S+)\s+<<\s*['\"]?([A-Za-z0-9_.-]+)['\"]?\s*\n(.*)\n\2\s*", re.S)
HEREDOC_ANY_RE = re.compile(r"(?:\bcat\s*>>?|\btee\b)[^|;&]*<<")
SED_I_RE = re.compile(r"\bsed\s+(?:-\S+\s+)*-i")
ECHO_REDIR_RE = re.compile(r"\b(echo|printf)\b[^|;]*>>?\s*\S+")
FS_MUT_RE = re.compile(r"(?:^|&&|;|\|)\s*(rm|mv|cp|touch)\s")
GIT_MUT_RE = re.compile(r"\bgit\s+(add|commit|checkout|mv|rm|apply|stash|restore|clean)\b")
SCRIPT_RE = re.compile(r"(?:^|&&|;|\|)\s*(python3?|node|ruby|perl)\s")
REDIR_RE = re.compile(r"(?<![0-9&])>>?\s*(/[\w./-]*|\.[\w./-]*|~[\w./-]*|[A-Za-z_][\w./-]*)")
BARE_RM_RE = re.compile(r"^rm\s+(\S+)$")

def cx_path(raw, cwd):
    """Normalize a Codex patch/exec path: strip the session cwd prefix so
    the absolute (/workspace/src/x) and relative (src/x) spellings of one
    file — both common in patch payloads — map to the same join key."""
    p = (raw or "?").strip().replace("\\", "/")
    if cwd:
        c = cwd.replace("\\", "/").rstrip("/")
        if p.startswith(c + "/"): p = p[len(c) + 1:]
        elif p == c: p = p[len(c):].lstrip("/")
    return norm_path(p)

def parse_patch(text, cwd):
    """Parse an apply_patch payload into join ops + parse counters.

    Add File -> ("write", fp, content); each Update hunk -> ("edit", fp,
    (old_block, new_block)) with context lines in both blocks (they anchor
    the replace the join performs); Delete File -> ("delete", fp);
    Update + Move to -> ("move", fp, new_fp). A hunk with no old-side
    lines cannot anchor a replace and is counted unparsed, never guessed.
    """
    ops = []
    pc = Counter()
    lines = (text or "").splitlines()
    i, n = 0, len(lines)
    cur_file = None
    cur_kind = None
    add_lines = []

    def flush_add():
        if cur_kind == "add" and cur_file is not None:
            ops.append(("write", cx_path(cur_file, cwd), "\n".join(add_lines)))

    while i < n:
        ln = lines[i]
        m = PATCH_SECTION_RE.match(ln)
        if m or ln.startswith("*** End Patch"):
            flush_add(); add_lines = []; cur_kind = None; cur_file = None
            if m:
                cur_file = m.group(2).strip()
                kind = m.group(1).lower()
                cur_kind = kind
                pc[f"sections_{kind}"] += 1
                if kind == "delete":
                    ops.append(("delete", cx_path(cur_file, cwd)))
                    cur_kind = None
            i += 1
            continue
        if cur_kind == "add":
            if ln.startswith("+"):
                add_lines.append(ln[1:])
            elif not ln.startswith("\\"):
                pc["body_lines_unparsed"] += 1
            i += 1
            continue
        if cur_kind == "update":
            mm = PATCH_MOVE_RE.match(ln)
            if mm:
                ops.append(("move", cx_path(cur_file, cwd), cx_path(mm.group(1), cwd)))
                pc["sections_move"] += 1
                i += 1
                continue
            if ln.startswith("@@"):
                body = []
                i += 1
                while i < n and (lines[i][:1] in (" ", "+", "-") or lines[i].startswith("\\")):
                    body.append(lines[i]); i += 1
                old_block = [b[1:] for b in body if b[:1] in (" ", "-")]
                new_block = [b[1:] for b in body if b[:1] in (" ", "+")]
                if not old_block:
                    pc["hunks_unparsed"] += 1
                else:
                    pc["hunks_parsed"] += 1
                    if old_block != new_block:
                        ops.append(("edit", cx_path(cur_file, cwd),
                                    ("\n".join(old_block), "\n".join(new_block))))
                continue
            if ln.strip():
                pc["body_lines_unparsed"] += 1
            i += 1
            continue
        i += 1
    flush_add()
    return ops, pc

def classify_shell(cmd, base_dir):
    """Classify one exec_command cmd for file mutation.

    Returns ("op", op_tuple) when the mutation is unambiguous — the whole
    command is a lone heredoc `cat > path` write, or a bare `rm <path>` —
    "unparsed" when the command line itself shows a write/remove we
    cannot faithfully replay, and None when it shows no mutation.
    Interpreter invocations are opaque (their file effects live in the
    script body, not the transcript) and classify None unless an earlier
    pattern matched. Pattern priority mirrors the corpus census.
    """
    s = (cmd or "").strip()
    if not s:
        return None
    if "*** Begin Patch" in s:
        return "unparsed"
    m = HEREDOC_WRITE_RE.fullmatch(s)
    if m:
        raw = m.group(1)
        fp = raw if raw.startswith("/") else (f"{base_dir.rstrip('/')}/{raw}" if base_dir else raw)
        return ("op", ("write", cx_path(fp, base_dir), m.group(3)))
    if HEREDOC_ANY_RE.search(s):
        return "unparsed"
    if SED_I_RE.search(s):
        return "unparsed"
    if ECHO_REDIR_RE.search(s):
        return "unparsed"
    rm = BARE_RM_RE.match(s)
    if rm:
        raw = rm.group(1)
        fp = raw if raw.startswith("/") else (f"{base_dir.rstrip('/')}/{raw}" if base_dir else raw)
        return ("op", ("delete", cx_path(fp, base_dir)))
    if FS_MUT_RE.search(s):
        return "unparsed"
    if SCRIPT_RE.search(s):
        return None
    if GIT_MUT_RE.search(s):
        return "unparsed"
    redir = REDIR_RE.search(s)
    if redir and redir.group(1) != "/dev/null":
        return "unparsed"
    return None

def _output_text(o):
    if isinstance(o, str): return o
    if isinstance(o, list):
        return "\n".join((c.get("text") or "") for c in o if isinstance(c, dict))
    return ""

def parse_codex_session(path):
    """Codex rollout JSONL -> the same (segments, meta) the Claude Code
    adapter produces, plus meta['codex_coverage'] channel counters."""
    transcript_bytes = Path(path).read_bytes()
    records = []
    for line in transcript_bytes.decode("utf-8", errors="replace").splitlines():
        try: records.append(json.loads(line))
        except json.JSONDecodeError: continue
    # Pre-pass: session cwd, per-call patch outcomes, cumulative tokens.
    cwd = None
    outcomes = {}
    tokens_in = tokens_out = 0
    ts_all = []
    for r in records:
        t = parse_ts(r.get("timestamp"))
        if t: ts_all.append(t)
        p = r.get("payload") or {}
        if r.get("type") == "session_meta" and p.get("cwd"):
            cwd = p["cwd"]
        if p.get("type") == "custom_tool_call_output":
            outcomes[p.get("call_id")] = _output_text(p.get("output")).startswith("Exit code: 0")
    for r in records:  # patch_apply_end, when present, is authoritative
        p = r.get("payload") or {}
        if p.get("type") == "patch_apply_end":
            outcomes[p.get("call_id")] = bool(p.get("success"))
        if p.get("type") == "token_count":
            tot = ((p.get("info") or {}).get("total_token_usage") or {})
            if tot:
                tokens_in = tot.get("input_tokens", tokens_in)
                tokens_out = tot.get("output_tokens", tokens_out)
    cx = Counter()
    segments = []
    cur = None
    pending_error = False
    injected = 0

    def new_segment(prompt_text, pre=False):
        seg = {"idx": len(segments), "prompt_chars": len(prompt_text),
               "correction_keyword": bool(CORRECTION_RE.search(prompt_text)) if prompt_text else False,
               "rubber_stamp": bool(RUBBER_RE.match(prompt_text)) if prompt_text else False,
               "after_error": pending_error, "ops": [], "tools": Counter(),
               "test_bash": 0, "browser_actions": 0, "shell_calls": 0, "errors_seen": 0}
        if pre: seg["pre_prompt"] = True
        segments.append(seg)
        return seg

    def note_error():
        nonlocal pending_error
        pending_error = True
        if cur is not None: cur["errors_seen"] += 1

    for r in records:
        p = r.get("payload") or {}
        pt = p.get("type")
        if r.get("type") == "event_msg" and pt == "user_message":
            text = p.get("message") or ""
            if text.lstrip().startswith("<"):
                injected += 1
                continue
            cur = new_segment(text)
            pending_error = False
        elif r.get("type") == "response_item" and pt == "message" and p.get("role") == "user":
            txt = "".join((c.get("text") or c.get("input_text") or "") for c in p.get("content") or [])
            if txt.lstrip().startswith("<"):
                injected += 1
            # Genuine texts here duplicate the user_message events (the
            # segment starts above); wrappers are the injected count.
        elif r.get("type") == "response_item" and pt == "custom_tool_call" and p.get("name") == "apply_patch":
            if cur is None: cur = new_segment("", pre=True)
            cur["tools"]["apply_patch"] += 1
            cx["patch_calls"] += 1
            ops, pc = parse_patch(p.get("input") or "", cwd)
            sections = pc["sections_add"] + pc["sections_update"] + pc["sections_delete"]
            outcome = outcomes.get(p.get("call_id"))
            if outcome is False:
                # apply_patch is atomic: a failed call changed nothing.
                cx["patch_calls_failed"] += 1
                cx["patch_file_ops_failed"] += sections
            else:
                if outcome is None: cx["patch_calls_unresolved"] += 1
                cur["ops"].extend(ops)
                cx["patch_file_ops_parsed"] += sections
                cx["patch_hunks_parsed"] += pc["hunks_parsed"]
                cx["patch_hunks_unparsed"] += pc["hunks_unparsed"]
                cx["patch_body_lines_unparsed"] += pc["body_lines_unparsed"]
        elif r.get("type") == "response_item" and pt == "function_call":
            if cur is None: cur = new_segment("", pre=True)
            name = p.get("name", "?")
            cur["tools"][name] += 1
            if name == "exec_command":
                cur["shell_calls"] += 1
                try: args = json.loads(p.get("arguments") or "{}")
                except json.JSONDecodeError: args = {}
                cmd = args.get("cmd") or ""
                if TEST_RE.search(cmd): cur["test_bash"] += 1
                verdict = classify_shell(cmd, args.get("workdir") or cwd)
                if verdict == "unparsed": cx["shell_writes_unparsed"] += 1
                elif verdict: cur["ops"].append(verdict[1]); cx["shell_writes_extracted"] += 1
            elif name == "write_stdin":
                cur["shell_calls"] += 1
        elif pt == "function_call_output":
            m = EXIT_CODE_RE.search(_output_text(p.get("output")))
            if m and m.group(1) != "0": note_error()
        elif pt == "custom_tool_call_output":
            if not _output_text(p.get("output")).startswith("Exit code: 0"): note_error()
        elif pt == "patch_apply_end":
            if not p.get("success"): note_error()
    meta = {
        "injected_filtered": injected, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "active_min": active_minutes(ts_all),
        "wall_min": round((max(ts_all) - min(ts_all)).total_seconds() / 60, 1) if len(ts_all) > 1 else 0.0,
        "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
        "harness": "codex",
        "codex_coverage": {
            "patch_calls": cx["patch_calls"],
            "patch_calls_failed": cx["patch_calls_failed"],
            "patch_calls_unresolved": cx["patch_calls_unresolved"],
            "patch_file_ops_parsed": cx["patch_file_ops_parsed"],
            "patch_file_ops_failed": cx["patch_file_ops_failed"],
            "patch_hunks_parsed": cx["patch_hunks_parsed"],
            "patch_hunks_unparsed": cx["patch_hunks_unparsed"],
            "patch_body_lines_unparsed": cx["patch_body_lines_unparsed"],
            "shell_writes_extracted": cx["shell_writes_extracted"],
            "shell_writes_unparsed": cx["shell_writes_unparsed"],
        },
    }
    return segments, meta

def detect_format(path):
    """Sniff a transcript's harness from its first parseable records."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try: r = json.loads(line)
            except json.JSONDecodeError: continue
            if r.get("type") in ("session_meta", "turn_context", "event_msg", "response_item"):
                return "codex"
            if r.get("type") in ("user", "assistant"):
                return "claude-code"
    return "claude-code"

# ---------------------------------------------------------------- replay
def apply_ops(segments, seed_index=None):
    """Replay Write/Edit ops. Returns (files, stats, introduced, seeded_bases).

    files: path -> list[(line, origin_segment)]; origin PREEXISTING (-1) for
    lines that came from a --repo seed and were never agent-introduced.
    """
    files = {}
    stats = Counter()
    introduced = Counter()
    seeded_bases = {}   # fp -> original seeded lines (for the -1 snapshot)
    base_kind = {}      # fp -> "seeded" | "transcript"

    def provenance_merge(old, new_lines, seg_idx):
        old_texts = [l for l, _ in old]
        sm = SequenceMatcher(a=old_texts, b=new_lines, autojunk=False)
        out = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                out.extend(old[i1:i2])
            elif tag in ("replace", "insert"):
                for ln in new_lines[j1:j2]:
                    out.append((ln, seg_idx))
                    if ln.strip(): introduced[seg_idx] += 1
        return out

    def try_seed(fp):
        if seed_index is None or fp in files:
            return False
        content = seed_index.lookup(fp)
        if content is None:
            return False
        lines = content.splitlines()
        seeded_bases[fp] = lines
        files[fp] = [(l, PREEXISTING) for l in lines]
        base_kind[fp] = "seeded"
        stats["files_seeded"] += 1
        return True

    for seg in segments:
        for op in seg["ops"]:
            if op[0] == "write":
                _, fp, content = op
                lines = content.splitlines()
                old = files.get(fp, [])
                files[fp] = provenance_merge(old, lines, seg["idx"]) if old else [(l, seg["idx"]) for l in lines]
                if not old: introduced[seg["idx"]] += sum(1 for l in lines if l.strip())
                base_kind[fp] = "transcript"
                stats["writes"] += 1
            elif op[0] == "delete":
                # Codex apply_patch Delete File (the Claude Code adapter
                # never emits this — Claude Code has no delete tool).
                _, fp = op
                stats["deletes"] += 1
                if fp in files:
                    del files[fp]; base_kind.pop(fp, None)
                    stats["deletes_applied"] += 1
                else:
                    stats["deletes_unapplied"] += 1
            elif op[0] == "move":
                # Codex apply_patch Update + Move to: relocate the file,
                # keeping every line's origin segment.
                _, fp, new_fp = op
                stats["moves"] += 1
                if fp in files:
                    files[new_fp] = files.pop(fp)
                    base_kind[new_fp] = base_kind.pop(fp, "transcript")
                else:
                    stats["moves_unapplied"] += 1
            else:
                _, fp, (old_s, new_s) = op
                stats["edits"] += 1
                if fp not in files and not try_seed(fp):
                    stats["edits_unapplied_no_base"] += 1; continue
                cur_text = "\n".join(l for l, _ in files[fp])
                if old_s and old_s in cur_text:
                    new_text = cur_text.replace(old_s, new_s, 1)
                    files[fp] = provenance_merge(files[fp], new_text.splitlines(), seg["idx"])
                    stats["edits_applied_seeded" if base_kind.get(fp) == "seeded" else "edits_applied"] += 1
                else:
                    stats["edits_unapplied_no_match"] += 1
    return files, stats, introduced, seeded_bases

def build_git_repo(snapshots, out_repo):
    """One commit per snapshot (segment -1 = pre-existing seed base, if any).
    Returns (commit_of_segment, blame Counter over non-blank lines)."""
    repo = Path(out_repo)
    repo.mkdir(parents=True, exist_ok=True)
    def git(*args, **kw):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, **kw)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q", str(repo)], capture_output=True)
        git("config", "user.email", "v1@local"); git("config", "user.name", "Proof of Steering v1")
    commit_of_segment = {}
    for seg_idx, snapshot in snapshots:
        for p in repo.rglob("*"):
            if ".git" in p.parts: continue
            if p.is_file(): p.unlink()
        for fp, lines in snapshot.items():
            dest = repo / fp; dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        git("add", "-A")
        msg = "segment -1 (pre-existing, seeded from --repo)" if seg_idx == PREEXISTING else f"segment {seg_idx}"
        git("commit", "-q", "--allow-empty", "-m", msg)
        sha = git("rev-parse", "HEAD").stdout.strip()
        commit_of_segment[sha] = seg_idx
    blame = Counter()
    final_files = list(snapshots[-1][1].keys()) if snapshots else []
    for fp in final_files:
        r = git("blame", "--line-porcelain", "HEAD", "--", fp)
        cur_sha = None
        for line in r.stdout.splitlines():
            if re.match(r"^[0-9a-f]{40} ", line): cur_sha = line.split()[0]
            elif line.startswith("\t") and line[1:].strip():
                blame[commit_of_segment.get(cur_sha, -999)] += 1
    return commit_of_segment, blame

# ---------------------------------------------------------------- code receipt
def code_receipt(session_path, label, repo_dir=None, repo_ref=None, recon_dir=None, fmt="auto"):
    if fmt == "auto":
        fmt = detect_format(session_path)
    if fmt == "codex":
        segments, meta = parse_codex_session(session_path)
    else:
        segments, meta = parse_session(session_path)
        fmt = "claude-code"
    seed_index = SeedIndex(repo_dir, ref=repo_ref) if repo_dir else None
    files, stats, introduced, seeded_bases = apply_ops(segments, seed_index)
    # snapshots: optional -1 seed base, then one per segment (prefix replays)
    snapshots = []
    if seeded_bases:
        snapshots.append((PREEXISTING, {fp: list(lines) for fp, lines in seeded_bases.items()}))
    for i in range(len(segments)):
        f_i, _, _, _ = apply_ops(segments[: i + 1], seed_index)
        snapshots.append((segments[i]["idx"], {fp: [l for l, _ in v] for fp, v in f_i.items()}))
    if recon_dir is None:
        recon_dir = Path(__file__).parent / "reconstructed" / f"reconstructed-{label}"
    commit_map, blame = build_git_repo(snapshots, recon_dir) if snapshots else ({}, Counter())
    total_final = sum(1 for v in files.values() for l, _ in v if l.strip())
    origin_counts = Counter()
    for v in files.values():
        for _l, o in v:
            if _l.strip(): origin_counts[o] += 1
    blame_total = sum(blame.values())
    agree = sum(min(origin_counts[s], blame.get(s, 0)) for s in set(origin_counts) | set(blame))
    # first artifact-producing segment (seed snapshot excluded)
    fas_idx = segments[0]["idx"] if segments else 0
    first_lines = Counter()
    for s_idx, snap in snapshots:
        if s_idx == PREEXISTING: continue
        nb = sum(1 for lines in snap.values() for l in lines if l.strip())
        if nb > 0:
            fas_idx = s_idx
            for fp, lines in snap.items():
                for l in lines:
                    if l.strip(): first_lines[l] += 1
            break
    final_lines_counter = Counter()
    for v in files.values():
        for l, _ in v:
            if l.strip(): final_lines_counter[l] += 1
    first_surviving = sum(min(first_lines[l], final_lines_counter.get(l, 0)) for l in first_lines)
    first_total = sum(first_lines.values())
    corr_segs = {s["idx"] for s in segments if s["correction_keyword"] or s["after_error"]}
    per_segment = []
    if origin_counts.get(PREEXISTING):
        per_segment.append({
            "segment": PREEXISTING, "kind": "pre-existing (seeded from --repo)",
            "prompt_chars": 0, "correction_keyword": False, "after_error": False,
            "rubber_stamp": False, "edit_write_ops": 0, "lines_introduced_gross": 0,
            "lines_surviving_to_head": origin_counts[PREEXISTING],
        })
    for s in segments:
        per_segment.append({
            "segment": s["idx"], "prompt_chars": s["prompt_chars"],
            "correction_keyword": s["correction_keyword"], "after_error": s["after_error"],
            "rubber_stamp": s["rubber_stamp"], "edit_write_ops": len(s["ops"]),
            "lines_introduced_gross": introduced.get(s["idx"], 0),
            "lines_surviving_to_head": origin_counts.get(s["idx"], 0),
        })
    coverage = {
        "repo_supplied": bool(repo_dir),
        "seed_source": seed_index.seed_source if seed_index else None,
        "writes": stats["writes"],
        "edits_total": stats["edits"],
        "edits_applied_on_transcript_base": stats["edits_applied"],
        "edits_applied_on_repo_seeded_base": stats["edits_applied_seeded"],
        "edits_unapplied_no_base": stats["edits_unapplied_no_base"],
        "edits_unapplied_no_match": stats["edits_unapplied_no_match"],
        "files_seeded_from_repo": stats["files_seeded"],
    }
    coverage.update(meta.get("codex_coverage") or {})
    receipt = {
        "schema": SCHEMA,
        "label": label, "kind": "code",
        "harness": meta.get("harness", "claude-code"),
        "validation_scope": VALIDATION_SCOPE,
        "transcript_sha256": meta["transcript_sha256"],
        "mechanistic": {
            "human_turns": sum(1 for s in segments if not s.get("pre_prompt")),
            "injected_user_records_filtered": meta["injected_filtered"],
            "correction_keyword_prompts": sum(1 for s in segments if s["correction_keyword"]),
            "prompts_after_error": sum(1 for s in segments if s["after_error"]),
            "rubber_stamp_prompts": sum(1 for s in segments if s["rubber_stamp"]),
            "tokens_in_deduped": meta["tokens_in"], "tokens_out_deduped": meta["tokens_out"],
            "active_minutes_gapcap300": meta["active_min"], "wall_minutes": meta["wall_min"],
            "verification_lanes": {
                "test_like_shell": sum(s["test_bash"] for s in segments),
                "shell_total": sum(s["shell_calls"] for s in segments),
                "browser_lane_actions": sum(s["browser_actions"] for s in segments),
            },
            "edit_write_ops": stats["writes"] + stats["edits"] + stats["deletes"] + stats["moves"],
            "coverage": coverage,
        },
        "git_join": {
            "method": "reconstructed local git repo, one commit per human-turn segment (plus a pre-existing commit when --repo seeding occurred); git blame on HEAD cross-checked vs in-memory line provenance",
            "reconstructed_repo_local_path": str(recon_dir),
            "files_at_head": len(files), "final_nonblank_lines": total_final,
            "git_ai_style_line_authorship": "agent-typed vs pre-existing split is reported via per_segment origin -1; authorship alone carries no triage signal (spike finding)",
            "first_artifact_segment": fas_idx,
            "headline_fields": {
                "post_first_prompt_share_pct": round(100 * sum(c for s, c in origin_counts.items() if s > fas_idx) / total_final, 1) if total_final and segments else None,
                "preexisting_share_pct": round(100 * origin_counts.get(PREEXISTING, 0) / total_final, 1) if total_final else None,
            },
            "context_fields": {
                "first_segment_lines": first_total,
                "first_segment_lines_surviving_to_head": first_surviving,
                "first_segment_survival_pct": round(100 * first_surviving / first_total, 1) if first_total else None,
                "share_of_head_already_present_after_first_segment_pct": round(100 * first_surviving / total_final, 1) if total_final else None,
            },
            "supporting_fields": {
                "correction_segment_share_pct": round(100 * sum(origin_counts[s] for s in corr_segs) / total_final, 1) if total_final else None,
            },
            "blame_vs_memory_provenance_agreement_pct": round(100 * agree / blame_total, 1) if blame_total else None,
            "per_segment": per_segment,
            "per_file": [{"file": fp, "final_lines": sum(1 for l, _ in v if l.strip()),
                          "first_segment_share_pct": round(100 * sum(1 for l, o in v if l.strip() and segments and o == fas_idx) / max(1, sum(1 for l, _ in v if l.strip())), 1) if v else 0,
                          "preexisting_share_pct": round(100 * sum(1 for l, o in v if l.strip() and o == PREEXISTING) / max(1, sum(1 for l, _ in v if l.strip())), 1) if v else 0}
                         for fp, v in sorted(files.items(), key=lambda kv: -len(kv[1]))[:15]],
        },
        "labels": {"semantic_weights": "none — rule-based categories only; no model calls",
                   "receipt_nature": "descriptive evidence, not a certified grade",
                   "field_status": "headline_fields validated in spike; context_fields demoted (survival saturates on greenfield corpora); supporting_fields noisy, read jointly with turn count"},
    }
    return receipt

# ---------------------------------------------------------------- doc receipt (as-is from spike, schema 1.0)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

def split_sentences(text):
    """Split text into sentences for the prose-granularity unchanged share.

    Deterministic and deliberately simple: non-blank lines are split after
    terminal punctuation (. ! ?) followed by whitespace. Heading lines and
    fragments without terminal punctuation count as one sentence each.
    """
    sents = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        for s in SENTENCE_SPLIT_RE.split(line):
            s = s.strip()
            if s: sents.append(s)
    return sents

def doc_receipt(repo_dir, rel_path, label):
    repo = Path(repo_dir)
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout
    shas = git("log", "--follow", "--reverse", "--pretty=format:%H", "--", rel_path).split()
    versions = []
    for sha in shas:
        txt = git("show", f"{sha}:{rel_path}")
        versions.append((sha[:8], txt))
    if not versions:
        raise SystemExit(f"no git history for {rel_path} in {repo}")
    final = versions[-1][1]
    sections = []
    cur_title, cur_lines = "(preamble)", []
    for line in final.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            if cur_lines or cur_title != "(preamble)": sections.append((cur_title, cur_lines))
            cur_title, cur_lines = m.group(2).strip(), [line]
        else: cur_lines.append(line)
    sections.append((cur_title, cur_lines))
    first_lines = Counter(l for l in versions[0][1].splitlines() if l.strip())
    out_sections = []
    for title, lines in sections:
        nb = [l for l in lines if l.strip()]
        if not nb: continue
        survived = sum(1 for l in nb if first_lines.get(l, 0) > 0)
        intro_rev = Counter()
        for l in set(nb):
            for vi, (_, vtxt) in enumerate(versions):
                if l in vtxt.splitlines(): intro_rev[vi] += 1; break
        out_sections.append({
            "section": title, "final_lines": len(nb),
            "pct_unchanged_from_first_version": round(100 * survived / len(nb), 1),
            "pct_introduced_after_first_version": round(100 * (len(nb) - survived) / len(nb), 1),
            "introduced_by_revision": {f"rev{i+1} ({versions[i][0]})": c for i, c in sorted(intro_rev.items())},
        })
    total_nb = sum(s["final_lines"] for s in out_sections)
    survived_total = sum(round(s["final_lines"] * s["pct_unchanged_from_first_version"] / 100) for s in out_sections)
    first_sentences = set(split_sentences(versions[0][1]))
    final_sentences = split_sentences(final)
    unchanged_sentence_share = (round(100 * sum(1 for s in final_sentences if s in first_sentences) / len(final_sentences), 1)
                                if final_sentences else None)
    return {
        "schema": SCHEMA, "label": label, "kind": "document",
        "harness": "git",
        "validation_scope": VALIDATION_SCOPE,
        "source": f"{repo} :: {rel_path}", "revisions": len(versions),
        "revision_count": len(versions),
        "revision_shas": [s for s, _ in versions],
        "final_nonblank_lines": total_nb,
        "overall_pct_unchanged_from_first_version": round(100 * survived_total / total_nb, 1) if total_nb else None,
        "unchanged_sentence_share_pct": unchanged_sentence_share,
        "per_section": out_sections,
        "labels": {"method": "git log --follow versions; exact-line provenance per section (conservative: any edit marks the line rewritten)",
                   "receipt_nature": "descriptive evidence, not a certified grade"},
    }

# ---------------------------------------------------------------- rendering
def render_md(r):
    lines = [f"# STEERING.md — {r['label']} ({r['kind']})", "",
             f"_Schema {r['schema']}. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._",
             f"_Harness: {r.get('harness')}._",
             f"_Validation scope: {r['validation_scope']}_", ""]
    if r["kind"] == "code":
        m, g = r["mechanistic"], r["git_join"]
        c = m["coverage"]
        lines += [f"- Human turns: **{m['human_turns']}** (correction-keyword: {m['correction_keyword_prompts']}, after-error: {m['prompts_after_error']}, rubber-stamp: {m['rubber_stamp_prompts']})",
                  f"- Injected user records filtered: {m['injected_user_records_filtered']}",
                  f"- Active time: {m['active_minutes_gapcap300']} min (wall {m['wall_minutes']} min)",
                  f"- Tokens (deduped by message id): in {m['tokens_in_deduped']}, out {m['tokens_out_deduped']}",
                  f"- Verification lanes: test-like shell {m['verification_lanes']['test_like_shell']}, shell total {m['verification_lanes']['shell_total']}, browser-lane {m['verification_lanes']['browser_lane_actions']}",
                  f"- Coverage: {c['writes']} writes, {c['edits_total']} edits — applied on transcript base {c['edits_applied_on_transcript_base']}, applied on repo-seeded base {c['edits_applied_on_repo_seeded_base']} ({c['files_seeded_from_repo']} files seeded" + (f", seed source: {c['seed_source']}" if c.get('seed_source') else "") + f"), unapplied no-base {c['edits_unapplied_no_base']}, unapplied no-match {c['edits_unapplied_no_match']}. A low-coverage receipt should be discounted by its reader.",
                  "", "## Git join (the part authorship cannot tell you)", "",
                  f"- Final artifact: {g['files_at_head']} files, {g['final_nonblank_lines']} non-blank lines",
                  f"- First artifact-producing segment: segment {g['first_artifact_segment']}",
                  f"- Share of HEAD introduced after that segment (headline): **{g['headline_fields']['post_first_prompt_share_pct']}%**",
                  f"- Share of HEAD that is pre-existing (seeded from repo): {g['headline_fields']['preexisting_share_pct']}%",
                  f"- First-segment survival into HEAD (context; saturates on greenfield corpora): {g['context_fields']['first_segment_survival_pct']}%",
                  f"- Share of HEAD from correction / after-error segments (supporting; noisy, read with turn count): {g['supporting_fields']['correction_segment_share_pct']}%",
                  f"- Blame vs in-memory provenance agreement: {g['blame_vs_memory_provenance_agreement_pct']}%",
                  "", "## Per-segment attribution", "",
                  "| segment | prompt chars | correction? | after error? | ops | lines introduced | lines surviving to HEAD |",
                  "|---|---|---|---|---|---|---|"]
        if "patch_calls" in c:
            lines.insert(len(lines) - 15, f"- Codex channels: {c['patch_calls']} apply_patch calls ({c['patch_calls_failed']} failed and dropped whole, {c['patch_calls_unresolved']} unresolved), {c['patch_file_ops_parsed']} patch file ops in the join ({c['patch_hunks_parsed']} hunks parsed, {c['patch_hunks_unparsed']} hunks unparsed, {c['patch_file_ops_failed']} file ops inside failed patches), shell writes extracted {c['shell_writes_extracted']}, shell writes unparsed {c['shell_writes_unparsed']} (counted, never guessed into the join).")
        for s in g["per_segment"]:
            seg = "pre-existing" if s["segment"] == PREEXISTING else str(s["segment"])
            lines.append(f"| {seg} | {s['prompt_chars']} | {'yes' if s['correction_keyword'] else '—'} | {'yes' if s['after_error'] else '—'} | {s['edit_write_ops']} | {s['lines_introduced_gross']} | {s['lines_surviving_to_head']} |")
    else:
        rev_count = r.get("revision_count", r["revisions"])
        lines += [f"- Revisions in git history: {r['revisions']} ({', '.join(r['revision_shas'])})",
                  f"- Final size: {r['final_nonblank_lines']} non-blank lines",
                  f"- Unchanged from first committed version: **at least {r['overall_pct_unchanged_from_first_version']}%** of the final text survives verbatim from the first version (a floor, computed over {rev_count} revisions: the exact-line rule only ever marks a line rewritten, so finer revision granularity only lowers this number)"]
        if r.get("unchanged_sentence_share_pct") is not None:
            lines.append(f"- Sentence-level unchanged share (the less granularity-sensitive prose measure): **{r['unchanged_sentence_share_pct']}%** of final sentences appear verbatim in the first version")
        lines += ["", "## Per-section steering map", "",
                  "| section | final lines | % unchanged from v1 | % introduced after v1 | introduced by revision |",
                  "|---|---|---|---|---|"]
        for s in r["per_section"]:
            intro = ", ".join(f"{k}: {v}" for k, v in s["introduced_by_revision"].items())
            lines.append(f"| {s['section']} | {s['final_lines']} | {s['pct_unchanged_from_first_version']} | {s['pct_introduced_after_first_version']} | {intro} |")
    lines.append("")
    return "\n".join(lines)

# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="steering_receipt",
                                 description="proof-of-steer v1 — emit a steering receipt (JSON + STEERING.md) from a coding-agent transcript or a git-carried document. Local only; receipts never contain prompt text.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("code", help="receipt from a coding-agent session JSONL (Claude Code or Codex rollout)")
    pc.add_argument("session", help="path to the session .jsonl transcript")
    pc.add_argument("--format", choices=["auto", "claude-code", "codex"], default="auto",
                    help="transcript format (default: auto-detect from the first records)")
    pc.add_argument("--label", required=True, help="receipt label (file names + receipt label field)")
    pc.add_argument("--repo", default=None, help="real repo directory: seed base content for files the session Edits but never Wrote")
    pc.add_argument("--repo-ref", default=None, help="seed bases from this git ref in --repo (git show REF:<path>) instead of the working tree; use the commit the session ran against for session-time content")
    pc.add_argument("--out", default="receipts-out", help="output directory for <label>.receipt.json and <label>.STEERING.md (default: receipts-out)")
    pc.add_argument("--recon-dir", default=None, help="where to materialise the reconstructed git repo (default: <out>/reconstructed-<label>)")
    pd = sub.add_parser("doc", help="receipt from a markdown document's git history")
    pd.add_argument("repo", help="git repo directory containing the document")
    pd.add_argument("path", help="document path relative to the repo root")
    pd.add_argument("--label", required=True, help="receipt label (file names + receipt label field)")
    pd.add_argument("--out", default="receipts-out", help="output directory (default: receipts-out)")
    args = ap.parse_args(argv)
    if args.cmd == "code" and args.repo_ref and not args.repo:
        ap.error("--repo-ref requires --repo")

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    if args.cmd == "code":
        recon = Path(args.recon_dir) if args.recon_dir else out_dir / f"reconstructed-{args.label}"
        r = code_receipt(args.session, args.label, repo_dir=args.repo,
                         repo_ref=args.repo_ref, recon_dir=recon, fmt=args.format)
    else:
        r = doc_receipt(args.repo, args.path, args.label)
    (out_dir / f"{args.label}.receipt.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    (out_dir / f"{args.label}.STEERING.md").write_text(render_md(r), encoding="utf-8")
    summary = {"label": r["label"], "kind": r["kind"], "schema": r["schema"],
               "receipt_json": str(out_dir / f"{args.label}.receipt.json"),
               "steering_md": str(out_dir / f"{args.label}.STEERING.md")}
    if r["kind"] == "code":
        summary.update({"human_turns": r["mechanistic"]["human_turns"],
                        "coverage": r["mechanistic"]["coverage"],
                        "post_first_prompt_share_pct": r["git_join"]["headline_fields"]["post_first_prompt_share_pct"],
                        "agreement_pct": r["git_join"]["blame_vs_memory_provenance_agreement_pct"]})
    else:
        summary.update({"revisions": r["revisions"],
                        "revision_count": r.get("revision_count"),
                        "overall_unchanged_pct": r["overall_pct_unchanged_from_first_version"],
                        "unchanged_sentence_share_pct": r.get("unchanged_sentence_share_pct"),
                        "sections": len(r["per_section"])})
    print(json.dumps(summary, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
