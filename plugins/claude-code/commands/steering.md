---
description: Generate a Proof of Steering receipt for the current session and show its headline numbers
allowed-tools: Bash(python3:*)
---

Generate a Proof of Steering receipt for the current Claude Code session.

1. Resolve the hook script path: use the value of the `STEERING_HOOK`
   environment variable if it is set; otherwise use the absolute path of
   `steering_hook.py` recorded in the Proof of Steering install notes
   (INSTALL.md, "Slash command" section — the user was told to set
   `STEERING_HOOK` or note the path). If neither is available, tell the
   user the hook script path is not configured and point them at
   INSTALL.md instead of guessing a path.
2. Run it in manual mode against this project, asking for the newest
   session transcript and a printed summary:

   `python3 "<hook script path>" --cwd "<absolute path of the current project directory>" --latest --print-summary`

   Note: `--latest` picks the most recently modified transcript in
   `~/.claude/projects/<encoded project path>/`, which is the current
   session's own transcript while this session is running. The receipt
   therefore covers the session **so far**.
3. Relay the printed headline numbers to the user verbatim (human turns,
   post-first-prompt share, blame agreement), plus the two file paths the
   command prints (`steering-receipt.json` and `STEERING.md` under the
   project's `.steering/` directory). Do not paraphrase the numbers,
   round them, or add interpretation beyond one plain sentence: the
   receipt is descriptive evidence, not a grade.
4. If the command exits non-zero, relay its stderr message exactly and
   suggest checking `.steering/hook.log` in the project root; do not
   retry with different arguments.
