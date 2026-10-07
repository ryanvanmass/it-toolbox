"""Read-only access to mbox mail archives (Google Takeout, Thunderbird,
Apple Mail exports, ...) for the Mbox Browser module.

Everything here is plain stdlib and blocking, so callers run it through
async_utils.run_in_background. A MboxReader keeps the file open (its
table of contents is built once, by index()) and serializes access with a
lock, because the browser can have a message load and a body search in
flight on worker threads at the same time, sharing one file handle.

The table of contents is built here rather than by stdlib `mailbox.mbox`
so the scan can report progress and be cancelled: on a multi-gigabyte
archive it's the slowest part of opening a file. It follows the same
rule as `mailbox.mbox`: every line starting with "From " begins a new
message, and a blank line just before it belongs to neither.
"""

import html
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path


@dataclass(frozen=True)
class MessageSummary:
    """One row of the message list — headers only."""

    key: int
    subject: str
    sender: str
    recipients: str
    date: datetime | None
    has_attachments: bool

    def matches(self, needle: str) -> bool:
        """Case-insensitive header match; `needle` must already be lowercase."""
        return any(
            needle in value.lower()
            for value in (self.subject, self.sender, self.recipients, self.date_text)
        )

    @property
    def date_text(self) -> str:
        return self.date.strftime("%Y-%m-%d %H:%M") if self.date else ""


@dataclass(frozen=True)
class Attachment:
    index: int
    filename: str
    content_type: str
    size: int


@dataclass(frozen=True)
class MessageDetail:
    key: int
    headers: list[tuple[str, str]]
    text_body: str | None
    html_body: str | None
    attachments: list[Attachment] = field(default_factory=list)


_SHOWN_HEADERS = ("From", "To", "Cc", "Date", "Subject")

_TAG_RE = re.compile(r"<[^>]+>")
# Attachment check for the message list. Parsing every message's MIME
# tree just for this made indexing ~10x slower on attachment-heavy
# archives, so index() looks for the disposition headers in the raw bytes
# instead; load() still walks the real parts.
_ATTACHMENT_HEADER_RE = re.compile(
    rb"^content-disposition:[ \t]*(attachment|inline;[ \t]*(\r?\n[ \t]+)?filename)",
    re.IGNORECASE | re.MULTILINE,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def decode_header_value(value: object) -> str:
    """RFC 2047-decoded, single-line header text. Tolerates the broken
    encodings real archives are full of rather than raising."""
    if value is None:
        return ""
    text = str(value)
    try:
        text = str(make_header(decode_header(text)))
    except (LookupError, UnicodeError, ValueError):
        pass
    return " ".join(text.split())


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    # Mixing naive and aware datetimes breaks sorting; archives have both.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def html_to_text(markup: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", markup)
    text = _TAG_RE.sub(" ", text)
    return " ".join(html.unescape(text).split())


def _is_attachment(part: EmailMessage) -> bool:
    if part.is_multipart():
        return False
    disposition = part.get_content_disposition()
    if disposition == "attachment":
        return True
    # Inline parts with a filename (e.g. pasted images) are attachments too
    # as far as a reader is concerned — the body viewer can't show them.
    return disposition == "inline" and part.get_filename() is not None


def _part_text(part: EmailMessage) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, ValueError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    return content if isinstance(content, str) else ""


def message_detail(message: EmailMessage, key: int = 0) -> MessageDetail:
    """The headers, first text/plain and text/html bodies, and attachment
    list of a parsed message. Shared by the Mbox Browser and EML Viewer."""
    headers = [
        (name, decode_header_value(message.get(name)))
        for name in _SHOWN_HEADERS
        if message.get(name)
    ]
    text_body = html_body = None
    attachments = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if _is_attachment(part):
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                Attachment(
                    index=len(attachments),
                    filename=part.get_filename() or f"attachment-{len(attachments) + 1}",
                    content_type=part.get_content_type(),
                    size=len(payload),
                )
            )
        elif part.get_content_type() == "text/plain" and text_body is None:
            text_body = _part_text(part)
        elif part.get_content_type() == "text/html" and html_body is None:
            html_body = _part_text(part)
    return MessageDetail(key, headers, text_body, html_body, attachments)


def attachment_bytes(message: EmailMessage, index: int) -> bytes:
    """Decoded content of the message's `index`th attachment, numbered as
    in message_detail()."""
    parts = [p for p in message.walk() if _is_attachment(p)]
    return parts[index].get_payload(decode=True) or b""


