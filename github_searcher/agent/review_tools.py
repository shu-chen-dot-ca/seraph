"""A reviewer agent's own tools: it checks a PR draft before it reaches the user's Inbox.

Every repo's PR drafts go to that repo's own reviewer first (its record's "role": "reviewer" and "reviews": the repo,
made the first time by Agents.give_review), which checks them in the author's folder on the author's desktop, where the
project is set up and built. Only an agent whose record's role is "reviewer" gets these (agent.py):
- review_read: a PR draft it was given to review, as the user would see it (title, text, overview with its checklist,
  commits, diff, the test runs, the evidence with its pictures as pictures), the repo's AI policy now and what it means
  for the PR's text (only a disclose repo's PRs say AI helped), and, while it holds the VM, the diff in
  ~/review-<draft id>.diff, with how to check the author's folder still has the draft's code;
- review_done: pass (the draft goes to the user's Inbox) or changes (back to its author, with the notes),
  through Agents.review_finished.

Each tool returns its result as text; a bad call returns is_error. describe() gives the chat's line for each call.

    tools = ReviewTools(agents, record).list()
"""

import asyncio
import base64
import json
import shlex

from claude_agent_sdk import tool

from github_searcher.agent.work_tools import EMOJI, NO_EMOJI
from github_searcher.jobs import EVIDENCE_DIR
from sandbox.vms import VMsError

# review_read shows this much of a draft's diff; the rest is in the VM's file.
REVIEW_DIFF_CHARS = 150_000
# The evidence's picture types, by file ending (inbox_api.py serves the same).
PICTURE_TYPES = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


