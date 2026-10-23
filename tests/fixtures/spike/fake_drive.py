"""Recorded-shape fake Drive transport for offline fixture validation.

Implements the exact callable signature of the gdrive provider's API
seam (`transport(*args, output=None) -> str`, mirroring `_gws` in
providers/gdrive_doc.py) and answers from a scenario directory:

    <scenario>/file.json    -- the `files get` response (id, name, times)
    <scenario>/pages.json   -- list of `revisions list` page responses,
                               in order; every page but the last carries
                               a "nextPageToken" the next request must
                               present, exactly like the real API
    <scenario>/texts/<revision-id>.txt
                            -- the text/plain export content served for
                               `revisions get` with alt=media (written
                               to the caller's -o path)

No network, no connector, no real documents: every byte is synthetic
fixture data checked in next to this file. The transport records each
request in `.requests` so the validator can assert pagination was
actually walked.
"""
from __future__ import annotations

import json
from pathlib import Path


class FakeDriveTransport:
    def __init__(self, scenario_dir):
        self.dir = Path(scenario_dir)
        self.file_meta = json.loads((self.dir / "file.json").read_text())
        self.pages = json.loads((self.dir / "pages.json").read_text())
        self.requests: list[tuple[str, object]] = []

    # ---- helpers ----
    def _page_index(self, token):
        if token is None:
            return 0
        for i, page in enumerate(self.pages):
            if page.get("nextPageToken") == token:
                return i + 1
        raise AssertionError(f"fake transport: unknown pageToken {token!r}")

    def _revision_meta(self, revision_id):
        for page in self.pages:
            for rev in page.get("revisions", []):
                if rev["id"] == revision_id:
                    return rev
        raise AssertionError(f"fake transport: unknown revision {revision_id!r}")

    # ---- the seam ----
    def __call__(self, *args, output=None):
        if args[:2] == ("drive", "status"):
            return json.dumps({"status": "connected", "kind": "fixture"})
        if len(args) < 5 or args[0] != "drive" or args[3] != "--params":
            raise AssertionError(f"fake transport: unexpected call shape {args!r}")
        params = json.loads(args[4])
        resource, action = args[1], args[2]

        if (resource, action) == ("files", "get"):
            if params.get("fileId") != self.file_meta["id"]:
                raise AssertionError(
                    f"fake transport: files get for wrong id {params.get('fileId')!r}")
            return json.dumps(self.file_meta)

        if (resource, action) == ("files", "list"):
            return json.dumps({"files": [self.file_meta]})

        if (resource, action) == ("revisions", "list"):
            if params.get("fileId") != self.file_meta["id"]:
                raise AssertionError("fake transport: revisions list for wrong file")
            token = params.get("pageToken")
            page = self.pages[self._page_index(token)]
            self.requests.append(("revisions.list", token))
            return json.dumps(page)

        if (resource, action) == ("revisions", "get"):
            rid = params.get("revisionId")
            self.requests.append(("revisions.get", rid))
            if output is not None:
                text = (self.dir / "texts" / f"{rid}.txt").read_text(encoding="utf-8")
                Path(output).write_text(text, encoding="utf-8")
                return ""
            return json.dumps(self._revision_meta(rid))

        raise AssertionError(f"fake transport: unhandled call {args!r}")
