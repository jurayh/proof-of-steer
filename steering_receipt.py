"""Proof of Steering v1 — steering receipt CLI. Stdlib only, local only.

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
  - v1.4 (additive, schema stays receipt@1.0): the adoption build.
    Doc mode is restructured onto a history-provider package
    (providers/: git, gdrive-doc, folder) behind a registry, so doc
    receipts gain `provider`, `history_complete`, and `authors` fields
    and the doc subcommand gains `--provider`; the join lives in
    doc_join.py and gains heading-less sectioning strategies for
    plain-text exports (markdown / heuristic / whole). Code receipts
    gain effect-based impact fields ported from the impact spike
    (procedural / continuation / reshaping / unmeasured segment classes
    computed from line provenance, never prompt text). Both kinds gain
    a `mark` field (the steering mark: a category word naming the
    process shape, never a grade). `--commitment` on both subcommands
    emits the hash-commitment block specified in
    ../specs/hash-commitment.md.
  - Demo subcommand (additive, schema stays receipt@1.0): `demo` runs
    the same code_receipt pipeline on a small synthetic session
    bundled in demo.py and additionally renders the badge and the
    Steerprint map, so a first-time user sees every output form in
    one run. The sample is synthetic and the demo says so in its own
    output; its hand-computed receipt is asserted in tests.
  - Decisions adoption (additive, schema stays receipt@1.0): code
    receipts gain a top-level `decisions` block counting the
    structured questions the agent asked and the user answered
    (AskUserQuestion events, ported from the decision-points spike):
    how often the user followed the option the agent marked
    recommended, chose a different listed option, answered in free
    text, or refused the question as posed, with errored, dismissed,
    input-unparseable, and unparseable coverage counted alongside.
    Decision events never create segments and do not feed the
    steering mark in this build. Codex receipts carry the block as
    zeros: decision events are an interactive Claude Code phenomenon.
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
  python3 steering_receipt.py demo [--out DIR]
"""
import argparse, hashlib, itertools, json, os, re, shutil, subprocess, sys
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
IMPACT_SCOPE = (
    " Impact classification (v1.4, from the Oct 2026 impact spike): "
    "segments are also classified by measured effect on the artifact "
    "(procedural, continuation, reshaping, unmeasured) from line "
    "provenance alone. Reshaping share separated steered sessions from "
    "near-one-prompt controls at AUC 0.929, against 0.602 for the "
    "keyword correction segment share and 0.616 for the keyword line "
    "share; every control session measured exactly 0 reshaping "
    "segments. In interactive Claude Code sessions 52.8% of human "
    "turns are procedural (no file effect), so raw turn counts "
    "overstate steering roughly twofold. Scope caveat: reshaping "
    "detects inter-segment rework, and reads as human steering only "
    "when the segments are genuine human turns; in the headless Codex "
    "batch the follow-up prompts were a pre-written escalation ladder "
    "fired on schedule, and reshaping there (median share 66.7%) "
    "measures the scripted schedule and agent self-repair, not a "
    "human steering."
)
CODE_VALIDATION_SCOPE = VALIDATION_SCOPE + IMPACT_SCOPE
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
    decision_calls = {}    # tool_use_id -> input, for AskUserQuestion calls
    decision_results = {}  # tool_use_id -> (result_text, is_error)
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
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    if blk.get("is_error"):
                        pending_error = True
                    decision_results[blk.get("tool_use_id")] = (
                        _decision_result_text(blk.get("content")),
                        bool(blk.get("is_error")))
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
                        "first_ts": r.get("timestamp"),
                        "ops": [], "tools": Counter(), "test_bash": 0,
                        "browser_actions": 0, "shell_calls": 0, "errors_seen": 0,
                    }
                    segments.append(cur)
                    pending_error = False
        if r.get("type") == "assistant":
            # Decision-event collection deliberately sits outside the
            # message.id dedupe below: transcripts that emit one record
            # per content block under a shared message id would
            # otherwise lose every AskUserQuestion block after the
            # first. Pairing is by tool_use id, as in the spike's
            # walker, so a re-emitted call still counts once.
            for blk in (msg.get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use" \
                        and blk.get("name") == "AskUserQuestion":
                    decision_calls[blk.get("id")] = blk.get("input") or {}
            mid = msg.get("id")
            if mid and mid in seen_msg_ids: continue
            if mid: seen_msg_ids.add(mid)
            u = msg.get("usage") or {}
            tokens_in += u.get("input_tokens", 0); tokens_out += u.get("output_tokens", 0)
            if cur is None:
                cur = {"idx": len(segments), "prompt_chars": 0, "correction_keyword": False,
                       "rubber_stamp": False, "after_error": False, "pre_prompt": True,
                       "first_ts": r.get("timestamp"),
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
    decision_events = []
    for call_id, call_input in decision_calls.items():
        res = decision_results.get(call_id)
        decision_events.append((call_input,
                                res[0] if res else None,
                                res[1] if res else False))
    return segments, {
        "injected_filtered": injected, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "active_min": active_minutes(ts_all),
        "wall_min": round((max(ts_all) - min(ts_all)).total_seconds() / 60, 1) if len(ts_all) > 1 else 0.0,
        "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
        "earliest_ts": min(ts_all).isoformat() if ts_all else None,
        "decision_events": decision_events,
    }

# ---------------------------------------------------------------- decision events
# Structured questions the agent asked and the user answered (Claude
# Code AskUserQuestion calls), ported from the decision-points spike
# (../decision-spike/extract.py). The spike classified 10,763 answered
# questions pooled across trace-commons and SWE-chat with 3.08%
# unparseable, hand-checked all 24 trace-commons questions against
# the raw records, and returned an ADOPT verdict. The port below is
# deliberately literal so the shipped numbers stay the spike's
# numbers; the corpus regression in the test suite pins that.
DECISION_REC_MARK = "(recommended)"
DECISIONS_SCOPE_CC = (
    "Decision fields count the structured questions the agent asked "
    "and the user answered. Followed and diverged are defined only "
    "where the agent marked a recommended option, and "
    "decisions_with_recommendation is their denominator: agents mark "
    "inconsistently (4% of questions in one validated corpus, 40% in "
    "another). A listed pick on an unmarked question counts as "
    "diverged_to_listed and means only that the user chose among the "
    "offered options. Free-text answers mean the user left the "
    "offered options entirely. Sessions where the agent never asks "
    "have zero decision points, which says nothing about steering "
    "through ordinary turns.")
DECISIONS_SCOPE_CODEX = (
    "Decision fields count the structured questions the agent asked "
    "and the user answered. Events of this kind are an interactive "
    "Claude Code phenomenon: the validated Codex rollouts are "
    "unattended runs and contain none (a full pattern scan of the "
    "rollout batch found zero), so this block reads zero rather than "
    "being omitted, and zero says nothing about steering through "
    "the rollout's turns.")

def decisions_scope_label(harness, meta):
    if harness == "codex":
        return DECISIONS_SCOPE_CODEX
    return DECISIONS_SCOPE_CC

def _decision_result_text(content):
    """Normalize a tool_result content (str or block list) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts)
    return ""

def _decision_norm(s):
    return " ".join((s or "").split())

def _split_decision_answers(text, questions):
    """Slice the serialized "Q"="A", ... result into per-question
    answers. Returns (answers, failure): answers is a list aligned
    with questions (entries may be None) and failure is None or a
    reason. Anchors are the exact question texts from the tool_use
    input, so answers are sliced between their own question anchor
    and a verified terminator: the next pair's anchor, the ". You
    can now continue" suffix, end of string, or the
    ' selected preview:' / ' user notes:' markers (a chosen option's
    preview, or the user's annotation, is recorded between the
    answer and the next pair; the answer is still just the label
    before the marker). Internal quotes inside an answer (pasted
    logs, code) satisfy none of the terminator tests and are
    skipped."""
    def anchor(i):
        return '"' + (questions[i].get("question") or "") + '"='

    answers = [None] * len(questions)
    cursor = 0
    for i in range(len(questions)):
        j = text.find(anchor(i), cursor)
        if j < 0:
            continue
        astart = j + len(anchor(i))
        if astart >= len(text) or text[astart] != '"':
            continue
        astart += 1
        p = astart
        while True:
            p = text.find('"', p)
            if p < 0:
                break
            after = text[p + 1:p + 24]
            if after.startswith(" selected preview:") or after.startswith(" user notes:"):
                answers[i] = text[astart:p]
                # skip the preview / note: resume at the next anchor or the suffix
                nxt = text.find(anchor(i + 1), p) if i + 1 < len(questions) else -1
                sfx = text.find("You can now continue", p)
                cursor = nxt if nxt >= 0 else (sfx if sfx >= 0 else len(text))
                break
            if after.startswith(", ") and (i + 1 >= len(questions)
                                            or text.startswith(anchor(i + 1), p + 3)):
                answers[i] = text[astart:p]
                cursor = p + 3
                break
            if after.startswith(". You can now continue") or after.startswith(" You can now continue"):
                answers[i] = text[astart:p]
                cursor = len(text)
                break
            if p + 1 >= len(text) or not text[p + 1:].strip():
                answers[i] = text[astart:p]
                cursor = len(text)
                break
            p += 1  # internal quote: not a terminator, keep scanning
        if answers[i] is None:
            # no terminator found; leave None (counted unparseable)
            cursor = astart
    if all(a is None for a in answers):
        return None, "no_anchors_found"
    return answers, None

def _segment_decision_multi(chosen, labels):
    """If `chosen` is exactly several listed labels joined by ', ',
    return them as a list; else None."""
    if not chosen or len(labels) < 2 or len(labels) > 8:
        return None
    pieces = chosen.split(", ")
    if len(pieces) >= 2 and all(p in labels for p in pieces):
        return pieces
    for r in range(2, len(labels) + 1):
        for combo in itertools.combinations(labels, r):
            if ", ".join(combo) == chosen:
                return list(combo)
    return None

def _classify_decision_question(chosen, question):
    """Classify one answered question. Returns (cls, detail)."""
    options = question.get("options") or []
    labels = [o.get("label", "") for o in options if isinstance(o, dict)]
    rec_label = next((l for l in labels if DECISION_REC_MARK in l.lower()), None)
    detail = {"labels": labels, "rec_label": rec_label,
              "multi_select": bool(question.get("multiSelect"))}
    if chosen is None:
        return "unparseable", {**detail, "reason": "no_answer_sliced"}
    if not chosen.strip():
        return "unparseable", {**detail, "reason": "empty_answer"}
    # exact listed match
    if chosen in labels:
        detail["match"] = "exact"
        return ("followed_recommendation" if chosen == rec_label else "diverged_to_listed"), detail
    # whitespace-normalized listed match
    nchosen = _decision_norm(chosen)
    for l in labels:
        if nchosen == _decision_norm(l):
            detail["match"] = "whitespace_normalized"
            return ("followed_recommendation" if l == rec_label else "diverged_to_listed"), detail
    # multi-select pick of listed labels
    if detail["multi_select"]:
        pieces = _segment_decision_multi(chosen, labels)
        if pieces is not None:
            detail.update({"match": "multi_pick", "picks": pieces})
            return "diverged_to_listed", detail
        return "unparseable", {**detail, "reason": "multi_select_unsplittable"}
    return "free_text", detail

def _normalize_decision_questions(call_input):
    """Return (questions, note). questions is None when the recorded
    input cannot yield a question list (missing, double-encoded beyond
    repair, or not a list at all). Some harnesses store `questions` as
    a JSON string holding the array; that is decoded transparently."""
    if not isinstance(call_input, dict):
        return None, "input_not_a_dict"
    questions = call_input.get("questions")
    note = None
    if isinstance(questions, str):
        try:
            questions = json.loads(questions)
            note = "input_double_encoded"
        except Exception:
            return None, "questions_string_undecodable"
    if questions is None:
        return None, "questions_missing"
    if not isinstance(questions, list):
        return None, "questions_not_a_list"
    fixed = []
    for q in questions:
        if isinstance(q, dict):
            fixed.append(q)
        else:
            fixed.append({"question": str(q), "options": []})
    return fixed, note

def _classify_decision_call(call_input, result, is_error):
    """Classify all questions of one AskUserQuestion call.

    result: result text or None if no result record exists.
    Errored calls return early: their questions are errored, never
    answered. Calls whose recorded input cannot be normalized are
    input_unparseable: counted separately, never answered. Rejected
    calls (the question reached the user and they refused it as
    posed) and dismissed calls likewise produce no answered
    questions."""
    questions, note = _normalize_decision_questions(call_input)
    if questions is None:
        return {"n_questions": 0, "questions": [], "status": "input_unparseable",
                "reason": note}
    out = {"n_questions": len(questions), "questions": []}
    if note:
        out["input_note"] = note
    if is_error:
        out["status"] = "errored"
        return out
    if result is None:
        out["status"] = "answered"
        for q in questions:
            out["questions"].append({"class": "unparseable", "reason": "missing_result",
                                     "chosen": None, "header": q.get("header")})
        return out
    if result.lstrip().startswith("[user dismissed"):
        out["status"] = "dismissed"
        return out
    if result.lstrip().startswith(("The user doesn't want to proceed",
                                   "The user does not want to proceed")):
        # the question reached the user and they refused it as posed
        # (sometimes asking to clarify instead): no choice was made
        out["status"] = "rejected"
        return out
    answers, failure = _split_decision_answers(result, questions)
    if answers is None:
        # no anchors at all: maybe an unserialized reply
        if len(questions) == 1 and result.strip():
            if len(result) > 2000:
                out["status"] = "answered"
                out["questions"].append({"class": "unparseable",
                                         "reason": "unserialized_result_implausible_length",
                                         "chosen": None, "header": questions[0].get("header")})
                return out
            cls, det = _classify_decision_question(result.strip(), questions[0])
            det = {**det, "unserialized_single": True}
            out["status"] = "answered"
            out["questions"].append({"class": cls, "chosen": result.strip(),
                                     "header": questions[0].get("header"), **det})
            return out
        out["status"] = "answered"
        reason = "result_not_serialized" if len(questions) > 1 else (failure or "no_anchors_found")
        for q in questions:
            out["questions"].append({"class": "unparseable", "reason": reason,
                                     "chosen": None, "header": q.get("header")})
        return out
    out["status"] = "answered"
    for i, q in enumerate(questions):
        if answers[i] is None:
            out["questions"].append({"class": "unparseable",
                                     "reason": f"question_not_in_result:{i}",
                                     "chosen": None, "header": q.get("header")})
            continue
        cls, det = _classify_decision_question(answers[i], q)
        rec = {"class": cls, "chosen": answers[i], "header": q.get("header"), **det}
        if failure:
            rec["parse_note"] = failure
        out["questions"].append(rec)
    return out

def build_decisions(events):
    """Aggregate paired AskUserQuestion events into the receipt's
    decisions block (the caller attaches the scope label). `events`
    is a list of (call_input, result_text_or_None, is_error) in
    transcript order, as parse_session collects them.

    Counting follows the decision-points spike exactly. decision_points
    counts every question in an answered call, including answers that
    could not be classified (those are also counted in coverage as
    unparseable_answers, the unmeasured_segments precedent).
    rejected_decision_calls counts calls, not questions: a refused
    call never decomposes into answered questions."""
    counts = Counter()
    for call_input, result, is_error in events:
        call = _classify_decision_call(call_input, result, is_error)
        status = call["status"]
        if status == "input_unparseable":
            counts["input_unparseable_decision_calls"] += 1
        elif status == "errored":
            counts["errored_decision_calls"] += 1
        elif status == "dismissed":
            counts["dismissed_decision_calls"] += 1
        elif status == "rejected":
            counts["rejected_decision_calls"] += 1
        else:
            for q in call["questions"]:
                counts["decision_points"] += 1
                if q.get("rec_label") is not None:
                    counts["decisions_with_recommendation"] += 1
                if q["class"] == "followed_recommendation":
                    counts["followed_recommendation"] += 1
                elif q["class"] == "diverged_to_listed":
                    counts["diverged_to_listed"] += 1
                elif q["class"] == "free_text":
                    counts["free_text_answers"] += 1
                else:
                    counts["unparseable_answers"] += 1
    return {
        "method": ("AskUserQuestion tool calls paired with their tool results "
                   "and each answered question classified by its chosen answer "
                   "(decision-points spike, Oct 2026): followed_recommendation "
                   "when the answer equals the option marked (Recommended), "
                   "diverged_to_listed when it equals a different listed option "
                   "(on unmarked questions, any listed pick), free_text_answers "
                   "when it matches no listed label; question text is never "
                   "stored, counts and categories only"),
        "decision_points": counts["decision_points"],
        "decisions_with_recommendation": counts["decisions_with_recommendation"],
        "followed_recommendation": counts["followed_recommendation"],
        "diverged_to_listed": counts["diverged_to_listed"],
        "free_text_answers": counts["free_text_answers"],
        "rejected_decision_calls": counts["rejected_decision_calls"],
        "coverage": {
            "errored_decision_calls": counts["errored_decision_calls"],
            "dismissed_decision_calls": counts["dismissed_decision_calls"],
            "input_unparseable_decision_calls": counts["input_unparseable_decision_calls"],
            "unparseable_answers": counts["unparseable_answers"],
        },
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
    (old_block, new_block), removed) with context lines in both blocks
    (they anchor the replace the join performs) and `removed` the
    frozenset of old-block line indices the hunk actually removes (its
    '-' lines; v1.4, for impact touch accounting: context lines are
    carried through unchanged and must not count as edited lines);
    Delete File -> ("delete", fp); Update + Move to -> ("move", fp,
    new_fp). A hunk with no old-side lines cannot anchor a replace and
    is counted unparsed, never guessed.
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
                old_block = []
                removed_idx = []
                for b in body:
                    if b[:1] in (" ", "-"):
                        if b[:1] == "-":
                            removed_idx.append(len(old_block))
                        old_block.append(b[1:])
                new_block = [b[1:] for b in body if b[:1] in (" ", "+")]
                if not old_block:
                    pc["hunks_unparsed"] += 1
                else:
                    pc["hunks_parsed"] += 1
                    if old_block != new_block:
                        ops.append(("edit", cx_path(cur_file, cwd),
                                    ("\n".join(old_block), "\n".join(new_block)),
                                    frozenset(removed_idx)))
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
    session_origin = None
    outcomes = {}
    tokens_in = tokens_out = 0
    ts_all = []
    for r in records:
        t = parse_ts(r.get("timestamp"))
        if t: ts_all.append(t)
        p = r.get("payload") or {}
        if r.get("type") == "session_meta":
            if p.get("cwd"):
                cwd = p["cwd"]
            if session_origin is None and (p.get("originator") or p.get("source")):
                # Rollout origin metadata: distinguishes interactive
                # front-ends from unattended exec runs. Keys the impact
                # scope label (impact spike check 3).
                session_origin = {"originator": p.get("originator"),
                                  "source": p.get("source")}
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

    def new_segment(prompt_text, pre=False, ts=None):
        seg = {"idx": len(segments), "prompt_chars": len(prompt_text),
               "correction_keyword": bool(CORRECTION_RE.search(prompt_text)) if prompt_text else False,
               "rubber_stamp": bool(RUBBER_RE.match(prompt_text)) if prompt_text else False,
               "after_error": pending_error, "ops": [], "tools": Counter(),
               "first_ts": ts,
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
            cur = new_segment(text, ts=r.get("timestamp"))
            pending_error = False
        elif r.get("type") == "response_item" and pt == "message" and p.get("role") == "user":
            txt = "".join((c.get("text") or c.get("input_text") or "") for c in p.get("content") or [])
            if txt.lstrip().startswith("<"):
                injected += 1
            # Genuine texts here duplicate the user_message events (the
            # segment starts above); wrappers are the injected count.
        elif r.get("type") == "response_item" and pt == "custom_tool_call" and p.get("name") == "apply_patch":
            if cur is None: cur = new_segment("", pre=True, ts=r.get("timestamp"))
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
            if cur is None: cur = new_segment("", pre=True, ts=r.get("timestamp"))
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
        "earliest_ts": min(ts_all).isoformat() if ts_all else None,
        "session_origin": session_origin,
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
def _is_earlier_origin(org, seg_idx):
    """True when a line's origin segment is an earlier human segment:
    not this segment, not the pre-existing seed (origin -1 is the
    repo's past, not an earlier turn of this session)."""
    return org is not None and org != seg_idx and org >= 0

def apply_ops(segments, seed_index=None, track=None):
    """Replay Write/Edit ops. Returns (files, stats, introduced, seeded_bases).

    files: path -> list[(line, origin_segment)]; origin PREEXISTING (-1) for
    lines that came from a --repo seed and were never agent-introduced.

    When `track` is a dict, it is filled with per-segment impact
    accounting (v1.4, ported from the impact spike's tracked replay):
    track[seg_idx] gains ops_applied, overlap_earlier_lines (earlier-
    segment lines an applied op edited or destroyed), overlap_delete_
    lines (earlier lines removed by an applied Delete), and
    first_touch_files (applied Writes to paths the replay had never
    produced). The accounting mirrors the spike exactly: an Edit counts
    the non-blank earlier-origin lines inside the replaced span (for
    Codex patch hunks, only the lines the hunk removes, never its
    context lines), and a Write/Edit merge additionally counts the
    earlier-origin lines the merge destroys. Snapshot prefix replays
    pass track=None and pay nothing for this.
    """
    files = {}
    stats = Counter()
    introduced = Counter()
    seeded_bases = {}   # fp -> original seeded lines (for the -1 snapshot)
    base_kind = {}      # fp -> "seeded" | "transcript"
    touched = set()     # paths the replay has produced (impact first-touch)

    def seg_track(seg_idx):
        if track is None: return None
        return track.setdefault(seg_idx, Counter())

    def provenance_merge(old, new_lines, seg_idx, destroyed=None):
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
            if destroyed is not None and tag in ("replace", "delete"):
                for ln, org in old[i1:i2]:
                    if ln.strip() and _is_earlier_origin(org, seg_idx):
                        destroyed.append(org)
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
        touched.add(fp)  # pre-existing: no segment can first-touch it
        stats["files_seeded"] += 1
        return True

    for seg in segments:
        st = seg_track(seg["idx"])
        for op in seg["ops"]:
            if op[0] == "write":
                _, fp, content = op
                lines = content.splitlines()
                old = files.get(fp, [])
                destroyed = [] if track is not None else None
                files[fp] = provenance_merge(old, lines, seg["idx"], destroyed) if old else [(l, seg["idx"]) for l in lines]
                if not old: introduced[seg["idx"]] += sum(1 for l in lines if l.strip())
                base_kind[fp] = "transcript"
                stats["writes"] += 1
                if track is not None:
                    st["ops_applied"] += 1
                    st["overlap_earlier_lines"] += len(destroyed or [])
                    if fp not in touched:
                        st["first_touch_files"] += 1
                    touched.add(fp)
            elif op[0] == "delete":
                # Codex apply_patch Delete File (the Claude Code adapter
                # never emits this; Claude Code has no delete tool).
                _, fp = op
                stats["deletes"] += 1
                if fp in files:
                    removed = files.pop(fp); base_kind.pop(fp, None)
                    stats["deletes_applied"] += 1
                    if track is not None:
                        st["ops_applied"] += 1
                        st["overlap_delete_lines"] += sum(
                            1 for l, org in removed
                            if l.strip() and _is_earlier_origin(org, seg["idx"]))
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
                    touched.add(new_fp)
                    if track is not None: st["ops_applied"] += 1
                else:
                    stats["moves_unapplied"] += 1
            else:
                fp = op[1]; (old_s, new_s) = op[2]
                removed_mask = op[3] if len(op) > 3 else None
                stats["edits"] += 1
                if fp not in files and not try_seed(fp):
                    stats["edits_unapplied_no_base"] += 1; continue
                cur = files[fp]
                cur_text = "\n".join(l for l, _ in cur)
                if old_s and old_s in cur_text:
                    if track is not None:
                        # Span accounting (impact spike): map the exact
                        # occurrence replace() will hit to line indices
                        # and count its non-blank earlier-origin lines.
                        # A patch hunk's removed_mask restricts the count
                        # to the lines the hunk removes; context lines in
                        # the span are carried through, not edited.
                        pos = cur_text.find(old_s)
                        start = cur_text[:pos].count("\n")
                        end = cur_text[:pos + len(old_s) - 1].count("\n")
                        end = min(end, len(cur) - 1)
                        for k, (ln, org) in enumerate(cur[start:end + 1]):
                            if removed_mask is not None and k not in removed_mask:
                                continue
                            if ln.strip() and _is_earlier_origin(org, seg["idx"]):
                                st["overlap_earlier_lines"] += 1
                    new_text = cur_text.replace(old_s, new_s, 1)
                    destroyed = [] if track is not None else None
                    files[fp] = provenance_merge(cur, new_text.splitlines(), seg["idx"], destroyed)
                    if track is not None:
                        st["ops_applied"] += 1
                        st["overlap_earlier_lines"] += len(destroyed or [])
                    stats["edits_applied_seeded" if base_kind.get(fp) == "seeded" else "edits_applied"] += 1
                else:
                    stats["edits_unapplied_no_match"] += 1
    return files, stats, introduced, seeded_bases

def _git_date_env(iso_ts):
    """GIT_AUTHOR_DATE / GIT_COMMITTER_DATE for a pinned commit date
    (hash-commitment spec section 4): the segment's first transcript
    timestamp as a unix time in UTC. Unparseable input gives the epoch,
    the spec's final fallback."""
    dt = parse_ts(iso_ts) if iso_ts else None
    if dt is None:
        return {"GIT_AUTHOR_DATE": "@0 +0000", "GIT_COMMITTER_DATE": "@0 +0000"}
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    # git's internal raw format; the "@" prefix matters: a bare "0 +0000"
    # (the epoch fallback) is rejected as an invalid date format.
    stamp = f"@{int(dt.timestamp())} +0000"
    return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}

def build_git_repo(snapshots, out_repo, commit_dates=None):
    """One commit per snapshot (segment -1 = pre-existing seed base, if any).
    Returns (commit_of_segment, blame Counter over non-blank lines).

    `commit_dates` (v1.4, only under --commitment) maps segment index
    to an ISO timestamp; author and committer dates of that segment's
    commit are pinned to it so a verifier's re-run reproduces the same
    HEAD SHA (specs/hash-commitment.md section 4). None keeps the
    historical behaviour: wall-clock commit dates, unpinned.
    """
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
        kw = {}
        if commit_dates is not None:
            kw["env"] = {**os.environ, **_git_date_env(commit_dates.get(seg_idx))}
        git("commit", "-q", "--allow-empty", "-m", msg, **kw)
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

# ---------------------------------------------------------------- impact + marks
IMPACT_SCOPE_CC = (
    "Impact classes measure inter-segment rework. The segments of this "
    "receipt are the human's own typed inputs in an interactive Claude "
    "Code session, so reshaping reads as human steering: a later input "
    "changed what an earlier input produced.")
IMPACT_SCOPE_CODEX_EXEC = (
    "Impact classes measure inter-segment rework. This rollout's turns "
    "are scripted task prompts fired by an unattended Codex exec run "
    "(session origin: codex_exec / exec), not a human typing in reaction "
    "to output, so reshaping here measures the scripted schedule and "
    "agent self-repair, not human steering.")
IMPACT_SCOPE_CODEX_OTHER = (
    "Impact classes measure inter-segment rework. They read as "
    "human-steering evidence only where the turns are genuine human "
    "input; this rollout's origin metadata does not establish that.")

def impact_scope_label(harness, meta):
    if harness == "codex":
        origin = meta.get("session_origin") or {}
        if origin.get("originator") == "codex_exec" or origin.get("source") == "exec":
            return IMPACT_SCOPE_CODEX_EXEC
        return IMPACT_SCOPE_CODEX_OTHER
    return IMPACT_SCOPE_CC

def classify_impact(segments, track):
    """Effect-based segment classes (v1.4; impact spike method).

    Returns (impact_dict, per_segment_map) where per_segment_map maps
    segment idx -> {"impact_class", "redirect", "overlap_earlier_lines"}
    for genuine human segments. Classes, from measured effect only:
    procedural (no ops attributed), unmeasured (ops attributed, none
    applied in the replay), reshaping (an applied op edited or deleted
    earlier-segment lines), continuation (anything else that applied).
    """
    human = [s for s in segments if not s.get("pre_prompt")]
    first_idx = human[0]["idx"] if human else None
    counts = Counter()
    per = {}
    reshaping_lines = 0
    redirect_count = 0
    for s in human:
        idx = s["idx"]
        t = (track or {}).get(idx) or Counter()
        overlap = t["overlap_earlier_lines"] + t["overlap_delete_lines"]
        if len(s["ops"]) == 0:
            cls = "procedural"
        elif t["ops_applied"] == 0:
            cls = "unmeasured"
        elif overlap > 0:
            cls = "reshaping"
        else:
            cls = "continuation"
        is_redirect = idx != first_idx and t["first_touch_files"] > 0
        counts[cls] += 1
        reshaping_lines += overlap
        if is_redirect: redirect_count += 1
        per[idx] = {"impact_class": cls, "redirect": is_redirect,
                    "overlap_earlier_lines": overlap}
    n = len(human)
    impact = {
        "method": ("effect-based segment classification from line provenance "
                   "(impact spike, Oct 2026): a segment is reshaping when an "
                   "applied op edited or deleted lines an earlier segment "
                   "introduced; prompt text is never read"),
        "procedural_turns": counts["procedural"],
        "continuation_turns": counts["continuation"],
        "reshaping_turns": counts["reshaping"],
        "unmeasured_segments": counts["unmeasured"],
        "reshaping_share_pct": round(100 * counts["reshaping"] / n, 1) if n else None,
        "reshaping_lines": reshaping_lines,
        "redirect_segments": redirect_count,
    }
    return impact, per

def code_mark(impact, per_segment_map):
    """The steering mark (code mode). A category word naming the
    process shape; it is not a grade (see SCHEMA.md)."""
    turns = (impact["procedural_turns"] + impact["continuation_turns"]
             + impact["reshaping_turns"] + impact["unmeasured_segments"])
    effect_followups = 0
    seen_first = False
    for idx in sorted(per_segment_map):
        if not seen_first:
            seen_first = True
            continue
        if per_segment_map[idx]["impact_class"] in ("continuation", "reshaping"):
            effect_followups += 1
    r, share, lines = (impact["reshaping_turns"], impact["reshaping_share_pct"],
                       impact["reshaping_lines"])
    if effect_followups == 0:
        return {"category": "One-shot",
                "basis": f"{turns} human turn{'s' if turns != 1 else ''}; no follow-up turn changed the artifact"}
    if r == 0:
        return {"category": "Prompted",
                "basis": f"{turns} human turns; follow-ups added work but never reshaped what an earlier turn produced"}
    if r >= 3 and share is not None and share >= 20:
        return {"category": "Closely steered",
                "basis": (f"{turns} human turns; {r} of them reshaped earlier work "
                          f"({share}% of turns, {lines} earlier lines rewritten)")}
    return {"category": "Steered",
            "basis": (f"{turns} human turns; {r} reshaped earlier work "
                      f"({lines} earlier lines rewritten)")}

def doc_mark(sections, revisions, floor_pct):
    """The steering mark (doc mode). `sections` are per-section dicts
    as doc_join builds them, still carrying the private `_first_titles`
    set. A section counts as reshaped when it already existed in the
    first version (its title is among the first version's sections),
    some of its first-version lines survive, and later revisions also
    introduced lines into it."""
    first_titles = sections[0]["_first_titles"] if sections else set()
    reshaped = sum(1 for s in sections
                   if s["section"] in first_titles
                   and s["pct_unchanged_from_first_version"] > 0
                   and len(s["introduced_by_revision"]) > 1)
    n = len(sections)
    if revisions <= 1:
        cat, basis = "One-shot", "1 revision; nothing arrived after the first version"
    elif reshaped == 0:
        cat = "Prompted"
        basis = (f"{revisions} revisions; later revisions only added sections "
                 f"and never reshaped a section that already existed")
    elif reshaped * 2 >= max(1, n) or (floor_pct is not None and floor_pct < 50):
        cat = "Closely steered"
        basis = (f"{revisions} revisions; {reshaped} of {n} sections were reshaped "
                 f"after introduction, and at least {floor_pct}% of the final text "
                 f"survives verbatim from the first version")
    else:
        cat = "Steered"
        basis = (f"{revisions} revisions; {reshaped} of {n} sections were reshaped "
                 f"after they were introduced")
    return {"category": cat, "basis": basis,
            "reshaped_sections": reshaped, "sections": n}

# ---------------------------------------------------------------- code receipt
def code_receipt(session_path, label, repo_dir=None, repo_ref=None, recon_dir=None, fmt="auto",
                 commitment=False):
    if fmt == "auto":
        fmt = detect_format(session_path)
    if fmt == "codex":
        segments, meta = parse_codex_session(session_path)
    else:
        segments, meta = parse_session(session_path)
        fmt = "claude-code"
    seed_index = SeedIndex(repo_dir, ref=repo_ref) if repo_dir else None
    track = {}
    files, stats, introduced, seeded_bases = apply_ops(segments, seed_index, track=track)
    # snapshots: optional -1 seed base, then one per segment (prefix replays)
    snapshots = []
    if seeded_bases:
        snapshots.append((PREEXISTING, {fp: list(lines) for fp, lines in seeded_bases.items()}))
    for i in range(len(segments)):
        f_i, _, _, _ = apply_ops(segments[: i + 1], seed_index)
        snapshots.append((segments[i]["idx"], {fp: [l for l, _ in v] for fp, v in f_i.items()}))
    if recon_dir is None:
        recon_dir = Path(__file__).parent / "reconstructed" / f"reconstructed-{label}"
    commit_dates = None
    if commitment:
        # A committed receipt must be reproducible bit-for-bit by a
        # verifier's re-run (spec section 4): rebuild the reconstructed
        # repo from scratch with pinned commit dates, so its HEAD SHA
        # depends only on the transcript and the seeding inputs.
        if Path(recon_dir).exists():
            shutil.rmtree(recon_dir)
        fallback = meta.get("earliest_ts") or "1970-01-01T00:00:00+00:00"
        def pinned_ts(seg):
            # Spec fallback chain: the segment's own first timestamp if
            # parseable, else the first parseable timestamp in the
            # transcript, else (inside _git_date_env) the epoch.
            ts = seg.get("first_ts")
            return ts if (ts and parse_ts(ts)) else fallback
        seg_ts = [s.get("first_ts") for s in segments if s.get("first_ts") and parse_ts(s["first_ts"])]
        commit_dates = {s["idx"]: pinned_ts(s) for s in segments}
        if seeded_bases:
            commit_dates[PREEXISTING] = min(seg_ts) if seg_ts else fallback
    commit_map, blame = build_git_repo(snapshots, recon_dir, commit_dates=commit_dates) if snapshots else ({}, Counter())
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
    impact, impact_per = classify_impact(segments, track)
    impact["scope"] = impact_scope_label(fmt, meta)
    mark = code_mark(impact, impact_per)
    # Decision events never created segments (they were collected
    # alongside the parse) and do not feed the mark in this build.
    # Codex rollouts contain no such events (see the scope label), so
    # the block is built from an empty event list and reads zeros.
    decisions = build_decisions([] if fmt == "codex" else meta.get("decision_events", []))
    decisions["scope"] = decisions_scope_label(fmt, meta)
    per_segment = []
    if origin_counts.get(PREEXISTING):
        per_segment.append({
            "segment": PREEXISTING, "kind": "pre-existing (seeded from --repo)",
            "prompt_chars": 0, "correction_keyword": False, "after_error": False,
            "rubber_stamp": False, "edit_write_ops": 0, "lines_introduced_gross": 0,
            "lines_surviving_to_head": origin_counts[PREEXISTING],
        })
    for s in segments:
        row = {
            "segment": s["idx"], "prompt_chars": s["prompt_chars"],
            "correction_keyword": s["correction_keyword"], "after_error": s["after_error"],
            "rubber_stamp": s["rubber_stamp"], "edit_write_ops": len(s["ops"]),
            "lines_introduced_gross": introduced.get(s["idx"], 0),
            "lines_surviving_to_head": origin_counts.get(s["idx"], 0),
        }
        if s["idx"] in impact_per:
            row.update(impact_per[s["idx"]])
        per_segment.append(row)
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
        "validation_scope": CODE_VALIDATION_SCOPE,
        "mark": mark,
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
            "impact": impact,
            "blame_vs_memory_provenance_agreement_pct": round(100 * agree / blame_total, 1) if blame_total else None,
            "per_segment": per_segment,
            "per_file": [{"file": fp, "final_lines": sum(1 for l, _ in v if l.strip()),
                          "first_segment_share_pct": round(100 * sum(1 for l, o in v if l.strip() and segments and o == fas_idx) / max(1, sum(1 for l, _ in v if l.strip())), 1) if v else 0,
                          "preexisting_share_pct": round(100 * sum(1 for l, o in v if l.strip() and o == PREEXISTING) / max(1, sum(1 for l, _ in v if l.strip())), 1) if v else 0}
                         for fp, v in sorted(files.items(), key=lambda kv: -len(kv[1]))[:15]],
        },
        "decisions": decisions,
        "labels": {"semantic_weights": "none — rule-based categories only; no model calls",
                   "receipt_nature": "descriptive evidence, not a certified grade",
                   "mark_semantics": "the mark names the process shape (how the work was steered), never its quality; it is not a grade",
                   "field_status": "headline_fields validated in spike; context_fields demoted (survival saturates on greenfield corpora); supporting_fields noisy, read jointly with turn count"},
    }
    if meta.get("session_origin"):
        receipt["mechanistic"]["session_origin"] = meta["session_origin"]
    if commitment:
        receipt["commitment"] = _code_commitment(meta, recon_dir, repo_dir, repo_ref)
    return receipt

