"""The HistoryProvider contract (see ../PROVIDER-DESIGN.md).

A provider answers one question: given an artifact reference, what are
its snapshots, oldest first? The join consumes snapshots and never
learns the source's name. Stdlib only, matching v1's style.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, ClassVar, Protocol


@dataclass
class ArtifactRef:
    scheme: str        # "git", "gdrive-doc", ...
    locator: str       # scheme-specific: "repo_dir::rel/path" or a file id


@dataclass
class Snapshot:
    id: str                        # provider-native id (commit sha, revision id)
    timestamp: str | None          # ISO 8601, UTC
    author: str | None             # display name if the source knows it
    size_lines: int | None = None  # non-blank lines, if cheap pre-fetch
    _text: str | None = None
    _fetch: Callable[[], str] | None = None

    def content(self) -> str:
        if self._text is None:
            if self._fetch is None:
                raise ValueError(f"snapshot {self.id} has neither text nor a fetch handle")
            self._text = self._fetch()
            self._fetch = None
        return self._text


@dataclass
class ArtifactMeta:
    title: str
    kind: str                      # "document", "slides", ...
    created: str | None = None
    modified: str | None = None
    history_complete: bool | None = None  # False = source admits truncation


@dataclass
class EvidenceEvent:
    kind: str          # "suggestion_accepted", "comment_resolved", ...
    timestamp: str | None = None
    actor: str | None = None
    detail: dict = field(default_factory=dict)  # counts/sizes only, never body text


class ProviderUnavailable(RuntimeError):
    """The provider cannot run at all (auth, connectivity). Carries the
    underlying tool's own words so the failure is evidence, not a guess."""


class HistoryProvider(Protocol):
    scheme: ClassVar[str]

    def describe(self, ref: ArtifactRef) -> ArtifactMeta: ...
    def snapshots(self, ref: ArtifactRef) -> list[Snapshot]: ...   # oldest first
    def evidence_events(self, ref: ArtifactRef) -> list[EvidenceEvent]:
        return []
