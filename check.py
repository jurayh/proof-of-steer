"""Maintainer-side receipt-vs-diff checker. Stdlib only.

A contributor attaches a steering receipt to a PR. The maintainer runs
this tool to verify the receipt's artifact-side claims against the PR
diff, without ever seeing the transcript. The transcript is never an
input here: there is no argument or flag that accepts one.

The central honesty constraint, stated on every report: a diff alone
cannot verify steering. It contains no segments, no turn counts, no
post-first share, no steering mark, no decisions, and no impact
classes. This tool verifies only artifact-side consistency (files and
line counts) and lists everything it did not check, with the reason,
on every run. It never prints an overall grade and never uses the word
"certified".

Comparable quantities: receipts count final non-blank lines, diffs
count added lines including blanks. The checker counts added
non-blank lines itself from the diff content and compares like with
like. Deleted lines are counted the same way and reported per file.

Verdict vocabulary per claim: verified, consistent, mismatch,
unverifiable. Diff files outside a receipt's listed files are
reported as unlisted, never hidden and never counted as mismatch
unless the receipt's file list is complete (see check_spec, shipped
as check-spec.md beside this module's home directory).
"""

import json
import re
import sys
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class CheckError(Exception):
    """Input error: unreadable files, unparseable receipt, no diff."""


def _is_blank(content):
    return content.strip() == ""


