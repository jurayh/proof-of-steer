"""Provider registry: one module plus one registration line per source.

Adopted into v1 in the v1.4 build from the gdocs spike (see
../../gdocs-spike/PROVIDER-DESIGN.md for the contract's rationale).
The registry is defined before the provider modules are imported so a
provider module may import the base contract without a cycle; modules
never register themselves, the registration lines below do.
"""
from __future__ import annotations

from .base import (ArtifactMeta, ArtifactRef, EvidenceEvent, HistoryProvider,
                   ProviderUnavailable, Snapshot)

PROVIDERS: dict[str, type] = {}


def register(cls):
    PROVIDERS[cls.scheme] = cls
    return cls


def get_provider(scheme: str) -> HistoryProvider:
    if scheme not in PROVIDERS:
        raise KeyError(f"unknown provider {scheme!r}; registered: {sorted(PROVIDERS)}")
    return PROVIDERS[scheme]()


from .git_provider import GitHistoryProvider      # noqa: E402
from .gdrive_doc import GDriveDocProvider         # noqa: E402
from .folder import FolderHistoryProvider         # noqa: E402

register(GitHistoryProvider)     # instance #1: git doc mode, on the contract
register(GDriveDocProvider)      # instance #2: Google Docs via Drive revisions
register(FolderHistoryProvider)  # instance #3: a folder of versioned files


__all__ = ["ArtifactMeta", "ArtifactRef", "EvidenceEvent", "HistoryProvider",
           "ProviderUnavailable", "Snapshot", "PROVIDERS", "register",
           "get_provider"]