def _code_commitment(meta, recon_dir, repo_dir, repo_ref):
    """The hash-commitment block (specs/hash-commitment.md section 2),
    computed in this same run from the same material the receipt was
    derived from. The transcript hash reuses the parse-time bytes via
    meta (the file is never re-read)."""
    def git_in(repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True).stdout.strip()
    block = {"algorithm": "sha256",
             "transcript_sha256": meta["transcript_sha256"],
             "repo_head_sha": git_in(recon_dir, "rev-parse", "HEAD")}
    if repo_dir:
        ref = repo_ref or "HEAD"
        seed_sha = git_in(repo_dir, "rev-parse", f"{ref}^{{commit}}")
        if re.fullmatch(r"[0-9a-f]{40}", seed_sha or ""):
            block["seed_repo_head_sha"] = seed_sha
        # else: the seed source does not resolve to a commit (e.g. a
        # plain directory of files); the field is omitted, never
        # emitted empty.
    artifact = {}
    listing = git_in(recon_dir, "ls-tree", "-r", "--name-only", "HEAD")
    for rel in listing.splitlines():
        if not rel:
            continue
        data = subprocess.run(["git", "-C", str(recon_dir), "cat-file", "blob",
                               f"HEAD:{rel}"], capture_output=True).stdout
        artifact[rel] = hashlib.sha256(data).hexdigest()
    block["artifact_file_sha256"] = artifact
    return block

