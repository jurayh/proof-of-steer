"""Proof of Steering — capture-time steering records. Stdlib only.

The rest of the tool reconstructs steering attribution after the
fact: it replays the transcript, rebuilds one git commit per
human-turn segment, and joins line provenance against git blame.
That join is inference, and receipts say so. This module is the
opposite direction (capture-spike, Oct 2026; adopted Oct 2026): at
commit time, while the session is live or just finished, it writes a
steering record as the commit's git note under refs/notes/steer,
stating which segments landed in that commit, what each segment
measurably did (its impact class, its decision outcomes as classes
only, the hunks it produced in that commit), and a SHA-256 of the
transcript bytes those claims came from. A later receipt then
separates captured segments (a record exists, is anchored to the
commit that carries it, and its segment hash matches the held
transcript) from inferred ones (the standing post-hoc pipeline) and
unmeasured ones, and prints the coverage split always.

Privacy, absolute: a record stores ids, hashes, counts, timestamps,
and line spans only. Never transcript text, never prompt text, never
file contents. The one string from the work itself is a file path in
a hunk entry, and that path is already in the commit the record
rides on. Decision entries store the class of each answer and
whether a recommendation existed; the classifier computes the
chosen answer text and this module discards it before writing.

Verification tiers, kept distinct everywhere in the product:
"verified against the transcript" means the segment hashes were
recomputed from held transcript bytes and the recorded hunks were
checked against the commit diffs. "verified against the commit"
means only the diff checks ran: they prove the recorded hunks are
really in the commit, not that the recorded classes are right. A
class lie passes the commit tier and fails the transcript tier
(capture-spike Gate B demonstrated both directions).

Registration: this module is the capture extension point. The CLI
wires it in steering_receipt.main (the `capture` and `notes`
subcommands, plus the `code --capture-repo` integration), and the
packaging registers the module in pyproject's py-modules list, the
same one-module-plus-registration shape as the history providers.
"""
import hashlib, json, re, subprocess, sys, tempfile
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import steering_receipt as sr

RECORD_SCHEMA = "proof-of-steering/steering-record@0.1-spike"
NOTES_REF = "steer"  # git notes --ref steer  ==  refs/notes/steer
NOTES_REFSPEC = "refs/notes/steer:refs/notes/steer"
BRANCH_REFSPEC = "refs/heads/*:refs/heads/*"
FETCH_REFSPEC = "+refs/notes/steer:refs/notes/steer"
REWRITE_REF = "refs/notes/steer"

CAPTURE_SCOPE = (
    "Capture fields separate segments whose steering was recorded "
    "at commit time in git notes (refs/notes/steer) from segments "
    "classified after the fact by replay. A segment counts as "
    "captured only when a record claims it, the record is anchored "
    "to the commit that carries it, and the recorded segment hash "
    "equals the hash of this transcript's segment bytes. Verified "
    "against the transcript means the segment hashes were "
    "recomputed from the held transcript and the recorded hunks "
    "were checked against the commit diffs. Verified against the "
    "commit means only the diff checks ran, which prove the "
    "recorded hunks are really in the commit, not that the "
    "recorded classes are right. Absence of records reads as zero "
    "captured, never as absence of steering.")
CAPTURE_SCOPE_CODEX = (
    "Capture records are written from Claude Code sessions in "
    "this build. Codex rollouts carry the capture block as zeros "
    "when a capture repo is supplied, so absence is visible and "
    "not silent.")
NOTES_ONLY_SCOPE = (
    "This partial receipt was built from capture-time steering "
    "records alone, with no transcript. Every field in it is "
    "verified against the commit at most: the recorded hunks were "
    "checked against the commit diffs, and the recorded classes "
    "passed the necessary-condition shape checks described in "
    "SCHEMA.md. Class honesty in full needs the transcript, which "
    "is not held here. Transcript-derived fields are unavailable, "
    "not zero.")


def _tool_id():
    try:
        from importlib.metadata import version
        return f"proof-of-steer {version('proof-of-steer')}"
    except Exception:
        return "proof-of-steer (source tree)"


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CaptureUnsupported(Exception):
    """Raised when capture is asked to handle a transcript shape it
    does not cover in this build (anything but Claude Code)."""


# ---------------------------------------------------------------- git helpers
def git(repo, *args, check=True, input_text=None):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, input=input_text)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def commit_hunks(repo, sha):
    """The commit's diff hunks against its first parent (the empty
    tree for a root commit), in the record's span format, sorted by
    file and start. Spans follow git's -U0 conventions: a side with
    zero lines names the line before the span."""
    r = git(repo, "diff-tree", "--root", "-r", "-U0", "--no-commit-id",
            "--format=", sha)
    hunks = []
    cur_file = None
    last_a = None
    for line in r.stdout.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
        elif line.startswith("+++ /dev/null"):
            cur_file = None  # deleted file: the header carries the a/ path
        elif line.startswith("--- a/"):
            last_a = line[6:]
        elif line.startswith("@@ "):
            spans = line.split("@@")[1].strip().split()
            old = spans[0][1:].split(",")
            new = spans[1][1:].split(",")
            hunks.append({"file": cur_file if cur_file is not None else last_a,
                          "start": int(new[0]),
                          "lines": int(new[1]) if len(new) > 1 else 1,
                          "removed_start": int(old[0]),
                          "removed_lines": int(old[1]) if len(old) > 1 else 1})
    return sorted(hunks, key=lambda h: (h["file"], h["start"], h["removed_start"]))


def list_noted_commits(repo):
    """commit sha -> note blob sha, for every note under the steer ref."""
    r = git(repo, "notes", "--ref", NOTES_REF, "list", check=False)
    out = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[1]] = parts[0]
    return out


def read_note(repo, sha):
    """The steering record attached to a commit, or None. A note that
    is not valid record JSON comes back marked _unparseable_note."""
    r = git(repo, "notes", "--ref", NOTES_REF, "show", sha, check=False)
    if r.returncode != 0:
        return None
    try:
        rec = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_unparseable_note": r.stdout}
    return rec if isinstance(rec, dict) else {"_unparseable_note": r.stdout}


def load_records(repo):
    """commit sha -> record dict, for every note under the steer ref.
    A repo with no notes (or not a git repo at all) reads as empty."""
    out = {}
    for sha in list_noted_commits(repo):
        rec = read_note(repo, sha)
        if rec is not None:
            out[sha] = rec
    return out