def _n(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _clean_path(raw):
    path = raw.strip()
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


class DiffFile:
    def __init__(self, path):
        self.path = path
        self.status = "modified"  # modified | added | deleted | renamed | binary
        self.renamed_from = None
        self.added = []  # added line contents (without the leading +)
        self.added_nonblank = 0
        self.deleted_nonblank = 0
        self.complete = True

    def finish_line(self, kind, content):
        if kind == "+":
            self.added.append(content)
            if not _is_blank(content):
                self.added_nonblank += 1
        elif kind == "-":
            if not _is_blank(content):
                self.deleted_nonblank += 1


class Diff:
    def __init__(self):
        self.files = []
        self.truncated = False
        self.truncated_file = None


def parse_diff(text):
    """Parse a unified diff. Never raises on malformed input: a diff
    that ends mid-hunk is reported truncated, not rejected."""
    diff = Diff()
    if not text.strip():
        return diff
    lines = text.splitlines()
    i = 0
    current = None
    old_path = None
    new_path = None
    rename_from = None
    hunk_old_left = 0
    hunk_new_left = 0
    in_hunk = False

    def flush():
        nonlocal current, old_path, new_path, rename_from
        if current is not None:
            diff.files.append(current)
        current = None
        old_path = None
        new_path = None
        rename_from = None

    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            if in_hunk and (hunk_old_left > 0 or hunk_new_left > 0):
                diff.truncated = True
                diff.truncated_file = current.path if current else None
                if current is not None:
                    current.complete = False
                flush()
                in_hunk = False
                return diff
            flush()
            current = DiffFile("")
            in_hunk = False
            i += 1
            continue
        if current is None:
            if line.startswith("--- "):
                old_path = line[4:]
                # A header-less patch: start a file on the --- line.
                current = DiffFile("")
                in_hunk = False
            i += 1
            continue
        if not in_hunk:
            if line.startswith("--- "):
                old_path = line[4:]
            elif line.startswith("+++ "):
                new_path = line[4:]
                if new_path.strip() == "/dev/null":
                    current.status = "deleted"
                    current.path = _clean_path(old_path) if old_path else ""
                elif old_path is not None and old_path.strip() == "/dev/null":
                    current.status = "added"
                    current.path = _clean_path(new_path)
                else:
                    current.path = _clean_path(new_path)
            elif line.startswith("rename from "):
                rename_from = line[len("rename from "):].strip()
            elif line.startswith("rename to "):
                current.status = "renamed"
                current.renamed_from = rename_from
                current.path = line[len("rename to "):].strip()
            elif line.startswith("Binary files "):
                current.status = "binary"
                m = re.match(r"Binary files a/(.*) and b/(.*) differ", line)
                if m:
                    current.path = m.group(2)
                elif new_path:
                    current.path = _clean_path(new_path)
                flush()
            elif line.startswith("@@ "):
                m = HUNK_RE.match(line)
                if m:
                    old_count = int(m.group(2)) if m.group(2) is not None else 1
                    new_count = int(m.group(4)) if m.group(4) is not None else 1
                    hunk_old_left = old_count
                    hunk_new_left = new_count
                    in_hunk = True
                    if not current.path:
                        if new_path:
                            current.path = _clean_path(new_path)
                        elif rename_from:
                            current.path = rename_from
                else:
                    # Unparseable hunk header: the file cannot be trusted.
                    current.complete = False
                    diff.truncated = True
                    diff.truncated_file = current.path or None
                    flush()
                    in_hunk = False
                    return diff
            # Other header lines (index, mode, similarity) are ignored.
            i += 1
            continue
        # In a hunk.
        if line.startswith("diff --git ") or line.startswith("@@ "):
            if hunk_old_left > 0 or hunk_new_left > 0:
                diff.truncated = True
                diff.truncated_file = current.path if current else None
                if current is not None:
                    current.complete = False
                flush()
                in_hunk = False
                return diff
            if line.startswith("@@ "):
                m = HUNK_RE.match(line)
                if m:
                    hunk_old_left = int(m.group(2)) if m.group(2) is not None else 1
                    hunk_new_left = int(m.group(4)) if m.group(4) is not None else 1
                else:
                    current.complete = False
                    diff.truncated = True
                    diff.truncated_file = current.path or None
                    flush()
                    in_hunk = False
                    return diff
            else:
                # New file header after a satisfied hunk: reprocess it.
                flush()
                in_hunk = False
                continue
            i += 1
            continue
        if line.startswith("\\"):
            i += 1
            continue
        if line.startswith("+"):
            current.finish_line("+", line[1:])
            hunk_new_left -= 1
        elif line.startswith("-"):
            current.finish_line("-", line[1:])
            hunk_old_left -= 1
        elif line.startswith(" "):
            hunk_old_left -= 1
            hunk_new_left -= 1
        else:
            # A line that is none of the above inside a hunk: the diff
            # is malformed from here on.
            diff.truncated = True
            diff.truncated_file = current.path if current else None
            current.complete = False
            flush()
            in_hunk = False
            return diff
        i += 1
        if hunk_old_left == 0 and hunk_new_left == 0:
            in_hunk = False
    if in_hunk and (hunk_old_left > 0 or hunk_new_left > 0):
        diff.truncated = True
        diff.truncated_file = current.path if current else None
        if current is not None:
            current.complete = False
    flush()
    return diff


def _session_lines(final_lines, preexisting_share_pct):
    """Lines the receipt attributes to the session, from the stated
    pre-existing share, rounded to whole lines."""
    pre = round(final_lines * preexisting_share_pct / 100.0)
    return final_lines - pre


def _check_code(receipt, diff):
    gj = receipt.get("git_join") or {}
    files_at_head = gj.get("files_at_head")
    total_lines = gj.get("final_nonblank_lines")
    per_file = gj.get("per_file") or []
    headline_pre = (gj.get("headline_fields") or {}).get("preexisting_share_pct")
    listed = {f["file"]: f for f in per_file}
    complete_list = files_at_head is not None and len(per_file) == files_at_head
    diff_by_path = {f.path: f for f in diff.files if f.path}
    checks = []
    unlisted = []
    counts = {"verified": 0, "consistent": 0, "mismatch": 0,
              "unverifiable": 0, "unlisted": 0}

    def note(verdict):
        counts[verdict] += 1

    for path, entry in listed.items():
        final = entry["final_lines"]
        pre = entry.get("preexisting_share_pct", 0.0)
        session = _session_lines(final, pre)
        d = diff_by_path.get(path)
        if d is None:
            if diff.truncated:
                checks.append({"file": path, "verdict": "unverifiable",
                               "receipt_lines": final, "diff_added_nonblank": None,
                               "diff_deleted_nonblank": None,
                               "detail": "diff truncated before this file could be parsed"})
                note("unverifiable")
            elif session > 0:
                checks.append({"file": path, "verdict": "mismatch",
                               "receipt_lines": final, "diff_added_nonblank": None,
                               "diff_deleted_nonblank": None,
                               "detail": ("receipt claims %d session lines in this file, "
                                          "but the diff never touches it") % session})
                note("mismatch")
            else:
                checks.append({"file": path, "verdict": "consistent",
                               "receipt_lines": final, "diff_added_nonblank": None,
                               "diff_deleted_nonblank": None,
                               "detail": "100 percent pre-existing, expected absent from the diff"})
                note("consistent")
            continue
        if d.status == "binary":
            checks.append({"file": path, "verdict": "unverifiable",
                           "receipt_lines": final, "diff_added_nonblank": None,
                           "diff_deleted_nonblank": None,
                           "detail": "binary file, the diff carries no line counts"})
            note("unverifiable")
            continue
        if not d.complete:
            checks.append({"file": path, "verdict": "unverifiable",
                           "receipt_lines": final, "diff_added_nonblank": None,
                           "diff_deleted_nonblank": None,
                           "detail": "diff truncated in this file's hunks"})
            note("unverifiable")
            continue
        if d.status == "renamed" and d.added_nonblank == 0 and d.deleted_nonblank == 0:
            checks.append({"file": path, "verdict": "unverifiable",
                           "receipt_lines": final, "diff_added_nonblank": 0,
                           "diff_deleted_nonblank": 0,
                           "detail": "rename only, content moved rather than added"})
            note("unverifiable")
            continue
        base = {"file": path, "receipt_lines": final,
                "diff_added_nonblank": d.added_nonblank,
                "diff_deleted_nonblank": d.deleted_nonblank}
        if d.status == "added" and d.deleted_nonblank > 0:
            checks.append({**base, "verdict": "mismatch",
                           "detail": "created file with deleted lines, which a creation cannot have"})
            note("mismatch")
            continue
        if pre == 0.0:
            if d.added_nonblank == final:
                checks.append({**base, "verdict": "verified",
                               "detail": "added non-blank lines equal final lines"})
                note("verified")
            elif d.added_nonblank < final:
                checks.append({**base, "verdict": "mismatch",
                               "detail": ("diff is missing %s the receipt claims")
                                          % _n(final - d.added_nonblank, "line")})
                note("mismatch")
            else:
                checks.append({**base, "verdict": "mismatch",
                               "detail": ("diff has %s the receipt does not account for")
                                          % _n(d.added_nonblank - final, "line")})
                note("mismatch")
        else:
            if d.added_nonblank > final:
                checks.append({**base, "verdict": "mismatch",
                               "detail": ("diff added more non-blank lines than the file "
                                          "holds in total")})
                note("mismatch")
            else:
                implied = final - d.added_nonblank
                checks.append({**base, "verdict": "consistent",
                               "detail": ("added lines fit inside final lines, implying %d "
                                          "surviving pre-existing lines; the diff base is "
                                          "unknown, so this is consistency, not proof") % implied})
                note("consistent")

    for path, d in diff_by_path.items():
        if path in listed:
            continue
        if complete_list:
            checks.append({"file": path, "verdict": "mismatch",
                           "receipt_lines": None,
                           "diff_added_nonblank": d.added_nonblank,
                           "diff_deleted_nonblank": d.deleted_nonblank,
                           "detail": "diff changes a file the receipt does not list"})
            note("mismatch")
        else:
            unlisted.append({"file": path, "added_nonblank": d.added_nonblank,
                             "deleted_nonblank": d.deleted_nonblank})
            counts["unlisted"] += 1

    # Totals, over all complete diff files. A truncated diff or a
    # binary file makes totals a lower bound, never an equality.
    total_added = sum(d.added_nonblank for d in diff.files if d.complete)
    any_binary = any(d.status == "binary" for d in diff.files)
    totals = {"receipt_lines": total_lines, "diff_added_nonblank": total_added}
    if diff.truncated:
        totals.update({"verdict": "unverifiable",
                       "detail": "diff truncated, totals are a lower bound only"})
        counts["unverifiable"] += 1
    elif total_added > total_lines:
        totals.update({"verdict": "mismatch",
                       "detail": ("diff added %s more than the "
                                  "receipt total") % _n(total_added - total_lines, "non-blank line")})
        counts["mismatch"] += 1
    elif any_binary:
        totals.update({"verdict": "unverifiable",
                       "detail": "a binary file in the diff carries uncounted lines"})
        counts["unverifiable"] += 1
    elif headline_pre == 0.0:
        if total_added == total_lines:
            totals.update({"verdict": "verified",
                           "detail": "total added non-blank lines equal the receipt total"})
            counts["verified"] += 1
        else:
            totals.update({"verdict": "mismatch",
                           "detail": ("diff total is %s short of the receipt total")
                                      % _n(total_lines - total_added, "line")})
            counts["mismatch"] += 1
    else:
        totals.update({"verdict": "consistent",
                       "detail": "total added lines fit inside the receipt total"})
        counts["consistent"] += 1

    return {"file_checks": checks, "unlisted_diff_files": unlisted,
            "totals": totals, "counts": counts,
            "file_list_complete": complete_list}


def _check_doc(receipt, diff):
    source = receipt.get("source") or ""
    basename = source.split("::")[-1].strip()
    total_lines = receipt.get("final_nonblank_lines")
    floor_pct = receipt.get("overall_pct_unchanged_from_first_version")
    history_complete = receipt.get("history_complete")
    checks = []
    counts = {"verified": 0, "consistent": 0, "mismatch": 0,
              "unverifiable": 0, "unlisted": 0}

    named = [f for f in diff.files if f.path and Path(f.path).name == basename]
    if named:
        target = named[0]
    elif len(diff.files) == 1:
        target = diff.files[0]
    else:
        target = None
    if target is None:
        checks.append({"file": basename, "verdict": "mismatch",
                       "receipt_lines": total_lines, "diff_added_nonblank": None,
                       "diff_deleted_nonblank": None,
                       "detail": "the receipt's document is not in the diff"})
        counts["mismatch"] += 1
        totals = {"receipt_lines": total_lines, "diff_added_nonblank": None,
                  "verdict": "mismatch",
                  "detail": "the receipt's document is not in the diff"}
        counts["mismatch"] += 1
        return {"file_checks": checks, "unlisted_diff_files": [],
                "totals": totals, "counts": counts, "file_list_complete": True}
    if target.status == "binary" or not target.complete:
        reason = ("binary file, the diff carries no line counts"
                  if target.status == "binary" else "diff truncated in this file's hunks")
        checks.append({"file": target.path, "verdict": "unverifiable",
                       "receipt_lines": total_lines, "diff_added_nonblank": None,
                       "diff_deleted_nonblank": None, "detail": reason})
        counts["unverifiable"] += 1
        totals = {"receipt_lines": total_lines, "diff_added_nonblank": None,
                  "verdict": "unverifiable", "detail": reason}
        counts["unverifiable"] += 1
        return {"file_checks": checks, "unlisted_diff_files": [],
                "totals": totals, "counts": counts, "file_list_complete": True}
    added = target.added_nonblank
    if added > total_lines:
        checks.append({"file": target.path, "verdict": "mismatch",
                       "receipt_lines": total_lines, "diff_added_nonblank": added,
                       "diff_deleted_nonblank": target.deleted_nonblank,
                       "detail": "diff added more non-blank lines than the document holds"})
        counts["mismatch"] += 1
        totals = {"receipt_lines": total_lines, "diff_added_nonblank": added,
                  "verdict": "mismatch",
                  "detail": "diff added more non-blank lines than the document holds"}
        counts["mismatch"] += 1
        return {"file_checks": checks, "unlisted_diff_files": [],
                "totals": totals, "counts": counts, "file_list_complete": True}
    implied = total_lines - added
    if history_complete and floor_pct is not None:
        floor_lines = floor_pct / 100.0 * total_lines
        if implied + 1 < floor_lines:
            detail = ("implied surviving lines %d fall below the receipt floor "
                      "of %.1f percent, so the diff added more than the floor allows"
                      ) % (implied, floor_pct)
            checks.append({"file": target.path, "verdict": "mismatch",
                           "receipt_lines": total_lines, "diff_added_nonblank": added,
                           "diff_deleted_nonblank": target.deleted_nonblank,
                           "detail": detail})
            counts["mismatch"] += 1
            totals = {"receipt_lines": total_lines, "diff_added_nonblank": added,
                      "verdict": "mismatch", "detail": detail}
            counts["mismatch"] += 1
            return {"file_checks": checks, "unlisted_diff_files": [],
                    "totals": totals, "counts": counts, "file_list_complete": True}
        detail = ("implied surviving lines %d sit at or above the receipt floor "
                  "of %.1f percent") % (implied, floor_pct)
    elif not history_complete:
        detail = ("history truncated at the first available revision, so the "
                  "floor is relative to that baseline and no floor check runs")
    else:
        detail = "added lines fit inside final lines"
    checks.append({"file": target.path, "verdict": "consistent",
                   "receipt_lines": total_lines, "diff_added_nonblank": added,
                   "diff_deleted_nonblank": target.deleted_nonblank,
                   "detail": detail})
    counts["consistent"] += 1
    totals = {"receipt_lines": total_lines, "diff_added_nonblank": added,
              "verdict": "consistent", "detail": detail}
    counts["consistent"] += 1
    return {"file_checks": checks, "unlisted_diff_files": [],
            "totals": totals, "counts": counts, "file_list_complete": True}


def _check_capture(receipt, repo):
    cap = receipt.get("capture")
    if not cap:
        return None
    section = {
        "captured_segments": cap.get("captured_segments"),
        "inferred_segments": cap.get("inferred_segments"),
        "unmeasured_segments": cap.get("unmeasured_segments"),
        "commits_with_records": cap.get("commits_with_records"),
    }
    if repo is None:
        section.update({
            "verdict": "unverifiable",
            "detail": ("commit hashes and git notes are not in a diff file, "
                       "so commit-anchored capture claims cannot be checked "
                       "from the diff alone; pass --repo to verify them "
                       "against the commit")})
        return section
    try:
        import capture as _capture
        result = _capture.verify_records(repo)
    except Exception as exc:  # unreadable repo, no notes, git failure
        section.update({"verdict": "unverifiable",
                        "detail": "capture verification could not run: %s" % exc})
        return section
    section.update({
        "tier": result.get("tier"),
        "passed": result.get("passed"),
        "failed": result.get("failed"),
        "skipped": result.get("skipped"),
    })
    if result.get("failed"):
        failures = [c for c in result.get("checks", []) if c.get("status") == "fail"]
        section.update({
            "verdict": "mismatch",
            "detail": "%d commit-tier check(s) failed" % result["failed"],
            "failures": failures[:10],
        })
    elif result.get("tier") == "verified against the commit":
        section.update({"verdict": "verified",
                        "detail": "recorded hunks check out against their commit diffs"})
    else:
        section.update({"verdict": "unverifiable",
                        "detail": "no records verified at the commit tier: %s" % result.get("tier")})
    return section


def check_receipt(receipt, diff_text, repo=None):
    """Run every artifact-side check. Returns the report dict."""
    diff = parse_diff(diff_text)
    kind = receipt.get("kind")
    report = {
        "receipt": {"label": receipt.get("label"), "kind": kind,
                    "schema": receipt.get("schema")},
        "diff": {"files": len(diff.files),
                 "integrity": "truncated" if diff.truncated else "complete",
                 "truncated_file": diff.truncated_file},
        "not_checked": [],
    }
    if receipt.get("notes_only") or (kind == "code" and "git_join" not in receipt):
        report.update({"file_checks": [], "unlisted_diff_files": [],
                       "totals": {"receipt_lines": None, "diff_added_nonblank": None,
                                  "verdict": "unverifiable",
                                  "detail": "notes-only receipt carries no artifact file list"},
                       "counts": {"verified": 0, "consistent": 0, "mismatch": 0,
                                  "unverifiable": 0, "unlisted": 0},
                       "file_list_complete": False})
        report["not_checked"] = [
            {"claim": "artifact files and line counts",
             "reason": "notes-only receipt carries no artifact file list"},
        ]
    elif kind == "code":
        report.update(_check_code(receipt, diff))
    elif kind == "document":
        report.update(_check_doc(receipt, diff))
    else:
        raise CheckError("unsupported receipt kind: %r" % (kind,))
    report["not_checked"].extend([
        {"claim": "steering mark",
         "reason": "a diff carries no segment provenance"},
        {"claim": "post-first share",
         "reason": "a diff carries no segment provenance"},
        {"claim": "turn counts",
         "reason": "a diff carries no segments"},
        {"claim": "impact classes",
         "reason": "a diff carries no segment provenance"},
        {"claim": "decisions",
         "reason": "a diff carries no decision calls"},
    ])
    if kind == "document":
        report["not_checked"].append(
            {"claim": "per-section attribution",
             "reason": "diff hunks do not map to document sections"})
    if kind == "code" and not report.get("file_list_complete"):
        report["not_checked"].append(
            {"claim": "per-file counts for files beyond the receipt's listed files",
             "reason": "the receipt lists only its largest files, so the rest "
                        "are constrained by the totals check, not per file"})
    capture_section = _check_capture(receipt, repo)
    report["capture"] = capture_section
    if capture_section is not None and repo is None:
        report["not_checked"].append(
            {"claim": "capture commit claims",
             "reason": "commit hashes and git notes are not in a diff file"})
    counts = report["counts"]
    checked = counts["verified"] + counts["consistent"]
    if counts["mismatch"] or diff.truncated or checked == 0:
        exit_code = 1
    else:
        exit_code = 0
    if capture_section is not None and capture_section.get("verdict") == "mismatch":
        exit_code = 1
    report["counts"] = counts
    report["exit_code"] = exit_code
    return report


def render_human(report):
    """Human summary on stdout. No overall grade, ever."""
    out = []
    r = report["receipt"]
    out.append("Check: %s (%s)" % (r["label"], r["kind"]))
    out.append("Diff: %d files, %s%s" % (
        report["diff"]["files"], report["diff"]["integrity"],
        (" (cut in %s)" % report["diff"]["truncated_file"])
        if report["diff"]["truncated_file"] else ""))
    for c in report["file_checks"]:
        added = ("-" if c["diff_added_nonblank"] is None
                 else str(c["diff_added_nonblank"]))
        out.append("[%s] %s: receipt %s lines, diff added %s non-blank. %s" % (
            c["verdict"], c["file"], c["receipt_lines"], added, c["detail"]))
    for u in report["unlisted_diff_files"]:
        out.append("[unlisted] %s: %d added non-blank lines, not among the "
                   "receipt's listed files; constrained by the totals check only."
                   % (u["file"], u["added_nonblank"]))
    t = report["totals"]
    out.append("Totals [%s]: receipt %s lines, diff added %s non-blank. %s" % (
        t["verdict"], t["receipt_lines"],
        "-" if t["diff_added_nonblank"] is None else t["diff_added_nonblank"],
        t["detail"]))
    cap = report.get("capture")
    if cap is not None:
        out.append("Capture [%s]: %s captured, %s inferred, %s unmeasured, "
                   "%s commits with records. %s" % (
                       cap["verdict"], cap["captured_segments"],
                       cap["inferred_segments"], cap["unmeasured_segments"],
                       cap["commits_with_records"], cap["detail"]))
    out.append("NOT CHECKED (a diff cannot verify these):")
    for n in report["not_checked"]:
        out.append("  - %s: %s" % (n["claim"], n["reason"]))
    c = report["counts"]
    out.append("Counts: verified %d, consistent %d, mismatch %d, "
               "unverifiable %d, unlisted %d" % (
                   c["verified"], c["consistent"], c["mismatch"],
                   c["unverifiable"], c["unlisted"]))
    return "\n".join(out) + "\n"


def run_check(receipt_path, diff_path, repo=None, json_out=None):
    """CLI entry point. Returns the process exit code."""
    try:
        receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("check: cannot read receipt: %s" % exc, file=sys.stderr)
        return 2
    try:
        diff_text = Path(diff_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("check: cannot read diff: %s" % exc, file=sys.stderr)
        return 2
    if not isinstance(receipt, dict) or "kind" not in receipt:
        print("check: not a steering receipt (no kind field)", file=sys.stderr)
        return 2
    try:
        report = check_receipt(receipt, diff_text, repo=repo)
    except CheckError as exc:
        print("check: %s" % exc, file=sys.stderr)
        return 2
    print(render_human(report), end="")
    if json_out:
        Path(json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report["exit_code"]