# ---------------------------------------------------------------- doc receipt (provider-based since v1.4)
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

def doc_receipt_provider(provider_name, label, *, repo=None, path=None,
                         file_id=None, folder=None, section_strategy="auto",
                         commitment=False, transport=None):
    """Document receipt from any history provider (v1.4).

    The provider answers one question (what are the artifact's
    snapshots, oldest first); doc_join does the math, once, for every
    source. `transport` is the gdrive-doc fixture seam, threaded through
    for tests; the CLI never passes it.
    """
    from doc_join import doc_join
    from providers import ArtifactRef, get_provider
    from providers.gdrive_doc import GDriveDocProvider
    if provider_name == "gdrive-doc" and transport is not None:
        prov = GDriveDocProvider(transport=transport)
    else:
        prov = get_provider(provider_name)
    if provider_name == "git":
        locator, source = f"{repo}::{path}", f"{repo} :: {path}"
    elif provider_name == "folder":
        locator, source = str(folder), f"folder :: {folder}"
    elif provider_name == "gdrive-doc":
        locator, source = str(file_id), f"gdrive-doc :: {file_id}"
    else:
        locator, source = str(repo or path or file_id or folder), str(repo or path or file_id or folder)
    ref = ArtifactRef(provider_name, locator)
    meta = prov.describe(ref)
    snaps = prov.snapshots(ref)
    if not snaps:
        raise SystemExit(f"no history for {source} via provider {provider_name}")
    versions = [(s.id, s.content()) for s in snaps]
    receipt = doc_join(versions, label=label, source=source,
                       provider=provider_name,
                       history_complete=meta.history_complete,
                       section_strategy=section_strategy,
                       authors=[s.author for s in snaps])
    if commitment:
        receipt["commitment"] = _doc_commitment(provider_name, versions,
                                                 repo=repo, path=path)
    return receipt