def write_note(repo, sha, record):
    """Attach a record (a dict) to a commit as its steer note,
    replacing any note already there."""
    blob = json.dumps(record, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(blob)
        tmp = fh.name
    try:
        git(repo, "notes", "--ref", NOTES_REF, "add", "-f", "-F", tmp, sha)
    finally:
        Path(tmp).unlink(missing_ok=True)


# ------------------------------------------------------------ transcript bytes
def _split_lines(data: bytes):
    """Split bytes into lines, terminators kept, lossless."""
    parts = data.split(b"\n")
    lines = [p + b"\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _record_of(line: bytes):
    try:
        rec = json.loads(line.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    return rec if isinstance(rec, dict) else None


def _genuine_user_text(rec) -> bool:
    """Mirror of parse_session's segment-open test for user records:
    non-empty joined text that is not an injected or meta record."""
    msg = rec.get("message") or {}
    content = msg.get("content")
    blocks = content if isinstance(content, list) else (
        [{"type": "text", "text": content}] if isinstance(content, str) else [])
    texts = [b.get("text", "") for b in blocks
             if isinstance(b, dict) and b.get("type") == "text"]
    joined = "\n".join(texts).strip()
    if not joined:
        return False
    if rec.get("isMeta") or joined.startswith(("<command-", "<local-command", "Caveat:")):
        return False
    return True


def split_transcript(path):
    """Partition a Claude Code session file into segments by raw bytes.

    Returns (segments, preamble): segments is a list of dicts
    {idx, raw, sha256, pre_prompt} in parse_session's segment order,
    preamble is the bytes before the first segment opened. The
    partition is lossless and the segment count is checked against
    the shipped parser, because a segment hash is only meaningful if
    the boundaries are exactly the parser's boundaries.
    """
    data = Path(path).read_bytes()
    segments = []
    current = None
    preamble = bytearray()
    for line in _split_lines(data):
        rec = _record_of(line)
        opens = False
        pre_prompt = False
        if rec is not None:
            if rec.get("type") == "user" and _genuine_user_text(rec):
                opens = True
            elif rec.get("type") == "assistant" and current is None:
                opens = True
                pre_prompt = True
        if opens:
            current = {"idx": len(segments), "raw": bytearray(),
                       "pre_prompt": pre_prompt}
            segments.append(current)
        if current is None:
            preamble += line
        else:
            current["raw"] += line
    for s in segments:
        s["raw"] = bytes(s["raw"])
        s["sha256"] = hashlib.sha256(s["raw"]).hexdigest()
    joined = bytes(preamble) + b"".join(s["raw"] for s in segments)
    if joined != data:
        raise ValueError("byte partition of the transcript is not lossless")
    parsed, _meta = sr.parse_session(path)
    if len(parsed) != len(segments):
        raise ValueError(
            f"splitter found {len(segments)} segments, the shipped parser "
            f"found {len(parsed)}")
    return segments, bytes(preamble)


# ------------------------------------------------------------ decisions per segment
def segment_decisions(path, n_segments):
    """Per-segment decision outcomes, classes only.

    Walks the transcript with the same boundary state machine as
    split_transcript, pairs AskUserQuestion calls with their results
    by tool_use id (as parse_session does), classifies each call with
    the shipped classifier, and returns a list indexed by segment idx
    of decision entries:

      {"status": <call status>,
       "questions": [{"class": ..., "with_recommendation": bool}]}

    The classifier also returns the chosen answer text; it is
    discarded here and never reaches a record. Totals are
    cross-checked against the shipped build_decisions, and a
    divergence raises: per-segment attribution that disagrees with
    the receipt's own decisions block must not be recorded silently.
    """
    _segments, meta = sr.parse_session(path)
    calls = {}    # tool_use_id -> (segment_idx, input)
    results = {}  # tool_use_id -> (result_text, is_error)
    current = -1
    for line in Path(path).read_bytes().splitlines():
        rec = _record_of(line)
        if rec is None:
            continue
        msg = rec.get("message") or {}
        if rec.get("type") == "user":
            if _genuine_user_text(rec):
                current += 1
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            for blk in blocks:
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    results[blk.get("tool_use_id")] = (
                        sr._decision_result_text(blk.get("content")),
                        bool(blk.get("is_error")))
        elif rec.get("type") == "assistant":
            if current < 0:
                current = 0  # pre-prompt segment
            for blk in (msg.get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use" \
                        and blk.get("name") == "AskUserQuestion":
                    calls[blk.get("id")] = (max(current, 0), blk.get("input") or {})
    per_segment = [[] for _ in range(n_segments)]
    events = []
    for call_id, (seg_idx, call_input) in calls.items():
        res = results.get(call_id)
        result_text = res[0] if res else None
        is_error = res[1] if res else False
        events.append((call_input, result_text, is_error))
        call = sr._classify_decision_call(call_input, result_text, is_error)
        entry = {"status": call["status"]}
        if call["status"] == "answered":
            entry["questions"] = [
                {"class": q["class"],
                 "with_recommendation": q.get("rec_label") is not None}
                for q in call["questions"]]
        per_segment[seg_idx].append(entry)
    shipped = sr.build_decisions(events)
    mine = Counter()
    for entries in per_segment:
        for e in entries:
            if e["status"] == "rejected":
                mine["rejected_decision_calls"] += 1
            for q in e.get("questions", []):
                mine["decision_points"] += 1
                key = {"followed_recommendation": "followed_recommendation",
                       "diverged_to_listed": "diverged_to_listed",
                       "free_text": "free_text_answers"}.get(
                           q["class"], "unparseable_answers")
                mine[key] += 1
    for k in ("decision_points", "followed_recommendation", "diverged_to_listed",
              "free_text_answers", "rejected_decision_calls"):
        if mine[k] != shipped[k]:
            raise ValueError(
                f"per-segment decision totals diverge on {k}: "
                f"{mine[k]} != shipped {shipped[k]}")
    if mine["unparseable_answers"] != shipped["coverage"]["unparseable_answers"]:
        raise ValueError("per-segment decision totals diverge on "
                         "unparseable_answers")
    return per_segment


# ------------------------------------------------------------ segment records
def snapshot_diff_hunks(old_lines, new_lines):
    """Diff hunks between two artifact states, in the record's span
    format, using git's -U0 span conventions. Computed with
    SequenceMatcher opcodes: each non-equal opcode is one hunk."""
    hunks = []
    sm = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        removed = i2 - i1
        added = j2 - j1
        hunks.append({
            "start": j1 + 1 if added else j1,
            "lines": added,
            "removed_start": i1 + 1 if removed else i1,
            "removed_lines": removed,
        })
    return hunks


def build_segment_records(session_path, seed_index=None):
    """Full capture analysis of one Claude Code session.

    Returns a dict with the parsed segments, the impact
    classification, per-human-segment record entries (impact class,
    redirect, overlap, decision outcomes as classes only, the
    segment's raw-byte SHA-256, and its hunks in session-replay
    snapshot coordinates, the provisional form the checkpoint file
    carries), the replay's final per-line provenance (used to
    attribute a real commit's hunks at attach time), and each
    segment's removed line texts per file (same purpose).
    """
    if sr.detect_format(session_path) == "codex":
        raise CaptureUnsupported(
            "capture records are written from Claude Code sessions in "
            "this build; Codex rollouts are not captured")
    segments, meta = sr.parse_session(session_path)
    byte_segments, _preamble = split_transcript(session_path)
    track = {}
    files, _stats, _introduced, seeded_bases = sr.apply_ops(
        segments, seed_index, track=track)
    _impact, impact_per = sr.classify_impact(segments, track)
    decisions = segment_decisions(session_path, len(segments))

    # prefix snapshots as line lists, for snapshot-diff hunks and
    # removed-line attribution; the seeded base is segment 0's "before"
    snapshots = []
    for i in range(len(segments)):
        f_i, _, _, _ = sr.apply_ops(segments[: i + 1], seed_index)
        snapshots.append({fp: [l for l, _ in v] for fp, v in f_i.items()})
    base_snapshot = {fp: list(lines) for fp, lines in seeded_bases.items()}

    records = []
    removed_texts = {}
    for s in segments:
        idx = s["idx"]
        if s.get("pre_prompt"):
            continue
        prev = snapshots[idx - 1] if idx > 0 else base_snapshot
        cur = snapshots[idx] if idx < len(snapshots) else {}
        hunks = []
        removed = {}
        for fp in sorted(set(prev) | set(cur)):
            old = prev.get(fp, [])
            new = cur.get(fp, [])
            if old == new:
                continue
            for h in snapshot_diff_hunks(old, new):
                hunks.append({"file": fp, **h})
            gone = Counter(old) - Counter(new)
            if gone:
                removed[fp] = gone
        hunks.sort(key=lambda h: (h["file"], h["start"], h["removed_start"]))
        removed_texts[idx] = removed
        records.append({
            "turn": idx,
            "impact_class": impact_per[idx]["impact_class"],
            "redirect": impact_per[idx]["redirect"],
            "overlap_earlier_lines": impact_per[idx]["overlap_earlier_lines"],
            "decisions": decisions[idx],
            "hunks": hunks,
            "transcript_sha256": byte_segments[idx]["sha256"],
        })
    return {"segments": segments, "meta": meta, "impact_per": impact_per,
            "records": records, "byte_segments": byte_segments,
            "replay_final": files, "removed_texts": removed_texts}


def make_record(commit, harness, segment_records, captured_at=None):
    """Assemble one steering record in the spike's format, unchanged:
    a schema id, the anchor commit, the harness, the capture time,
    the tool, and the segments array."""
    return {
        "schema": RECORD_SCHEMA,
        "commit": commit,
        "harness": harness,
        "captured_at": captured_at or utcnow_iso(),
        "tool": _tool_id(),
        "segments": sorted(segment_records, key=lambda r: r["turn"]),
    }


def attach_record(repo, commit, record):
    """Write a record as the commit's steer note. If the commit
    already carries a record, the two are merged: segments combine
    by turn with the incoming record winning, and the anchor is
    (re)set to this commit, which is also how a record whose anchor
    went stale in a history rewrite is re-anchored. Returns the
    record as written."""
    existing = read_note(repo, commit)
    merged = dict(record)
    merged["commit"] = commit
    if isinstance(existing, dict) and not existing.get("_unparseable_note") \
            and existing.get("segments"):
        by_turn = {s["turn"]: s for s in existing["segments"]}
        for s in record["segments"]:
            by_turn[s["turn"]] = s
        merged["segments"] = [by_turn[t] for t in sorted(by_turn)]
    write_note(repo, commit, merged)
    return merged


# ------------------------------------------------------------ commit hunk attribution
def _show_lines(repo, spec):
    r = git(repo, "show", spec, check=False)
    if r.returncode != 0:
        return []
    return r.stdout.splitlines()


def attribute_commit_hunks(repo, commit, records, replay_final, removed_texts):
    """Attribute a real commit's hunks to the segments being recorded.

    Additions: the commit diff's new-side spans are split at replay
    provenance boundaries. The replay's final lines are aligned to
    the commit's lines by text (SequenceMatcher), so a line the
    commit holds carries the origin segment the replay assigns it,
    and consecutive same-origin lines form one recorded hunk.
    Additions whose origin is not one of the segments being recorded
    (pre-existing lines, earlier sessions, hand edits) are claimed by
    nobody here: the record under-claims rather than over-claims.

    Removals: the commit diff's removed lines, in order per file,
    are matched against each segment's removed line texts from the
    replay (in turn order, earliest segment first), and consecutive
    matched positions form the recorded removed spans. Removals no
    segment's replay explains stay unclaimed.

    Returns {turn: [hunks in commit coordinates]}. Addition and
    removal spans in the same file are paired in order into single
    hunks; leftovers carry a zero count on the other side with the
    anchor git would print for a span of that shape.
    """
    attaching = {r["turn"] for r in records}
    real = commit_hunks(repo, commit)
    by_file = {}
    for h in real:
        by_file.setdefault(h["file"], []).append(h)
    parents = git(repo, "rev-list", "--parents", "-n", "1", commit).stdout.split()
    parent = parents[1] if len(parents) > 1 else None

    additions = {}  # turn -> {file: [(start, lines)]}
    removals = {}   # turn -> {file: [(removed_start, removed_lines)]}
    for fp, hunks in by_file.items():
        commit_lines = _show_lines(repo, f"{commit}:{fp}")
        parent_lines = _show_lines(repo, f"{parent}:{fp}") if parent else []
        # Session transcripts carry absolute file paths; the commit
        # carries repo-relative ones. Match the replay's key for this
        # file by exact name or path suffix, the same rule the seed
        # index uses.
        rkey = fp if fp in replay_final else next(
            (k for k in replay_final if k.endswith("/" + fp)), None)
        replay_lines = replay_final.get(rkey, []) if rkey else []
        replay_texts = [l for l, _ in replay_lines]
        origin_at = {}  # commit line number (1-based) -> origin segment
        sm = SequenceMatcher(a=replay_texts, b=commit_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    origin_at[j1 + k + 1] = replay_lines[i1 + k][1]
        # anchors for zero-count sides, from the diff's own totals
        added_before = Counter()   # new-side lines added before a position
        removed_before = Counter()
        total_added = total_removed = 0
        for h in hunks:
            added_before[h["start"]] = total_added
            removed_before[h["removed_start"]] = total_removed
            total_added += h["lines"]
            total_removed += h["removed_lines"]
        for h in hunks:
            # additions, split by origin
            pos = h["start"]
            end = h["start"] + h["lines"]
            while pos < end:
                org = origin_at.get(pos)
                run = pos
                while run < end and origin_at.get(run) == org:
                    run += 1
                if org in attaching:
                    additions.setdefault(org, {}).setdefault(fp, []).append(
                        (pos, run - pos))
                pos = run
            # removals, matched to segments by removed line text
            rpos = h["removed_start"]
            rend = h["removed_start"] + h["removed_lines"]
            queues = {t: Counter(removed_texts.get(t, {}).get(rkey, {}))
                      for t in sorted(attaching)}
            while rpos < rend:
                text = parent_lines[rpos - 1] if 0 < rpos <= len(parent_lines) else None
                owner = None
                for t in sorted(attaching):
                    if text is not None and queues[t][text] > 0:
                        queues[t][text] -= 1
                        owner = t
                        break
                if owner is not None:
                    # the owner search already consumed the line at
                    # rpos; extend the run from the next position
                    run = rpos + 1
                    while run < rend:
                        t2 = parent_lines[run - 1] if 0 < run <= len(parent_lines) else None
                        if t2 is not None and queues[owner][t2] > 0:
                            queues[owner][t2] -= 1
                            run += 1
                        else:
                            break
                    removals.setdefault(owner, {}).setdefault(fp, []).append(
                        (rpos, run - rpos))
                    rpos = run
                else:
                    rpos += 1  # unclaimed removal line
    out = {}
    for turn in attaching:
        hunks = []
        files = set(additions.get(turn, {})) | set(removals.get(turn, {}))
        for fp in sorted(files):
            adds = sorted(additions.get(turn, {}).get(fp, []))
            rems = sorted(removals.get(turn, {}).get(fp, []))
            paired = min(len(adds), len(rems))
            for i in range(paired):
                hunks.append({"file": fp, "start": adds[i][0], "lines": adds[i][1],
                              "removed_start": rems[i][0],
                              "removed_lines": rems[i][1]})
            for s, ln in adds[paired:]:
                hunks.append({"file": fp, "start": s, "lines": ln,
                              "removed_start": s - 1, "removed_lines": 0})
            for s, ln in rems[paired:]:
                hunks.append({"file": fp, "start": s - 1, "lines": 0,
                              "removed_start": s, "removed_lines": ln})
        hunks.sort(key=lambda h: (h["file"], h["start"], h["removed_start"]))
        out[turn] = hunks
    return out


# ------------------------------------------------------------ init (setup)
def init_repo(repo, remote="origin"):
    """Write the documented one-time setup into a repo's config.

    Idempotent. Writes the notes fetch refspec, the notes push
    refspec WITH the branch push refspec alongside it (a lone notes
    push refspec makes git push exactly the configured refspecs and
    silently drops the branches, the trap capture-spike Gate A
    caught), and notes.rewriteRef covering refs/notes/steer so git
    copies records onto amended and rebased commits where it
    supports doing so. Returns a summary of what was added and what
    was already present.
    """
    repo = Path(repo)
    if git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise ValueError(f"not a git repository: {repo}")
    wanted = [
        (f"remote.{remote}.fetch", FETCH_REFSPEC),
        (f"remote.{remote}.push", BRANCH_REFSPEC),
        (f"remote.{remote}.push", NOTES_REFSPEC),
        ("notes.rewriteRef", REWRITE_REF),
    ]
    added, present = [], []
    for key, value in wanted:
        existing = git(repo, "config", "--get-all", key,
                       check=False).stdout.splitlines()
        if value in existing:
            present.append(f"{key} = {value}")
        else:
            git(repo, "config", "--add", key, value)
            added.append(f"{key} = {value}")
    remotes = git(repo, "remote").stdout.split()
    return {"repo": str(repo), "remote": remote,
            "added": added, "already_present": present,
            "origin_configured": remote in remotes}


# ------------------------------------------------------------ checkpoint state
def _state_name(session_id):
    s = re.sub(r"[^A-Za-z0-9._-]", "-", str(session_id or "session"))[:80]
    return f"{s or 'session'}.json"


def state_dir_for(repo, state_dir=None):
    return Path(state_dir) if state_dir else Path(repo) / ".steering" / "capture"


def load_state(repo, session_id, state_dir=None):
    p = state_dir_for(repo, state_dir) / _state_name(session_id)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8")), p
        except json.JSONDecodeError:
            return None, p
    return None, p


def write_checkpoint(repo, session_path, session_id=None, state_dir=None):
    """Accumulate per-segment intervention records for a live session.

    Recomputes the capture analysis of the transcript as it stands
    (the transcript grows during the session, so the last segment's
    record is provisional until the session ends) and writes the
    state file under .steering/capture/. Hunks in the state file are
    in session-replay snapshot coordinates and are labelled
    provisional: attach finalizes them against the real commit.
    Returns the state dict.
    """
    repo = Path(repo)
    session_id = session_id or Path(session_path).stem
    analysis = build_segment_records(session_path)
    prior, path = load_state(repo, session_id, state_dir)
    head = git(repo, "rev-parse", "HEAD", check=False).stdout.strip() or None
    state = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "harness": analysis["meta"].get("harness", "claude-code"),
        "base_commit": (prior or {}).get("base_commit", head),
        "updated_at": utcnow_iso(),
        "attached": (prior or {}).get("attached", []),
        "segments": [
            {"turn": r["turn"], "impact_class": r["impact_class"],
             "redirect": r["redirect"],
             "overlap_earlier_lines": r["overlap_earlier_lines"],
             "decisions": r["decisions"], "hunks": r["hunks"],
             "hunks_basis": "session replay snapshots (provisional)",
             "transcript_sha256": r["transcript_sha256"]}
            for r in analysis["records"]],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return state


def attach_pending(repo, session_path, session_id=None, commit="HEAD",
                   state_dir=None, push=True, remote="origin"):
    """Attach the session's not-yet-recorded segments to a commit.

    Recomputes the analysis from the final transcript, attributes
    the target commit's hunks to the pending segments, writes the
    merged record as the commit's steer note, updates the
    checkpoint state, and then (change 1 from the spike) pushes
    ONLY refs/notes/steer to the repo's existing origin, announcing
    that it did so. A push failure is reported in the result, never
    fatal: the record is stored locally and the config transport
    from capture init remains as the fallback. Nothing else is ever
    pushed, no branch, no other ref.
    """
    repo = Path(repo)
    session_id = session_id or Path(session_path).stem
    commit_sha = git(repo, "rev-parse", f"{commit}^{{commit}}").stdout.strip()
    state, state_path = load_state(repo, session_id, state_dir)
    analysis = build_segment_records(session_path)
    hashes = {s["idx"]: s["sha256"] for s in analysis["byte_segments"]}
    # A turn counts as already recorded only when a note in this
    # repo claims it with a matching segment hash AND the note's
    # commit is an ancestor of (or equal to) the target commit. A
    # note left behind on a rewritten-away commit therefore does not
    # suppress re-recording on the rewritten history, and the
    # checkpoint state's bookkeeping is advisory only: the notes
    # themselves are the authority.
    recorded_turns = set()
    for note_sha, rec in load_records(repo).items():
        if not isinstance(rec, dict) or rec.get("_unparseable_note"):
            continue
        if git(repo, "merge-base", "--is-ancestor", note_sha, commit_sha,
               check=False).returncode != 0:
            continue
        for rs in rec.get("segments", []):
            t = rs.get("turn")
            if t in hashes and rs.get("transcript_sha256") == hashes[t]:
                recorded_turns.add(t)
    existing = read_note(repo, commit_sha)
    stale_anchor = None
    if isinstance(existing, dict) and not existing.get("_unparseable_note") \
            and existing.get("commit") not in (None, commit_sha):
        stale_anchor = existing.get("commit")
    pending = [r for r in analysis["records"] if r["turn"] not in recorded_turns]
    result = {"repo": str(repo), "commit": commit_sha,
              "session_id": session_id, "attached_turns": [],
              "reanchored_from": stale_anchor, "push": {"attempted": False}}
    if not pending and stale_anchor is None:
        result["status"] = "nothing-new"
        return result
    if pending:
        # seed the replay from the commit's parent so the replay
        # coordinates align with the commit's diff base
        parents = git(repo, "rev-list", "--parents", "-n", "1",
                      commit_sha).stdout.split()
        seed = None
        if len(parents) > 1:
            seed = sr.SeedIndex(repo, ref=parents[1])
            analysis = build_segment_records(session_path, seed_index=seed)
            pending = [r for r in analysis["records"]
                       if r["turn"] not in recorded_turns]
        attributed = attribute_commit_hunks(
            repo, commit_sha, pending, analysis["replay_final"],
            analysis["removed_texts"])
        for r in pending:
            r["hunks"] = attributed.get(r["turn"], [])
    record = make_record(commit_sha,
                         analysis["meta"].get("harness", "claude-code"),
                         pending)
    written = attach_record(repo, commit_sha, record)
    result["attached_turns"] = [r["turn"] for r in pending]
    result["record_segments"] = len(written["segments"])
    result["status"] = "attached"
    # persist the bookkeeping alongside any checkpoint state
    state = state or {"session_id": session_id,
                      "transcript_path": str(session_path),
                      "harness": analysis["meta"].get("harness", "claude-code"),
                      "base_commit": None, "attached": [], "segments": []}
    state.setdefault("attached", []).append(
        {"commit": commit_sha, "turns": result["attached_turns"],
         "attached_at": utcnow_iso()})
    state["updated_at"] = utcnow_iso()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    # change 1: the driver pushes the notes ref itself, nothing else
    remotes = git(repo, "remote").stdout.split()
    if not push:
        result["push"] = {"attempted": False, "reason": "disabled by --no-push"}
    elif remote not in remotes:
        result["push"] = {"attempted": False,
                          "reason": f"no {remote} remote configured"}
    else:
        r = git(repo, "push", remote, NOTES_REFSPEC, check=False)
        result["push"] = {"attempted": True, "ok": r.returncode == 0,
                          "remote": remote,
                          "detail": (r.stderr or r.stdout).strip().splitlines()[-1]
                          if (r.stderr or r.stdout).strip() else ""}
    return result


def attach_announcements(result):
    """The plain-language lines the attach flow announces, including
    the driver push (change 1 requires the push to be announced,
    never silent)."""
    lines = []
    if result["status"] == "nothing-new":
        lines.append(f"capture: nothing new to attach for session "
                     f"{result['session_id']} (commit {result['commit'][:10]})")
        return lines
    turns = result["attached_turns"]
    lines.append(f"capture: attached steering record for {len(turns)} "
                 f"segment(s) {turns} to commit {result['commit'][:10]} "
                 f"under refs/notes/steer")
    if result.get("reanchored_from"):
        lines.append(f"capture: re-anchored the record that named commit "
                     f"{result['reanchored_from'][:10]} (a history rewrite "
                     f"had copied the note onto this commit)")
    p = result["push"]
    if p.get("attempted") and p.get("ok"):
        lines.append(f"capture: pushed {NOTES_REFSPEC} to {p['remote']} "
                     f"(driver push: the notes ref only, no branches)")
    elif p.get("attempted"):
        lines.append(f"capture: notes push to {p['remote']} FAILED "
                     f"(reported, not fatal): {p.get('detail', '')}. The "
                     f"record is stored locally; the capture init config "
                     f"transport remains as the fallback.")
    else:
        lines.append(f"capture: notes not pushed ({p.get('reason', '')}); "
                     f"the record is stored locally")
    return lines


# ------------------------------------------------------------ verification
def _span_positions(h):
    new_pos = set(range(h["start"], h["start"] + h["lines"])) if h["lines"] else set()
    old_pos = set(range(h["removed_start"],
                        h["removed_start"] + h["removed_lines"])) \
        if h["removed_lines"] else set()
    return new_pos, old_pos


def _first_inconsistent_hunk(recorded_hunks, real_hunks):
    """Span-consistency of recorded hunks against a commit's real diff.

    A recorded hunk is consistent when every new-side position it
    claims appears among the diff's new-side positions for that file,
    and every removed-side position among the diff's removed-side
    positions for that file. This is deliberately a subset check, not
    equality: one commit can carry several segments, hand edits, and
    work from other sessions, so the record never has to exhaust the
    diff (the claimed and total position counts are reported by the
    caller, so incompleteness is visible rather than hidden). Returns
    the first inconsistent recorded hunk, or None.
    """
    new_by_file, old_by_file = {}, {}
    for dh in real_hunks:
        n, o = _span_positions(dh)
        new_by_file.setdefault(dh["file"], set()).update(n)
        old_by_file.setdefault(dh["file"], set()).update(o)
    for rh in recorded_hunks:
        rnew, rold = _span_positions(rh)
        if not rnew <= new_by_file.get(rh["file"], set()):
            return rh
        if not rold <= old_by_file.get(rh["file"], set()):
            return rh
    return None


def _history_ancestors(repo):
    """The commits on the current HEAD history, or an empty set when
    HEAD does not resolve. Records riding on commits outside this
    set are orphans of a history rewrite: they still verify against
    their own commit, but they claim nothing in this history."""
    r = git(repo, "rev-list", "HEAD", check=False)
    if r.returncode != 0:
        return set()
    return set(r.stdout.split())


def _record_order(repo, shas):
    """Noted commits in history order: position on the HEAD history
    first, then position on any ref, then committer time. Committer
    time alone cannot order a fast sequence of commits (one-second
    resolution), so topology leads."""
    pos = {}
    for args in (("rev-list", "--reverse", "HEAD"),
                 ("rev-list", "--reverse", "--all")):
        r = git(repo, *args, check=False)
        if r.returncode == 0:
            for sha in r.stdout.split():
                pos.setdefault(sha, len(pos))
    def key(sha):
        if sha in pos:
            return (0, pos[sha], sha)
        r = git(repo, "show", "-s", "--format=%ct", sha, check=False)
        try:
            return (1, int(r.stdout.strip()), sha)
        except ValueError:
            return (1, 0, sha)
    return sorted(shas, key=key)


def verify_records(repo, session_path=None):
    """Verify every steering record in a repo, at one of two tiers.

    Commit tier (always run): each note parses as a record, its
    anchor names the commit that carries it, no (turn, segment hash)
    pair is claimed by two commits in the current history (an orphan
    on a rewritten-away commit and its rewritten copy claim the same
    segments legitimately), and every recorded hunk is
    span-consistent with the commit's real diff. With no transcript,
    class claims get only the necessary-condition shape checks: a
    segment recorded as procedural must carry no hunks, and a
    segment recorded as reshaping must remove lines in a file an
    earlier recorded segment touched, a condition evaluated only
    where the commit's diff carries removal evidence for the
    segment's files (in a final-state commit whose diff removes
    nothing there, the check is skipped, not passed or failed).

    Transcript tier (when session_path is given): for each record
    that belongs to this session (any segment hash matches), the
    segment hashes are recomputed from the transcript bytes and the
    recorded classes are compared against a full replay of the
    transcript. Records belonging to other sessions are skipped at
    this tier, never failed.

    Returns a dict with per-check entries, pass, fail and skip
    counts, per-commit claimed versus total diff positions, and the
    strongest tier with no failures, stated in the product's exact
    tier wording.
    """
    repo = Path(repo)
    records = load_records(repo)
    checks = []

    def add(commit, segment, check, status, detail=""):
        checks.append({"commit": commit, "segment": segment, "check": check,
                       "status": status, "detail": detail})

    analysis = None
    hashes = {}
    if session_path is not None:
        analysis = build_segment_records(session_path)
        hashes = {s["idx"]: s["sha256"] for s in analysis["byte_segments"]}
    matched = set()
    if session_path is not None:
        for sha, rec in records.items():
            if not isinstance(rec, dict) or rec.get("_unparseable_note"):
                continue
            for rs in rec.get("segments", []):
                t = rs.get("turn")
                if t in hashes and rs.get("transcript_sha256") == hashes[t]:
                    matched.add(sha)
                    break
    claims = {}   # (turn, segment hash) -> commit
    ancestors = _history_ancestors(repo)
    in_history = ancestors if ancestors else set(records)
    touched_files = set()
    commit_stats = []
    for sha in _record_order(repo, list(records)):
        rec = records[sha]
        if not isinstance(rec, dict) or rec.get("_unparseable_note") \
                or rec.get("schema") != RECORD_SCHEMA \
                or not isinstance(rec.get("segments"), list):
            add(sha, None, "record-parse", "fail",
                "the note is not a steering record in the expected format")
            continue
        add(sha, None, "record-parse", "pass")
        if rec.get("commit") == sha:
            add(sha, None, "V1-anchor", "pass")
        else:
            add(sha, None, "V1-anchor", "fail",
                f"the record names commit {str(rec.get('commit'))[:12]} "
                f"but rides on {sha[:12]}")
        real = commit_hunks(repo, sha)
        diff_new = sum(h["lines"] for h in real)
        diff_old = sum(h["removed_lines"] for h in real)
        claimed_new = claimed_old = 0
        for rs in rec["segments"]:
            t = rs.get("turn")
            for h in rs.get("hunks", []):
                n, o = _span_positions(h)
                claimed_new += len(n)
                claimed_old += len(o)
            key = (t, rs.get("transcript_sha256"))
            # Uniqueness binds within the current history: an orphan
            # left on a rewritten-away commit and the copy git moved
            # onto the rewritten commit claim the same segments
            # legitimately, so a collision fails only when both
            # claiming commits are in this history.
            if key in claims and claims[key] != sha \
                    and sha in in_history and claims[key] in in_history:
                add(sha, t, "V1-uniqueness", "fail",
                    f"turn {t} with this segment hash is also claimed "
                    f"by commit {claims[key][:12]}")
            else:
                claims.setdefault(key, sha)
                add(sha, t, "V1-uniqueness", "pass")
            bad = _first_inconsistent_hunk(rs.get("hunks", []), real)
            if bad is None:
                add(sha, t, "V3-hunks-vs-diff", "pass")
            else:
                add(sha, t, "V3-hunks-vs-diff", "fail",
                    f"recorded hunk in {bad['file']} at new line "
                    f"{bad['start']} is not inside this commit's diff")
            if session_path is not None:
                if sha in matched:
                    if hashes.get(t) is not None \
                            and rs.get("transcript_sha256") == hashes[t]:
                        add(sha, t, "V2-segment-hash", "pass")
                    else:
                        add(sha, t, "V2-segment-hash", "fail",
                            "the recorded segment hash does not match "
                            "the transcript bytes for this turn")
                    want = analysis["impact_per"].get(t)
                    if want is None:
                        add(sha, t, "V4-class-vs-replay", "fail",
                            "the turn is not a human segment in this "
                            "transcript")
                    elif rs.get("impact_class") == want["impact_class"] \
                            and rs.get("redirect") == want["redirect"] \
                            and rs.get("overlap_earlier_lines") == \
                            want["overlap_earlier_lines"]:
                        add(sha, t, "V4-class-vs-replay", "pass")
                    else:
                        add(sha, t, "V4-class-vs-replay", "fail",
                            f"recorded class {rs.get('impact_class')} "
                            f"with overlap {rs.get('overlap_earlier_lines')} "
                            f"against a replay that measures "
                            f"{want['impact_class']} with overlap "
                            f"{want['overlap_earlier_lines']}")
                else:
                    add(sha, t, "V2-segment-hash", "skipped",
                        "the record belongs to a different session")
                    add(sha, t, "V4-class-vs-replay", "skipped",
                        "the record belongs to a different session")
            else:
                cls = rs.get("impact_class")
                seg_files = {h["file"] for h in rs.get("hunks", [])}
                diff_removed_files = {h["file"] for h in real
                                      if h["removed_lines"] > 0}
                removal_hunks = [h for h in rs.get("hunks", [])
                                 if h["removed_lines"] > 0]
                if cls == "procedural" and rs.get("hunks"):
                    add(sha, t, "V4-weak-shape", "fail",
                        "recorded as procedural but carries hunks")
                elif cls == "reshaping" and removal_hunks:
                    if any(h["file"] in touched_files for h in removal_hunks):
                        add(sha, t, "V4-weak-shape", "pass")
                    else:
                        add(sha, t, "V4-weak-shape", "fail",
                            "recorded as reshaping but its removed lines "
                            "are in no file an earlier recorded segment "
                            "touched")
                elif cls == "reshaping" and seg_files & diff_removed_files:
                    add(sha, t, "V4-weak-shape", "fail",
                        "recorded as reshaping, and this commit removes "
                        "lines in a file the segment touched, but the "
                        "segment claims no removed lines")
                elif cls == "reshaping":
                    # The commit removes nothing in this segment's
                    # files (the final-state commit shape, where the
                    # rework is not in the diff at all), so the
                    # necessary condition has no evidence to bite on.
                    add(sha, t, "V4-weak-shape", "skipped",
                        "the commit removes no lines in this segment's "
                        "files, so the reshaping shape check does not "
                        "apply")
                else:
                    add(sha, t, "V4-weak-shape", "pass")
                touched_files |= seg_files
        commit_stats.append({"commit": sha,
                             "claimed_new_positions": claimed_new,
                             "diff_new_positions": diff_new,
                             "claimed_removed_positions": claimed_old,
                             "diff_removed_positions": diff_old})
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    skipped = sum(1 for c in checks if c["status"] == "skipped")
    commit_tier = ("record-parse", "V1-anchor", "V1-uniqueness",
                   "V3-hunks-vs-diff", "V4-weak-shape")
    transcript_tier = ("V2-segment-hash", "V4-class-vs-replay")
    commit_fail = any(c["status"] == "fail" and c["check"] in commit_tier
                      for c in checks)
    transcript_fail = any(c["status"] == "fail" and c["check"] in transcript_tier
                          for c in checks)
    transcript_pass = any(c["status"] == "pass" and c["check"] in transcript_tier
                          for c in checks)
    if records and not commit_fail and session_path is not None \
            and transcript_pass and not transcript_fail:
        tier = "verified against the transcript"
    elif records and not commit_fail:
        tier = "verified against the commit"
    else:
        tier = "not verified"
    return {"records": len(records), "session_supplied": session_path is not None,
            "checks": checks, "passed": passed, "failed": failed,
            "skipped": skipped, "commits": commit_stats, "tier": tier}


# ------------------------------------------------------------ receipt integration
CAPTURE_METHOD = (
    "segments are marked captured when a steering record under "
    "refs/notes/steer claims them: the record is anchored to the "
    "commit that carries it and its recorded segment hash equals "
    "the hash of this transcript's segment bytes. Captured segments "
    "are additionally checked against their commit's diff. Every "
    "other segment keeps the standing post-hoc classification and "
    "is counted inferred, or unmeasured when the replay could not "
    "measure its effect.")


def capture_block_zero(segments_total, impact_per, scope=CAPTURE_SCOPE):
    """The capture block when nothing is captured: the coverage split
    still printed in full, with captured at zero."""
    return {
        "method": CAPTURE_METHOD,
        "segments_total": segments_total,
        "captured_segments": 0,
        "inferred_segments": sum(1 for v in impact_per.values()
                                 if v["impact_class"] != "unmeasured"),
        "unmeasured_segments": sum(1 for v in impact_per.values()
                                   if v["impact_class"] == "unmeasured"),
        "commits_with_records": 0,
        "session_match": False,
        "verification": {"tier": "not verified",
                         "against_commit": {"segments_checked": 0,
                                            "segments_passed": 0},
                         "against_transcript": {"segments_checked": 0,
                                                "segments_passed": 0},
                         "failures": []},
        "per_segment": [
            {"segment": idx,
             "origin": "unmeasured" if impact_per[idx]["impact_class"] == "unmeasured"
             else "inferred"}
            for idx in sorted(impact_per)],
        "scope": scope,
    }


def build_capture_block(repo, session_path, impact_per):
    """The capture block for one code receipt.

    Never raises on a missing or not-a-git repo: that reads as the
    zero block. An unexpected analysis error is reported inside the
    block (as capture_error, with the zero counts) rather than
    swallowed or allowed to kill the receipt.
    """
    human = sorted(impact_per)
    block = capture_block_zero(len(human), impact_per)
    try:
        records = load_records(repo)
        if not records:
            return block
        block["commits_with_records"] = len(records)
        ancestors = _history_ancestors(repo)
        byte_segments, _preamble = split_transcript(session_path)
        hashes = {s["idx"]: s["sha256"] for s in byte_segments}
        captured = {}
        failures = []
        claims_on_transcript = 0
        for sha in _record_order(repo, list(records)):
            if ancestors and sha not in ancestors:
                continue  # an orphan of a rewrite claims nothing here
            rec = records[sha]
            if not isinstance(rec, dict) or rec.get("_unparseable_note"):
                failures.append({"segment": None, "commit": sha,
                                   "check": "record-parse",
                                   "detail": "a note under refs/notes/steer "
                                             "is not a steering record"})
                continue
            if rec.get("commit") != sha:
                continue  # an anchor-stale record claims nothing here
            for rs in rec.get("segments", []):
                t = rs.get("turn")
                if t not in impact_per or t not in hashes:
                    continue
                claims_on_transcript += 1
                if rs.get("transcript_sha256") == hashes[t]:
                    captured[t] = (sha, rs)
                else:
                    failures.append({"segment": t, "commit": sha,
                                     "check": "V2-segment-hash",
                                     "detail": "the recorded segment hash "
                                               "does not match this "
                                               "transcript's segment bytes"})
        block["session_match"] = bool(captured)
        commit_passed = 0
        for t in sorted(captured):
            sha, rs = captured[t]
            bad = _first_inconsistent_hunk(rs.get("hunks", []),
                                           commit_hunks(repo, sha))
            if bad is None:
                commit_passed += 1
            else:
                failures.append({"segment": t, "commit": sha,
                                 "check": "V3-hunks-vs-diff",
                                 "detail": f"recorded hunk in {bad['file']} "
                                           f"at new line {bad['start']} is "
                                           f"not inside this commit's diff"})
            want = impact_per[t]
            if rs.get("impact_class") != want["impact_class"] \
                    or rs.get("redirect") != want["redirect"] \
                    or rs.get("overlap_earlier_lines") != \
                    want["overlap_earlier_lines"]:
                failures.append({"segment": t, "commit": sha,
                                 "check": "V4-class-vs-replay",
                                 "detail": f"recorded class "
                                           f"{rs.get('impact_class')} with "
                                           f"overlap "
                                           f"{rs.get('overlap_earlier_lines')} "
                                           f"against this receipt's measured "
                                           f"{want['impact_class']} with "
                                           f"overlap "
                                           f"{want['overlap_earlier_lines']}"})
        block["captured_segments"] = len(captured)
        block["inferred_segments"] = sum(
            1 for idx in human if idx not in captured
            and impact_per[idx]["impact_class"] != "unmeasured")
        block["unmeasured_segments"] = sum(
            1 for idx in human if idx not in captured
            and impact_per[idx]["impact_class"] == "unmeasured")
        # The tier is the strongest statement with no failures, the
        # same rule verify_records applies: class-only failures (the
        # hunks and hashes hold) degrade the block to the commit
        # tier, and anything else leaves it not verified.
        tier = "not verified"
        if captured and not failures:
            tier = "verified against the transcript"
        elif captured and all(f["check"] == "V4-class-vs-replay"
                              for f in failures):
            tier = "verified against the commit"
        block["verification"] = {
            "tier": tier,
            "against_commit": {"segments_checked": len(captured),
                               "segments_passed": commit_passed},
            "against_transcript": {"segments_checked": claims_on_transcript,
                                   "segments_passed": len(captured)},
            "failures": failures,
        }
        block["per_segment"] = [
            {"segment": idx, "origin": "captured", "commit": captured[idx][0],
             "impact_class_recorded": captured[idx][1].get("impact_class")}
            if idx in captured else
            {"segment": idx,
             "origin": "unmeasured" if impact_per[idx]["impact_class"] == "unmeasured"
             else "inferred"}
            for idx in human]
        return block
    except Exception as e:  # reported in the block, never silent
        block["capture_error"] = f"{type(e).__name__}: {e}"
        return block


# ------------------------------------------------------------ notes-only receipt
def _aggregate_impact(seg_records):
    """An impact-shaped aggregate over recorded segments, in record
    order. Classes are the ones recorded at commit time."""
    counts = Counter(r.get("impact_class") for r in seg_records)
    n = len(seg_records)
    reshaping = counts.get("reshaping", 0)
    return {
        "method": ("aggregated from capture-time steering records: the "
                   "classes were measured and recorded at commit time, "
                   "not recomputed here"),
        "procedural_turns": counts.get("procedural", 0),
        "continuation_turns": counts.get("continuation", 0),
        "reshaping_turns": reshaping,
        "unmeasured_segments": counts.get("unmeasured", 0),
        "reshaping_share_pct": round(100 * reshaping / n, 1) if n else None,
        "reshaping_lines": sum(r.get("overlap_earlier_lines", 0)
                               for r in seg_records),
        "redirect_segments": sum(1 for r in seg_records if r.get("redirect")),
    }


def _aggregate_decisions(seg_records):
    """A decisions-shaped aggregate over recorded decision entries.
    Entries carry classes only, so the aggregate is exact: the
    questions and answers themselves were never stored."""
    counts = Counter()
    for rs in seg_records:
        for e in rs.get("decisions", []):
            status = e.get("status")
            if status == "answered":
                for q in e.get("questions", []):
                    counts["decision_points"] += 1
                    if q.get("with_recommendation"):
                        counts["decisions_with_recommendation"] += 1
                    key = {"followed_recommendation": "followed_recommendation",
                           "diverged_to_listed": "diverged_to_listed",
                           "free_text": "free_text_answers"}.get(
                               q.get("class"), "unparseable_answers")
                    counts[key] += 1
            elif status == "rejected":
                counts["rejected_decision_calls"] += 1
            elif status == "errored":
                counts["errored_decision_calls"] += 1
            elif status == "dismissed":
                counts["dismissed_decision_calls"] += 1
            elif status == "input_unparseable":
                counts["input_unparseable_decision_calls"] += 1
    return {
        "method": ("counted from capture-time steering records: each "
                   "answered question contributes its recorded class and "
                   "whether a recommendation was marked, and a rejected "
                   "call contributes one rejected count. The questions "
                   "and answers themselves were never stored."),
        "decision_points": counts["decision_points"],
        "decisions_with_recommendation": counts["decisions_with_recommendation"],
        "followed_recommendation": counts["followed_recommendation"],
        "diverged_to_listed": counts["diverged_to_listed"],
        "free_text_answers": counts["free_text_answers"],
        "rejected_decision_calls": counts["rejected_decision_calls"],
        "coverage": {
            "errored_decision_calls": counts["errored_decision_calls"],
            "dismissed_decision_calls": counts["dismissed_decision_calls"],
            "input_unparseable_decision_calls":
                counts["input_unparseable_decision_calls"],
            "unparseable_answers": counts["unparseable_answers"],
        },
        "scope": ("notes-only: decision outcomes as recorded at commit "
                  "time, verified against the commit at most. The "
                  "followed rate's only denominator is "
                  "decisions_with_recommendation, as on full receipts."),
    }


def _mark_over(seg_records):
    impact = _aggregate_impact(seg_records)
    per_map = {i: {"impact_class": r.get("impact_class"),
                   "redirect": bool(r.get("redirect")),
                   "overlap_earlier_lines": r.get("overlap_earlier_lines", 0)}
               for i, r in enumerate(seg_records)}
    return sr.code_mark(impact, per_map), impact


def notes_only_receipt(repo, label):
    """Change 3: a partial receipt built from steering records alone.

    No transcript is read. Per-commit captured classes, decision
    outcomes, and marks are computed from the records, with the
    records verified at the commit tier. Transcript-derived fields
    are present as null and named in unavailable_fields: unavailable
    rather than zero. Returns (receipt, markdown).
    """
    repo = Path(repo)
    records = load_records(repo)
    verification = verify_records(repo)
    per_commit = []
    all_segments = []
    harness = "claude-code"
    for sha in _record_order(repo, list(records)):
        rec = records[sha]
        if not isinstance(rec, dict) or rec.get("_unparseable_note"):
            per_commit.append({"commit": sha, "record_parseable": False,
                               "segments_recorded": 0, "segments": []})
            continue
        harness = rec.get("harness", harness)
        segs = rec.get("segments", [])
        mark, impact = _mark_over(segs)
        per_commit.append({
            "commit": sha, "record_parseable": True,
            "captured_at": rec.get("captured_at"),
            "harness": rec.get("harness"),
            "segments_recorded": len(segs),
            "impact": impact,
            "mark": mark,
            "mark_scope": "per-commit, over this commit's recorded segments",
            "decisions": _aggregate_decisions(segs),
            "segments": [
                {"turn": rs.get("turn"),
                 "impact_class": rs.get("impact_class"),
                 "redirect": rs.get("redirect"),
                 "overlap_earlier_lines": rs.get("overlap_earlier_lines"),
                 "hunks": rs.get("hunks", []),
                 "decisions": rs.get("decisions", [])}
                for rs in segs],
        })
        all_segments.extend(segs)
    mark_all, impact_all = _mark_over(all_segments)
    receipt = {
        "schema": sr.SCHEMA,
        "label": label, "kind": "code",
        "notes_only": True,
        "harness": harness,
        "validation_scope": NOTES_ONLY_SCOPE,
        "mark": mark_all,
        "mark_scope": "aggregate over recorded segments only",
        "transcript_sha256": None,
        "mechanistic": None,
        "git_join": None,
        "unavailable_fields": ["transcript_sha256", "mechanistic", "git_join"],
        "impact": impact_all,
        "decisions": _aggregate_decisions(all_segments),
        "capture": {
            "record_schema": RECORD_SCHEMA,
            "commits_with_records": len(records),
            "segments_recorded": len(all_segments),
            "verification_tier": verification["tier"],
            "verification": {"checks_passed": verification["passed"],
                             "checks_failed": verification["failed"],
                             "checks_skipped": verification["skipped"],
                             "commits": verification["commits"]},
        },
        "per_commit": per_commit,
        "labels": {
            "semantic_weights": "none — rule-based categories only; no model calls",
            "receipt_nature": "descriptive evidence, not a certified grade",
            "mark_semantics": "the mark names the process shape (how the work was steered), never its quality; it is not a grade",
        },
        "scope": NOTES_ONLY_SCOPE,
    }
    return receipt, render_notes_md(receipt)


def render_notes_md(r):
    cap = r["capture"]
    lines = [f"# STEERING.md — {r['label']} (code, notes-only partial receipt)", "",
             f"_Schema {r['schema']}. Descriptive evidence, not a certified grade. Counts and categories only; no prompt text._",
             f"_Harness: {r.get('harness')}._",
             "_Notes-only partial receipt: built from capture-time steering records "
             "(git notes under refs/notes/steer) alone. No transcript was held or read._",
             f"_Verification tier: {cap['verification_tier']}._"]
    if r.get("mark"):
        lines.append(f"- Steering mark (aggregate over recorded segments): "
                     f"**{r['mark']['category']}**. {r['mark']['basis']}. "
                     "The mark names the process shape, not a grade.")
    im = r["impact"]
    d = r["decisions"]
    dc = d["coverage"]
    lines += [
        f"- Recorded segments: {cap['segments_recorded']} across "
        f"{cap['commits_with_records']} commits carrying steering records.",
        f"- Impact classes (as recorded at commit time): {im['procedural_turns']} procedural, "
        f"{im['continuation_turns']} continuation, {im['reshaping_turns']} reshaping "
        f"({im['reshaping_lines']} earlier lines rewritten), {im['unmeasured_segments']} unmeasured, "
        f"{im['redirect_segments']} redirect.",
        f"- Decisions (as recorded at commit time): {d['decision_points']} answered questions, "
        f"of which {d['followed_recommendation']} followed the marked recommendation "
        f"(marked on {d['decisions_with_recommendation']} questions), {d['diverged_to_listed']} "
        f"chose a different listed option, and {d['free_text_answers']} were answered in free text. "
        f"{d['rejected_decision_calls']} question calls were rejected as posed.",
        f"- Decision coverage: {dc['errored_decision_calls']} errored calls, "
        f"{dc['dismissed_decision_calls']} dismissed calls, "
        f"{dc['input_unparseable_decision_calls']} calls with unparseable recorded input, "
        f"{dc['unparseable_answers']} unparseable answers.",
        "- Unavailable without the transcript (shown as unavailable, not zero): "
        "the transcript hash, the mechanistic counts, and the git join.",
        "", "## Per-commit records", "",
        "| commit | captured at | segments | procedural | continuation | reshaping | unmeasured | mark |",
        "|---|---|---|---|---|---|---|---|"]
    for c in r["per_commit"]:
        if not c["record_parseable"]:
            lines.append(f"| {c['commit'][:12]} | (note is not a steering record) | 0 | | | | | |")
            continue
        ci = c["impact"]
        lines.append(f"| {c['commit'][:12]} | {c['captured_at']} | {c['segments_recorded']} | "
                     f"{ci['procedural_turns']} | {ci['continuation_turns']} | "
                     f"{ci['reshaping_turns']} | {ci['unmeasured_segments']} | "
                     f"{c['mark']['category']} |")
    lines += ["", f"- Scope: {r['scope']}", ""]
    return "\n".join(lines)
