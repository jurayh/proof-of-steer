"""Instance #1: git. v1's doc-mode fetch (git log --follow + git show)
re-expressed as a HistoryProvider. Used by the spike to prove the
contract + join reproduce v1's numbers exactly; v1 itself is untouched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import ArtifactMeta, ArtifactRef, EvidenceEvent, Snapshot


class GitHistoryProvider:
    scheme = "git"

    @staticmethod
    def _split(locator: str) -> tuple[Path, str]:
        repo, rel = locator.split("::", 1)
        return Path(repo), rel

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True).stdout

    def describe(self, ref: ArtifactRef) -> ArtifactMeta:
        repo, rel = self._split(ref.locator)
        # A shallow clone (e.g. --depth 1) hides every revision before the
        # boundary; claiming completeness there is exactly the dishonesty
        # the history_complete field exists to prevent.
        shallow = self._git(repo, "rev-parse",
                            "--is-shallow-repository").strip() == "true"
        return ArtifactMeta(title=rel, kind="document",
                            history_complete=not shallow)

    def snapshots(self, ref: ArtifactRef) -> list[Snapshot]:
        repo, rel = self._split(ref.locator)
        out = self._git(repo, "log", "--follow", "--reverse",
                        "--pretty=format:%H%x09%aI%x09%an", "--", rel)
        snaps = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, ts, author = line.split("\t", 2)
            snaps.append(Snapshot(
                id=sha[:8], timestamp=ts, author=author,
                _fetch=lambda s=sha: self._git(repo, "show", f"{s}:{rel}")))
        return snaps

    def evidence_events(self, ref: ArtifactRef) -> list[EvidenceEvent]:
        return []  # git revision history carries no rejection evidence (the blind spot)
