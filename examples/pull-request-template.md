# Pull request template snippet

Add the section below to your project's pull request template (`.github/pull_request_template.md`, or the template your host uses) and contributors who worked with an agent will attach their steering evidence by habit. It takes them one command, and it gives you the receipt before you start reading.

Copy everything between the lines:

---

## Steering

If an AI agent helped make this change, attach its steering receipt so reviewers can price their review.

- Steering mark: <!-- for example: Closely steered, 7 turns -->
- Receipt: <!-- attach the .receipt.json file, paste the summary from STEERING.md, or link the Steerprint -->

Generate it with `proof-of-steer code <session.jsonl> --label <label>`. The receipt carries counts and categories only, never prompt text, and the transcript never leaves your machine.

Delete this section if no agent was involved.

---

Why ask? A receipt reports what observably happened while the change was made: how many genuine human turns there were, how much of the shipped code arrived after the first prompt, and which parts were reshaped in later turns. It is descriptive evidence, never a certified grade. And it helps either way, because a one-prompt receipt and a closely steered one ask for very different reviews.
