"""Read-only access to a single saved email message (.eml) for the EML
Viewer. The message is parsed with the same rules as the Mbox Browser
(see mbox_reader.message_detail), so both show it identically.

Plain stdlib and blocking: callers run it through
async_utils.run_in_background.
"""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from it_toolbox.core.mbox_reader import MessageDetail, attachment_bytes, message_detail


class EmlReader:
    """Reads and parses the whole file up front; .eml files hold one
    message, so there's nothing to index or keep open."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"No such file: {self.path}")
        data = self.path.read_bytes().replace(b"\r\n", b"\n")
        # Some tools save a single message with its mbox "From " separator
        # line still on top; it isn't a header, so the parser would treat
        # it as the start of the body.
        if data.startswith(b"From "):
            data = data.partition(b"\n")[2]
        if not data.strip():
            raise ValueError(f"{self.path.name} is empty")
        self._message: EmailMessage = BytesParser(policy=policy.default).parsebytes(data)

    def load(self) -> MessageDetail:
        return message_detail(self._message)

    def attachment_bytes(self, index: int) -> bytes:
        return attachment_bytes(self._message, index)
