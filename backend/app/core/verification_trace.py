"""What the verification agent did, for explaining a run that stopped without a verdict.

The summary is shown publicly, and the argument under check was written by
whoever posted it. So it is built only from what the agent asked to do — tool
names and their inputs, clipped — and never from what a tool returned or what
the agent wrote. Fetches name their domain, not their URL.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

SUMMARY_LIMIT = 400
QUOTED_QUERIES = 3
QUERY_CHARS = 40
COMMAND_CHARS = 60
NAME_CHARS = 40

_HOSTNAME = re.compile(r"^[a-z0-9.-]{1,63}$")

_SEARCH = "mcp__paper__search_paper"
_READ = "mcp__paper__read_paper"
_FILE_SEARCH = frozenset({"Glob", "Grep"})


def _clip(text: object, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def plural(n: int, singular: str, many: str) -> str:
    return f"{n} {singular if n == 1 else many}"


def _domain(url: object) -> str:
    """The host, if it looks like one. `urlparse` happily returns prose as a hostname."""
    host = urlparse(str(url)).hostname
    if host is None or not _HOSTNAME.match(host):
        return "an unparseable address"
    return host


def _offset(value: object) -> str:
    return str(value) if isinstance(value, int) else "?"


def _doing(call: ToolUseBlock) -> str:
    """The step as a gerund phrase: "running `ls`"."""
    args = call.input
    if call.name == _SEARCH:
        return f'searching the paper for "{_clip(args.get("query", ""), QUERY_CHARS)}"'
    if call.name == _READ:
        return f"reading the paper (characters {_offset(args.get('start'))}–{_offset(args.get('end'))})"
    if call.name == "Bash":
        return f"running `{_clip(args.get('command', ''), COMMAND_CHARS)}`"
    if call.name in _FILE_SEARCH:
        return f"searching files for `{_clip(args.get('pattern', ''), QUERY_CHARS)}`"
    if call.name == "WebFetch":
        return f"fetching from {_domain(args.get('url', ''))}"
    return f"calling {_clip(call.name, NAME_CHARS)}"


@dataclass
class VerificationTrace:
    """Tool calls observed so far. Fed message by message, so it survives a cancelled run.

    Turns are counted by ``message_id`` because the CLI streams one model
    response as several ``AssistantMessage``s that share it. A message without
    an id counts as a turn of its own.
    """

    calls: list[ToolUseBlock] = field(default_factory=list)
    finished: set[str] = field(default_factory=set)
    turn_ids: set[str] = field(default_factory=set)
    unidentified_turns: int = 0

    @property
    def turns(self) -> int:
        return len(self.turn_ids) + self.unidentified_turns

    def observe(self, message: object) -> None:
        if isinstance(message, AssistantMessage):
            if message.message_id is None:
                self.unidentified_turns += 1
            else:
                self.turn_ids.add(message.message_id)
            self.calls.extend(b for b in message.content if isinstance(b, ToolUseBlock))
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            self.finished.update(
                b.tool_use_id for b in message.content if isinstance(b, ToolResultBlock)
            )

    def _activity(self) -> str:
        kinds = Counter(c.name for c in self.calls)
        parts = []
        if kinds[_SEARCH]:
            queries = [
                f'"{_clip(c.input.get("query", ""), QUERY_CHARS)}"'
                for c in self.calls if c.name == _SEARCH
            ][:QUOTED_QUERIES]
            parts.append(
                f"{plural(kinds[_SEARCH], 'search', 'searches')} of the paper "
                f"({', '.join(queries)})"
            )
        if kinds[_READ]:
            parts.append(f"{plural(kinds[_READ], 'read', 'reads')} of the paper")
        if kinds["Bash"]:
            parts.append(plural(kinds["Bash"], "shell command", "shell commands"))
        file_searches = sum(kinds[name] for name in _FILE_SEARCH)
        if file_searches:
            parts.append(plural(file_searches, "file search", "file searches"))
        if kinds["WebFetch"]:
            domains = list(dict.fromkeys(
                _domain(c.input.get("url", "")) for c in self.calls if c.name == "WebFetch"
            ))
            parts.append(
                f"{plural(kinds['WebFetch'], 'fetch', 'fetches')} from {', '.join(domains)}"
            )
        known = {_SEARCH, _READ, "Bash", "WebFetch", *_FILE_SEARCH}
        for name, n in kinds.items():
            if name not in known:
                parts.append(f"{plural(n, 'call', 'calls')} to {_clip(name, NAME_CHARS)}")
        return ", ".join(parts)

    def _position(self) -> str:
        unfinished = [c for c in self.calls if c.id not in self.finished]
        if unfinished:
            return f"It was still {_doing(unfinished[-1])} when it stopped."
        return f"Its last step was {_doing(self.calls[-1])}."

    def summary(self, stopped: str) -> str:
        """A paragraph of at most ``SUMMARY_LIMIT`` characters.

        ``stopped`` says why the run ended, e.g. "after 500s and 19 turns".
        """
        if not self.calls:
            return f"Stopped {stopped}, before using any tools."
        head, tail = f"Stopped {stopped}: ", f". {self._position()}"
        room = max(SUMMARY_LIMIT - len(head) - len(tail), 1)
        return _clip(head + _clip(self._activity(), room) + tail, SUMMARY_LIMIT)
