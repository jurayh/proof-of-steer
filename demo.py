"""Proof of Steering — bundled demo. Stdlib only, local only.

`proof-of-steer demo` runs the real receipt pipeline on a small
synthetic Claude Code session bundled with the tool, so a first-time
user can see a receipt, a badge, and a Steerprint in under a minute
without hunting for a transcript of their own. The receipt comes from
the same `steering_receipt.code_receipt` path as any real session;
there is no demo-only shortcut anywhere in the pipeline.

The sample session is a hand-authored miniature of a steered session
(it is not a copy of any reference session): 7 human turns building a
tiny reading-list CLI across two files. By design it contains one
procedural turn (a bare "continue" answered in prose), follow-ups that
only add (a new test file; one added header line), two corrections
that rewrite lines from earlier segments, one added line that a later
correction discards again, and a test run (the verification lane).
The hand-computed receipt for it is recorded in BUILD-NOTES.md and
asserted exactly by tests/test_demo.py.
"""
import json, shutil, sys, tempfile
from pathlib import Path

import steering_receipt as sr
import steering_viz

DEMO_LABEL = "demo"

SAMPLE_SESSION_JSONL = r"""{"type": "user", "timestamp": "2026-10-23T14:00:00Z", "message": {"content": [{"type": "text", "text": "Create reading_list.py, a tiny command line tool that keeps a list of books I want to read. It needs an add command and a list command."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:00:24Z", "message": {"id": "msg_demo_1", "usage": {"input_tokens": 820, "output_tokens": 210}, "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/home/demo/reading-list/reading_list.py", "content": "#!/usr/bin/env python3\nimport sys\nBOOKS = []\ndef add(title):\n    BOOKS.append(title)\n    print(\"added: \" + title)\ndef show():\n    for title in BOOKS:\n        print(\"- \" + title)\ndef main():\n    cmd = sys.argv[1] if len(sys.argv) > 1 else \"list\"\n    if cmd == \"add\":\n        add(sys.argv[2])\n    elif cmd == \"list\":\n        show()\nif __name__ == \"__main__\":\n    main()\n"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:00:26Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "ok"}]}}
{"type": "user", "timestamp": "2026-10-23T14:01:10Z", "message": {"content": [{"type": "text", "text": "continue"}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:01:20Z", "message": {"id": "msg_demo_2", "usage": {"input_tokens": 300, "output_tokens": 40}, "content": [{"type": "text", "text": "The basic tool is in place: add stores a title, and list prints every title with a dash. Say the word and I will keep going."}]}}
{"type": "user", "timestamp": "2026-10-23T14:02:05Z", "message": {"content": [{"type": "text", "text": "Add a test file with a few tests for it."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:02:30Z", "message": {"id": "msg_demo_3", "usage": {"input_tokens": 640, "output_tokens": 150}, "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/home/demo/reading-list/test_reading_list.py", "content": "import reading_list\ndef test_add_appends_a_title():\n    reading_list.BOOKS.clear()\n    reading_list.add(\"Dune\")\n    assert reading_list.BOOKS == [\"Dune\"]\ndef test_show_prints_the_title(capsys):\n    reading_list.BOOKS[:] = []\n    reading_list.add(\"Emma\")\n    reading_list.show()\n    out = capsys.readouterr().out\n    assert \"Emma\" in out\n"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:02:32Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "ok"}]}}
{"type": "user", "timestamp": "2026-10-23T14:03:15Z", "message": {"content": [{"type": "text", "text": "The list should be numbered, not dashed. Change show to print a number before each title, starting at 1."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:03:40Z", "message": {"id": "msg_demo_4", "usage": {"input_tokens": 700, "output_tokens": 120}, "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/home/demo/reading-list/reading_list.py", "old_string": "    for title in BOOKS:\n        print(\"- \" + title)", "new_string": "    for number, title in enumerate(BOOKS, 1):\n        print(str(number) + \". \" + title)"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:03:42Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "ok"}]}}
{"type": "user", "timestamp": "2026-10-23T14:04:20Z", "message": {"content": [{"type": "text", "text": "Print a header line, My reading list:, above the titles when listing."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:04:50Z", "message": {"id": "msg_demo_5", "usage": {"input_tokens": 900, "output_tokens": 230}, "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/home/demo/reading-list/reading_list.py", "content": "#!/usr/bin/env python3\nimport sys\nBOOKS = []\ndef add(title):\n    BOOKS.append(title)\n    print(\"added: \" + title)\ndef show():\n    print(\"My reading list:\")\n    for number, title in enumerate(BOOKS, 1):\n        print(str(number) + \". \" + title)\ndef main():\n    cmd = sys.argv[1] if len(sys.argv) > 1 else \"list\"\n    if cmd == \"add\":\n        add(sys.argv[2])\n    elif cmd == \"list\":\n        show()\nif __name__ == \"__main__\":\n    main()\n"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:04:52Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "ok"}]}}
{"type": "user", "timestamp": "2026-10-23T14:05:30Z", "message": {"content": [{"type": "text", "text": "Remove the header again. The output was cleaner without it."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:05:50Z", "message": {"id": "msg_demo_6", "usage": {"input_tokens": 500, "output_tokens": 80}, "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/home/demo/reading-list/reading_list.py", "old_string": "    print(\"My reading list:\")\n    for number, title in enumerate(BOOKS, 1):", "new_string": "    for number, title in enumerate(BOOKS, 1):"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:05:52Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "ok"}]}}
{"type": "user", "timestamp": "2026-10-23T14:06:40Z", "message": {"content": [{"type": "text", "text": "Change the add message to Added, then the title, then to your list, instead of added colon. Fix the wording and run the tests."}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:07:00Z", "message": {"id": "msg_demo_7", "usage": {"input_tokens": 550, "output_tokens": 90}, "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/home/demo/reading-list/reading_list.py", "old_string": "    print(\"added: \" + title)", "new_string": "    print(\"Added \" + title + \" to your list\")"}}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:07:05Z", "message": {"id": "msg_demo_8", "usage": {"input_tokens": 200, "output_tokens": 30}, "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "python3 -m pytest test_reading_list.py -q"}}]}}
{"type": "user", "timestamp": "2026-10-23T14:07:09Z", "message": {"content": [{"type": "tool_result", "is_error": false, "content": "2 passed in 0.11s"}]}}
{"type": "assistant", "timestamp": "2026-10-23T14:07:15Z", "message": {"id": "msg_demo_9", "usage": {"input_tokens": 150, "output_tokens": 25}, "content": [{"type": "text", "text": "Done: the add message is updated and both tests pass."}]}}"""


