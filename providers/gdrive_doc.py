"""Instance #2: Google Docs via the Drive API, reached through the
connector CLI (/opt/hatch/bin/hatch_gws_cli), the sanctioned auth path.

Read-only: files list/get, revisions list/get. No writes, no sharing
changes. Content per revision comes from `revisions get` with
alt=media written to a temp file (the CLI supports -o for binary
responses); the metadata response's exportLinks["text/plain"] is
recorded per revision as the documented fallback.

If Drive is not connected, every entry point raises ProviderUnavailable
carrying the CLI's own error text, so a blocked run reports evidence
instead of failing obscurely.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .base import (ArtifactMeta, ArtifactRef, EvidenceEvent,
                   ProviderUnavailable, Snapshot)

GWS = "/opt/hatch/bin/hatch_gws_cli"
DOC_MIME = "application/vnd.google-apps.document"
SLIDES_MIME = "application/vnd.google-apps.presentation"


class GwsError(RuntimeError):
    pass


def _gws(*args: str, output: Path | None = None) -> str:
    cmd = [GWS, *args]
    if output is not None:
        cmd += ["-o", str(output)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise GwsError((r.stderr or r.stdout).strip()[:500])
    return r.stdout


def _gws_json(*args: str) -> dict:
    return json.loads(_gws(*args))


def preflight(transport=None) -> dict:
    """Return the parsed `drive status`; raise ProviderUnavailable if
    the connector is not connected. `transport` is the fixture seam:
    a callable with _gws's signature; None means the real CLI."""
    run = transport if transport is not None else _gws
    try:
        st = json.loads(run("drive", "status"))
    except Exception as e:
        raise ProviderUnavailable(f"drive status failed: {e}")
    if st.get("status") != "connected":
        # Capture the live failure as it presents on a real call, too.
        try:
            run("drive", "files", "list", "--params", '{"pageSize":1}')
            live = ""
        except Exception as e:
            live = f" Live probe (files list) error: {e}"
        raise ProviderUnavailable(
            f"Google Drive connector is not connected "
            f"(status={st.get('status')!r}, reason={st.get('reason')!r}).{live} "
            f"Connecting is the user's step via the connector's connect link; "
            f"this provider does not work around it.")
    return st


class GDriveDocProvider:
    scheme = "gdrive-doc"
    mime = DOC_MIME
    kind = "document"

    def __init__(self, transport=None):
        # Transport seam: every API call goes through this callable,
        # which has _gws's signature (*args, output=None) -> str.
        # None (the default everywhere, including the registry) means
        # the real connector CLI. Tests pass a recorded/fake transport
        # (see fixtures/fake_drive.py) and the provider logic runs
        # unmodified against it.
        self._transport = transport if transport is not None else _gws

    def _json(self, *args: str) -> dict:
        return json.loads(self._transport(*args))

    # ---- discovery + census (metadata only; no content fetched) ----
    def discover(self, page_size: int = 100) -> list[dict]:
        """List the user's Google Docs (id, title, timestamps)."""
        preflight(self._transport)
        q = f"mimeType='{self.mime}' and trashed=false"
        fields = "files(id,name,mimeType,createdTime,modifiedTime)"
        data = self._json("drive", "files", "list", "--params",
                          json.dumps({"q": q, "pageSize": page_size,
                                      "fields": fields,
                                      "orderBy": "modifiedTime desc"}))
        return data.get("files", [])

    def revision_census(self, file_id: str) -> dict:
        """Counts and shape of one file's revision list. No content."""
        revs = self._list_revisions(file_id)
        times = [r.get("modifiedTime") for r in revs if r.get("modifiedTime")]
        authors = {(r.get("lastModifyingUser") or {}).get("displayName")
                   for r in revs}
        authors.discard(None)
        return {
            "file_id": file_id,
            "revisions_returned": len(revs),
            "first_revision_time": min(times) if times else None,
            "last_revision_time": max(times) if times else None,
            "distinct_authors": len(authors),
            "has_text_plain_export": sum(
                1 for r in revs if "text/plain" in (r.get("exportLinks") or {})),
        }

    def _list_revisions(self, file_id: str) -> list[dict]:
        preflight(self._transport)
        revs, token = [], None
        while True:
            params = {"fileId": file_id, "pageSize": 200,
                      "fields": "revisions(id,modifiedTime,lastModifyingUser,exportLinks),nextPageToken"}
            if token:
                params["pageToken"] = token
            data = self._json("drive", "revisions", "list", "--params",
                              json.dumps(params))
            revs.extend(data.get("revisions", []))
            token = data.get("nextPageToken")
            if not token:
                return revs

    # ---- contract ----
    def describe(self, ref: ArtifactRef) -> ArtifactMeta:
        preflight(self._transport)
        f = self._json("drive", "files", "get", "--params",
                       json.dumps({"fileId": ref.locator,
                                   "fields": "id,name,mimeType,createdTime,modifiedTime"}))
        # Drive's revisions.list documentation warns the list may be
        # incomplete for frequently edited files and unpinned revisions
        # are purged; the provider cannot promise completeness.
        return ArtifactMeta(title=f.get("name", ref.locator), kind=self.kind,
                            created=f.get("createdTime"),
                            modified=f.get("modifiedTime"),
                            history_complete=False)

    def snapshots(self, ref: ArtifactRef) -> list[Snapshot]:
        revs = self._list_revisions(ref.locator)
        snaps = []
        for r in revs:
            rid = r["id"]
            user = (r.get("lastModifyingUser") or {}).get("displayName")
            snaps.append(Snapshot(
                id=rid, timestamp=r.get("modifiedTime"), author=user,
                _fetch=lambda rid=rid: self._fetch_revision_text(ref.locator, rid)))
        return snaps

    def _fetch_revision_text(self, file_id: str, revision_id: str) -> str:
        """One revision's plain text via revisions get (alt=media).

        This is the provider's single content seam: if the connector
        CLI's revision-download behaviour changes, only this method
        changes. The metadata exportLinks fallback is recorded by the
        census (has_text_plain_export)."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rev.txt"
            self._transport("drive", "revisions", "get", "--params",
                            json.dumps({"fileId": file_id, "revisionId": revision_id,
                                        "alt": "media"}),
                            output=out)
            return out.read_text(encoding="utf-8", errors="replace")

    def evidence_events(self, ref: ArtifactRef) -> list[EvidenceEvent]:
        # Suggested-edit accept/reject state is not exposed in the
        # connector CLI's tested surface today (comments exist as a
        # resource; per-suggestion resolution state per revision does
        # not). Return none rather than claim unread evidence; the
        # channel is where it lands when the API path is verified.
        return []