def _doc_commitment(provider_name, versions, *, repo=None, path=None):
    """Revision content hashes (specs/hash-commitment.md section 2/3).
    Git: over the stored blob bytes (git cat-file), never the join's
    text-decoded content. Other providers: over the snapshot text as
    UTF-8, the only byte string those sources define."""
    digests = []
    if provider_name == "git":
        for sid, _txt in versions:
            data = subprocess.run(["git", "-C", str(repo), "cat-file", "blob",
                                   f"{sid}:{path}"], capture_output=True).stdout
            digests.append(hashlib.sha256(data).hexdigest())
    else:
        for _sid, txt in versions:
            digests.append(hashlib.sha256(txt.encode("utf-8")).hexdigest())
    return {"algorithm": "sha256",
            "revision_content_sha256": digests,
            "final_content_sha256": digests[-1] if digests else None}

def doc_receipt(repo_dir, rel_path, label, **kw):
    """The git doc path, kept at its v1 signature: doc_receipt(repo,
    path, label) is the interface the CLI's default UX and the plugin
    era tests use. Extra keyword arguments (section_strategy,
    commitment) pass through to doc_receipt_provider."""
    return doc_receipt_provider("git", label, repo=repo_dir, path=rel_path, **kw)

# ---------------------------------------------------------------- rendering
def render_md(r):
    lines = [f"# STEERING.md — {r['label']} ({r['kind']})", "",
             f"_Schema {r['schema']}. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._",
             f"_Harness: {r.get('harness')}._",
             f"_Validation scope: {r['validation_scope']}_"]
    if r.get("commitment"):
        c = r["commitment"]
        if r["kind"] == "code":
            line = (f"- Commitment (sha256): transcript {c['transcript_sha256'][:12]}…, "
                    f"reconstructed HEAD {c['repo_head_sha'][:12]}…")
            if c.get("seed_repo_head_sha"):
                line += f", seed repo {c['seed_repo_head_sha'][:12]}…"
            lines.append(line + ". Reveal the material to verify.")
        else:
            lines.append(f"- Commitment (sha256): final content {c['final_content_sha256'][:12]}…, "
                         f"{len(c['revision_content_sha256'])} revision content hashes. "
                         "Reveal the material to verify.")
    if r.get("mark"):
        lines.append(f"- Steering mark: **{r['mark']['category']}**. {r['mark']['basis']}. "
                     "The mark names the process shape, not a grade.")
    lines.append("")
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
                  f"- Blame vs in-memory provenance agreement: {g['blame_vs_memory_provenance_agreement_pct']}%"]
        if g.get("impact"):
            im = g["impact"]
            lines += [f"- Impact classes (measured effect from line provenance, never prompt wording): {im['procedural_turns']} procedural, {im['continuation_turns']} continuation, {im['reshaping_turns']} reshaping ({im['reshaping_lines']} earlier lines rewritten), {im['unmeasured_segments']} unmeasured, {im['redirect_segments']} redirect",
                      f"- Impact scope: {im['scope']}"]
        if r.get("decisions"):
            d = r["decisions"]
            dc = d["coverage"]
            lines += [f"- Decisions (structured questions the agent asked and the user answered): {d['decision_points']} answered questions, of which {d['followed_recommendation']} followed the marked recommendation (marked on {d['decisions_with_recommendation']} questions), {d['diverged_to_listed']} chose a different listed option, and {d['free_text_answers']} were answered in free text. {d['rejected_decision_calls']} question calls were rejected as posed.",
                      f"- Decision coverage: {dc['errored_decision_calls']} errored calls, {dc['dismissed_decision_calls']} dismissed calls, {dc['input_unparseable_decision_calls']} calls with unparseable recorded input, {dc['unparseable_answers']} unparseable answers.",
                      f"- Decision scope: {d['scope']}"]
        lines += [
                  "", "## Per-segment attribution", "",
                  "| segment | prompt chars | correction? | after error? | ops | lines introduced | lines surviving to HEAD |",
                  "|---|---|---|---|---|---|---|"]
        if "patch_calls" in c:
            cov_idx = next(i for i, l in enumerate(lines) if l.startswith("- Coverage:"))
            lines.insert(cov_idx + 1, f"- Codex channels: {c['patch_calls']} apply_patch calls ({c['patch_calls_failed']} failed and dropped whole, {c['patch_calls_unresolved']} unresolved), {c['patch_file_ops_parsed']} patch file ops in the join ({c['patch_hunks_parsed']} hunks parsed, {c['patch_hunks_unparsed']} hunks unparsed, {c['patch_file_ops_failed']} file ops inside failed patches), shell writes extracted {c['shell_writes_extracted']}, shell writes unparsed {c['shell_writes_unparsed']} (counted, never guessed into the join).")
        for s in g["per_segment"]:
            seg = "pre-existing" if s["segment"] == PREEXISTING else str(s["segment"])
            lines.append(f"| {seg} | {s['prompt_chars']} | {'yes' if s['correction_keyword'] else '—'} | {'yes' if s['after_error'] else '—'} | {s['edit_write_ops']} | {s['lines_introduced_gross']} | {s['lines_surviving_to_head']} |")
    else:
        rev_count = r.get("revision_count", r["revisions"])
        if r.get("provider"):
            lines.append(f"- History provider: {r['provider']} (history complete: {r.get('history_complete')}; section strategy: {r.get('section_strategy')})")
        if r.get("authors"):
            lines.append(f"- Authors: {', '.join(r['authors'])}")
        lines += [f"- Revisions{' in git history' if r.get('provider') in (None, 'git') else ''}: {r['revisions']} ({', '.join(r['revision_shas'])})",
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
def _infer_doc_provider(provider_arg, repo_arg, path_arg):
    """Resolve the doc provider from the reference. Returns
    (provider_name, ref) where ref is (repo, path) for git, (folder,)
    for folder, (file_id,) for gdrive-doc. An explicit --provider wins;
    a `scheme:` prefix on the reference is honoured; otherwise a
    document path means git (the default UX since v1), a directory
    means folder, and anything else is treated as a Drive file id."""
    if repo_arg:
        for scheme in ("git", "gdrive-doc", "folder"):
            if repo_arg.startswith(scheme + ":") and not Path(repo_arg).exists():
                provider_arg = provider_arg or scheme
                repo_arg = repo_arg[len(scheme) + 1:]
                break
    if provider_arg == "git":
        return "git", (repo_arg, path_arg)
    if provider_arg == "folder":
        return "folder", (repo_arg,)
    if provider_arg == "gdrive-doc":
        return "gdrive-doc", (repo_arg,)
    if path_arg is not None:
        return "git", (repo_arg, path_arg)
    if repo_arg and Path(repo_arg).is_dir():
        return "folder", (repo_arg,)
    return "gdrive-doc", (repo_arg,)

def main(argv=None):
    ap = argparse.ArgumentParser(prog="steering_receipt",
                                 description="Proof of Steering v1 — emit a steering receipt (JSON + STEERING.md) from a coding-agent transcript or a git-carried document. Local only; receipts never contain prompt text.")
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
    pc.add_argument("--commitment", action="store_true", help="emit the hash-commitment block (specs/hash-commitment.md): hashes of the exact material this receipt was derived from, computed in this run; replay commit dates are pinned so the reconstructed HEAD is reproducible")
    pd = sub.add_parser("doc", help="receipt from a document's history, via a history provider (git by default)")
    pd.add_argument("repo", help="git repo directory containing the document; with --provider folder, the folder of versioned files; with --provider gdrive-doc, the Drive file id")
    pd.add_argument("path", nargs="?", default=None, help="document path relative to the repo root (git provider only)")
    pd.add_argument("--provider", choices=["git", "gdrive-doc", "folder"], default=None,
                    help="history provider (default: inferred from the reference: git when a document path is given, folder when the reference is a directory of versioned files, gdrive-doc when it is a bare file id)")
    pd.add_argument("--section-strategy", choices=["auto", "markdown", "heuristic", "whole"], default="auto",
                    help="how the final version is sectioned (default auto: markdown markers, else conservative heading-like detection with >= 2 candidates, else one whole-document section)")
    pd.add_argument("--commitment", action="store_true", help="emit the hash-commitment block (specs/hash-commitment.md): SHA-256 of each revision's content, computed in this run")
    pd.add_argument("--label", required=True, help="receipt label (file names + receipt label field)")
    pd.add_argument("--out", default="receipts-out", help="output directory (default: receipts-out)")
    px = sub.add_parser("demo", help="run the pipeline on the bundled synthetic sample session and render a receipt, a badge, and a Steerprint map")
    px.add_argument("--out", default="demo-out", help="output directory (default: demo-out)")
    args = ap.parse_args(argv)
    if args.cmd == "code" and args.repo_ref and not args.repo:
        ap.error("--repo-ref requires --repo")
    if args.cmd == "demo":
        from demo import run_demo
        return run_demo(Path(args.out))

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    if args.cmd == "code":
        recon = Path(args.recon_dir) if args.recon_dir else out_dir / f"reconstructed-{args.label}"
        r = code_receipt(args.session, args.label, repo_dir=args.repo,
                         repo_ref=args.repo_ref, recon_dir=recon, fmt=args.format,
                         commitment=args.commitment)
    else:
        from providers import ProviderUnavailable
        provider_name, ref = _infer_doc_provider(args.provider, args.repo, args.path)
        try:
            if provider_name == "git":
                if ref[1] is None:
                    ap.error("the git provider needs a document path: doc REPO PATH")
                r = doc_receipt_provider("git", args.label, repo=ref[0], path=ref[1],
                                         section_strategy=args.section_strategy,
                                         commitment=args.commitment)
            elif provider_name == "folder":
                r = doc_receipt_provider("folder", args.label, folder=ref[0],
                                         section_strategy=args.section_strategy,
                                         commitment=args.commitment)
            else:
                r = doc_receipt_provider("gdrive-doc", args.label, file_id=ref[0],
                                         section_strategy=args.section_strategy,
                                         commitment=args.commitment)
        except ProviderUnavailable as e:
            ap.error(f"provider unavailable: {e}")
    (out_dir / f"{args.label}.receipt.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    (out_dir / f"{args.label}.STEERING.md").write_text(render_md(r), encoding="utf-8")
    summary = {"label": r["label"], "kind": r["kind"], "schema": r["schema"],
               "receipt_json": str(out_dir / f"{args.label}.receipt.json"),
               "steering_md": str(out_dir / f"{args.label}.STEERING.md")}
    if r.get("mark"):
        summary["mark"] = r["mark"]["category"]
    if r.get("commitment"):
        summary["commitment"] = True
    if r["kind"] == "code":
        summary.update({"human_turns": r["mechanistic"]["human_turns"],
                        "coverage": r["mechanistic"]["coverage"],
                        "impact": {k: r["git_join"]["impact"][k] for k in
                                   ("procedural_turns", "continuation_turns", "reshaping_turns",
                                    "unmeasured_segments", "reshaping_share_pct",
                                    "reshaping_lines", "redirect_segments")},
                        "post_first_prompt_share_pct": r["git_join"]["headline_fields"]["post_first_prompt_share_pct"],
                        "agreement_pct": r["git_join"]["blame_vs_memory_provenance_agreement_pct"]})
    else:
        summary.update({"provider": r.get("provider"),
                        "history_complete": r.get("history_complete"),
                        "revisions": r["revisions"],
                        "revision_count": r.get("revision_count"),
                        "overall_unchanged_pct": r["overall_pct_unchanged_from_first_version"],
                        "unchanged_sentence_share_pct": r.get("unchanged_sentence_share_pct"),
                        "sections": len(r["per_section"])})
    print(json.dumps(summary, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
