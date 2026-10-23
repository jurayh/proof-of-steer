"""Instance #3: a folder of versioned text files.

Scheme: "folder". The artifact is a directory of versioned text/markdown
files (the way people actually keep drafts when no platform tracks them:
`notes.v1.md`, `notes.v2.md`, `notes.v3.md`). Snapshots are the files,
oldest first. Adopted into v1 in the v1.4 build from the worked example
in ../../extensibility/examples/filesystem_provider.py; the demo there
(58.3% overall on examples/demo_data) is a regression gate for this copy.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .base import ArtifactMeta, ArtifactRef, EvidenceEvent, Snapshot

VERSION_RE = re.compile(r"(?:\.v|[-_]v)(\d+)$")
TRAILING_NUM_RE = re.compile(r"(\d+)$")
TEXT_SUFFIXES = {".md", ".txt", ".markdown"}


def _version_key(p: Path) -> tuple[int, str]:
    """Sort key: explicit version number first, filename as tiebreak."""
    stem = p.stem
    m = VERSION_RE.search(stem) or TRAILING_NUM_RE.search(stem)
    return (int(m.group(1)) if m else 0, p.name)


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


class FolderHistoryProvider:
    """HistoryProvider over a directory of versioned text files.

    Locator: the directory path. Every *.md / *.txt / *.markdown file
    directly in the directory is one snapshot of the same artifact,
    ordered by the version number in its name (`.vN`, `-vN`, `_vN`, or
    trailing digits), then by filename.
    """

    scheme = "folder"

    @staticmethod
    def _files(ref: ArtifactRef) -> list[Path]:
        d = Path(ref.locator)
        if not d.is_dir():
            return []
        files = [p for p in d.iterdir()
                 if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]
        return sorted(files, key=_version_key)

    def describe(self, ref: ArtifactRef) -> ArtifactMeta:
        files = self._files(ref)
        title = Path(ref.locator).name or ref.locator
        if files:
            stems = [VERSION_RE.sub("", p.stem) for p in files]
            if len(set(stems)) == 1:
                title = stems[0]
        mtimes = [p.stat().st_mtime for p in files]
        return ArtifactMeta(
            title=title, kind="document",
            created=_iso(min(mtimes)) if mtimes else None,
            modified=_iso(max(mtimes)) if mtimes else None,
            # The directory is the entire source of record this provider
            # reads: nothing exists upstream of it that could be
            # truncated away, so the promise git makes applies here too.
            history_complete=True)

    def snapshots(self, ref: ArtifactRef) -> list[Snapshot]:
        snaps = []
        for p in self._files(ref):
            text = p.read_text(encoding="utf-8", errors="replace")
            snaps.append(Snapshot(
                id=p.stem,
                timestamp=_iso(p.stat().st_mtime),
                author=None,  # a folder knows no authors
                size_lines=sum(1 for l in text.splitlines() if l.strip()),
                _text=text))
        return snaps  # [] for an empty folder: honest, never fabricated

    def evidence_events(self, ref: ArtifactRef) -> list[EvidenceEvent]:
        return []  # a folder carries no platform events (the blind spot)