class ReviewTools:
    def __init__(self, agents, record: dict):
        # The Agents manager: the inbox, jobs, repo signals and the VMs.
        self.agents = agents
        # The agent's record (the same dict): its "role", and the target VM read from it each time.
        self.record = record
        self.agent_id = record["id"]

    def list(self) -> list:
        # Read from the record each time: a new reviewer's role is set on its record after it is made.
        if self.record.get("role") != "reviewer":
            return []
        return [
            tool(
                "review_read",
                "Read a PR draft you were given to review (draft_...): its title and text as they would go to GitHub, the "
                "overview for the user (with the author's checklist of every point asked, and the cases it also tested), its "
                "commits, the diff, the test runs and the evidence, with the pictures, and the repo's AI policy as it is now "
                "with what it means for the PR's text (ai_policy: only a disclose repo's PRs say AI helped). While you hold "
                "the VM, the whole diff is also put in ~/review-<draft id>.diff, to apply on the commit it starts from (base_sha).",
                {"draft_id": str},
            )(self.review_read),
            tool(
                "review_done",
                "Your verdict on a PR draft you reviewed. pass: it goes to the user's Inbox, with your notes. changes: it "
                "goes back to its author with your notes, and never reaches the user. notes: for pass, what you checked "
                "in a few lines; for changes, exactly what must change and why, each point on its own line, with the "
                "failing case (the input, what came out, what should). No emoji.",
                {
                    "type": "object",
                    "properties": {"draft_id": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "changes"]}, "notes": {"type": "string"}},
                    "required": ["draft_id", "verdict", "notes"],
                },
            )(self.review_done),
        ]

    def describe(self, name: str, args: dict) -> str | None:
        """The chat's line for a call of these tools, or None for another tool."""
        if name == "review_read":
            return f"Reading {args.get('draft_id')} to review it"
        if name == "review_done":
            return f"Review of {args.get('draft_id')}: {args.get('verdict')}"
        return None

    async def review_read(self, args: dict) -> dict:
        try:
            draft = self.agents.inbox.get(args["draft_id"])
        except KeyError:
            return {"content": [{"type": "text", "text": f"No draft {args['draft_id']}."}], "is_error": True}
        if draft["review"] is None or draft["review"]["agent"] != self.agent_id:
            return {"content": [{"type": "text", "text": f"{draft['id']} wasn't given to you to review."}], "is_error": True}
        tests = {"before": None, "after": None}
        if draft["job"] is not None:
            try:
                tests = self.agents.jobs.get(draft["job"])["tests"]
            except KeyError:
                pass
        author = self.agents.agents.get(draft["agent"])
        diff = draft["diff"]
        cut = len(diff) > REVIEW_DIFF_CHARS
        report = {
            "id": draft["id"],
            "author": author.name if author is not None else draft["agent"],
            "for": draft["target"],
            "replaces": draft["replaces"],
            "title": draft["title"],
            "body": draft["body"],
            "overview": draft["overview"],
            "branch": draft["branch"],
            "base": draft["base"],
            "base_sha": draft["base_sha"],
            "commits": [commit["message"] for commit in draft["commits"]],
            "tests": tests,
            "evidence": [],
        }
        for item in draft["evidence"]:
            each = {key: item.get(key) for key in ["id", "kind", "stage", "topic", "context", "caption", "command", "exit_code", "output_tail"]}
            report["evidence"].append(each)
        # A new version or rebase of the user's open PR: its body is the comment posted with the push, and the author's
        # rules decide whether there is one (prompt.md, Following up on PRs and issues). The reviewer goes by the same rules,
        # so it never sends a draft back for what draft_pr refuses.
        if draft["update_of"] is not None:
            report["push_comment"] = (
                f"This is the next version of the user's PR {draft['update_of']}, and body is the comment posted on it with the "
                "push. It stays empty when no maintainer or reviewer asked for this version this round (a failing check, a "
                "bot's point, a conflict nobody mentioned) or one comment of ours already speaks for the round: draft_pr "
                "refuses one then. Never ask for a push comment in those cases, and never for an answer to a review bot or to "
                "anyone who is neither a maintainer nor a reviewer."
            )
        # The repo's AI policy as the app has it now (repo_signals.py), and the rule draft_pr holds the author to: kestra's
        # reviewer asked for an AI line because our older kestra drafts had one, from when its tag was disclose; it is
        # welcome now, and a PR there says nothing about AI.
        if draft["repo"] is not None:
            signals = self.agents.repo_signals.get(draft["repo"])
            policy = "none"
            if signals is not None and signals.get("ai_policy"):
                policy = signals["ai_policy"]["tag"]
            rule = (
                "Its PRs say nothing about AI helping: no AI section, no line that an AI or agent prepared it. Never ask for "
                "one. This is the repo's tag now: go by it, not by older drafts or PRs."
            )
            if policy == "disclose":
                rule = (
                    "Its PRs say plainly that AI tools helped, the way its rules or PR template ask: ask for that when it is "
                    "missing. This is the repo's tag now: go by it, not by older drafts or PRs."
                )
            report["ai_policy"] = {"tag": policy, "rule": rule}
        text = json.dumps(report) + "\n\nThe diff" + (f" (cut at {REVIEW_DIFF_CHARS:,} characters; all of it is in the VM's file)" if cut else "") + ":\n" + diff[:REVIEW_DIFF_CHARS]

        # The diff as a file in the VM, while it holds one: to apply on base_sha and run the tests on.
        vm_name = self.record["target_vm"]
        desktop = None
        vm_record = None
        if vm_name is not None:
            try:
                vm_record = self.agents.vms.get(vm_name)
                desktop = vm_record.holding(self.agent_id)
            except VMsError:
                desktop = None
        if desktop is not None:
            vm = vm_record.desktop_vm(desktop)
            name = f"review-{draft['id']}.diff"
            body = diff if diff.endswith("\n") else diff + "\n"
            try:
                result = await asyncio.to_thread(vm.exec, f"cat > {name}", 120, body)
                # It checks the draft in the author's folder, where it was drafted and the project is built.
                if result.returncode == 0:
                    folder = shlex.quote(draft["path"] or "")
                    copy = f"~/review-{draft['id']}"
                    text += (
                        f"\n\nThe diff is in ~/{name}. The draft was made in {draft['path']}: check its code is still the draft's "
                        f"(`cd {folder} && git add -A -N . && git diff {draft['base_sha']} | cmp - ~/{name} && echo same`) and work "
                        f"there, leaving it as you found it. If the author changed it since, check a copy instead: `git -C {folder} "
                        f"worktree add {copy} {draft['base_sha']} && git -C {copy} apply ~/{name}` (and `git -C {folder} worktree "
                        f"remove --force {copy}` when done)."
                    )
            except Exception as error:
                text += f"\n\nThe diff couldn't be put in the VM: {error}"

        content = [{"type": "text", "text": text}]
        for item in draft["evidence"]:
            if item["kind"] not in ["screenshot", "image"] or not item.get("file"):
                continue
            ending = item["file"].rsplit(".", 1)[-1]
            path = EVIDENCE_DIR / item["file"]
            if ending not in PICTURE_TYPES or not path.is_file():
                continue
            data = await asyncio.to_thread(path.read_bytes)
            content.append({"type": "text", "text": f"{item['id']}, {item['stage']}, {item['topic']}: {item['caption']}"})
            content.append({"type": "image", "data": base64.b64encode(data).decode(), "mimeType": PICTURE_TYPES[ending]})
        return {"content": content}

    async def review_done(self, args: dict) -> dict:
        try:
            draft = self.agents.inbox.get(args["draft_id"])
        except KeyError:
            return {"content": [{"type": "text", "text": f"No draft {args['draft_id']}."}], "is_error": True}
        if draft["review"] is None or draft["review"]["agent"] != self.agent_id:
            return {"content": [{"type": "text", "text": f"{draft['id']} wasn't given to you to review."}], "is_error": True}
        if draft["review"]["state"] != "waiting" or draft["status"] != "pending":
            return {"content": [{"type": "text", "text": f"{draft['id']} has its verdict already."}], "is_error": True}
        verdict = args.get("verdict")
        notes = (args.get("notes") or "").strip()
        if verdict not in ["pass", "changes"]:
            return {"content": [{"type": "text", "text": "verdict must be pass or changes."}], "is_error": True}
        if not notes:
            return {"content": [{"type": "text", "text": "Write your notes: what you checked, or what must change."}], "is_error": True}
        found = EMOJI.findall(notes)
        if found:
            return {"content": [{"type": "text", "text": NO_EMOJI + " ".join(sorted(set(found)))}], "is_error": True}
        self.agents.review_finished(draft["id"], verdict == "pass", notes)
        text = f"{draft['id']} went to the user's Inbox with your notes."
        if verdict == "changes":
            text = f"{draft['id']} went back to its author with your notes; its next draft comes to you again."
        vm_name, place = self.agents.queue.place(self.agent_id)
        left = [other for other in self.agents.jobs.for_agent(self.agent_id) if other["status"] in ["queued", "working"] and other["vm"] == vm_name]
        if place == 0 and not left:
            text += f" You have no open jobs left for {vm_name}: call release_vm now."
        return {"content": [{"type": "text", "text": text}]}