#: index() progress callback: (phase, done, total). Phase is SCANNING
#: (done/total in bytes) and then READING (done/total in messages).
ProgressCallback = Callable[[str, int, int], None]
SCANNING = "scanning"
READING = "reading"

_PROGRESS_EVERY_BYTES = 1 << 20


class IndexCancelled(Exception):
    """index() was stopped by its `cancelled` callback."""


class MboxReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"No such mbox file: {self.path}")
        self._file = open(self.path, "rb")  # noqa: SIM115 - closed by close()
        self._lock = threading.Lock()
        self._parser = BytesParser(policy=policy.default)
        # The list only needs a few headers, decoded by decode_header_value()
        # anyway: compat32 skips policy.default's (much slower) structured
        # header parsing.
        self._header_parser = BytesParser(policy=policy.compat32)
        self._toc: list[tuple[int, int]] = []

    def close(self) -> None:
        with self._lock:
            self._file.close()

    def raw_bytes(self, key: int) -> bytes:
        """The message as stored (minus its "From " separator line), for
        parsing and for "Save as .eml"."""
        start, stop = self._toc[key]
        with self._lock:
            self._file.seek(start)
            self._file.readline()
            data = self._file.read(stop - self._file.tell())
        return data.replace(b"\r\n", b"\n")

    def _message(self, key: int) -> EmailMessage:
        return self._parser.parsebytes(self.raw_bytes(key))

    def _scan(self, progress: ProgressCallback, cancelled: Callable[[], bool]) -> None:
        total = self.path.stat().st_size
        starts: list[int] = []
        stops: list[int] = []
        blank_before = 0  # length of the blank line just read, if any
        position = next_report = 0
        with self._lock:
            self._file.seek(0)
            for line in self._file:
                if line.startswith(b"From "):
                    if len(stops) < len(starts):
                        stops.append(position - blank_before)
                    starts.append(position)
                    blank_before = 0
                elif line in (b"\n", b"\r\n"):
                    blank_before = len(line)
                else:
                    blank_before = 0
                position += len(line)
                if position >= next_report:
                    if cancelled():
                        raise IndexCancelled
                    progress(SCANNING, position, total)
                    next_report = position + _PROGRESS_EVERY_BYTES
        if len(stops) < len(starts):
            stops.append(position - blank_before)
        self._toc = list(zip(starts, stops))
        progress(SCANNING, total, total)

    def index(
        self,
        progress: ProgressCallback = lambda phase, done, total: None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> list[MessageSummary]:
        """Headers of every message, in file order. Raises IndexCancelled
        if `cancelled()` turns true part-way."""
        self._scan(progress, cancelled)
        total = len(self._toc)
        summaries = []
        for key in range(total):
            if cancelled():
                raise IndexCancelled
            progress(READING, key, total)
            raw = self.raw_bytes(key)
            header_end = raw.find(b"\n\n")
            message = self._header_parser.parsebytes(
                raw if header_end == -1 else raw[: header_end + 1], headersonly=True
            )
            summaries.append(
                MessageSummary(
                    key=key,
                    subject=decode_header_value(message.get("Subject")),
                    sender=decode_header_value(message.get("From")),
                    recipients=", ".join(
                        decode_header_value(message.get(name))
                        for name in ("To", "Cc")
                        if message.get(name)
                    ),
                    date=_parse_date(decode_header_value(message.get("Date"))),
                    has_attachments=_ATTACHMENT_HEADER_RE.search(raw) is not None,
                )
            )
        progress(READING, total, total)
        return summaries

    def load(self, key: int) -> MessageDetail:
        return message_detail(self._message(key), key)

    def attachment_bytes(self, key: int, index: int) -> bytes:
        return attachment_bytes(self._message(key), index)

    def body_text(self, key: int) -> str:
        """All text/plain and text/html content of a message, flattened
        for full-text search."""
        chunks = []
        for part in self._message(key).walk():
            if part.is_multipart() or _is_attachment(part):
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                chunks.append(_part_text(part))
            elif content_type == "text/html":
                chunks.append(html_to_text(_part_text(part)))
        return "\n".join(chunks)

    def search_bodies(
        self, keys: list[int], query: str, cancelled=lambda: False
    ) -> set[int] | None:
        """Keys among `keys` whose body contains `query` (case-insensitive).
        Returns None if `cancelled()` turned true part-way — the caller has
        moved on to a newer query and the partial result is meaningless.
        """
        needle = query.lower()
        found = set()
        for key in keys:
            if cancelled():
                return None
            if needle in self.body_text(key).lower():
                found.add(key)
        return found