def run_demo(out_dir):
    """Run the bundled sample session through the receipt pipeline.

    Writes <label>.receipt.json, <label>.STEERING.md, <label>.badge.svg
    and <label>.steerprint.html into out_dir (plus the reconstructed
    git repo the join is cross-checked against, as the code subcommand
    does), prints a short guided summary, and returns 0.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    recon_dir = out_dir / f"reconstructed-{DEMO_LABEL}"
    if recon_dir.exists():
        # A stale reconstruction would poison the blame cross-check on
        # a repeat run (see the --commitment path in code_receipt).
        shutil.rmtree(recon_dir)
    with tempfile.TemporaryDirectory() as tmp:
        session_path = Path(tmp) / "sample-session.jsonl"
        session_path.write_text(SAMPLE_SESSION_JSONL + "\n", encoding="utf-8")
        receipt = sr.code_receipt(session_path, DEMO_LABEL, recon_dir=recon_dir)
    receipt_path = out_dir / f"{DEMO_LABEL}.receipt.json"
    md_path = out_dir / f"{DEMO_LABEL}.STEERING.md"
    badge_path = out_dir / f"{DEMO_LABEL}.badge.svg"
    map_path = out_dir / f"{DEMO_LABEL}.steerprint.html"
    receipt_path.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    md_path.write_text(sr.render_md(receipt), encoding="utf-8")
    badge_path.write_text(steering_viz.badge_svg(receipt), encoding="utf-8")
    map_path.write_text(steering_viz.build([receipt]), encoding="utf-8")

    m, g = receipt["mechanistic"], receipt["git_join"]
    im = g["impact"]
    mark = receipt["mark"]
    print("proof-of-steer demo")
    print()
    print("The bundled sample is a small synthetic Claude Code session, written for")
    print(f"trying the tool: {m['human_turns']} human turns in which a person steers an agent")
    print("building a tiny reading-list CLI. It is not a real session. Every number")
    print("below was computed by the same pipeline that handles real transcripts.")
    print()
    print(f"Steering mark: {mark['category']}")
    print(f"  {mark['basis']}")
    print(f"Headline: {g['headline_fields']['post_first_prompt_share_pct']}% of the shipped "
          f"lines arrived after the first prompt")
    print(f"Impact: {im['procedural_turns']} procedural, {im['continuation_turns']} continuation, "
          f"{im['reshaping_turns']} reshaping, {im['unmeasured_segments']} unmeasured")
    print()
    print(f"Written to {out_dir}:")
    for name, what in ((receipt_path.name, "the receipt (counts and categories only, never prompt text)"),
                       (md_path.name, "the same receipt as a readable summary"),
                       (badge_path.name, "the steering mark as an embeddable badge"),
                       (map_path.name, "the full Steerprint map; open it in a browser"),
                       (recon_dir.name + "/", "the local git repo the join was cross-checked against")):
        print(f"  {name:<24} {what}")
    print()
    print("Now run it on your own session:")
    print("  proof-of-steer code path/to/session.jsonl --label my-session")
    return 0


if __name__ == "__main__":
    sys.exit(run_demo(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo-out")))
