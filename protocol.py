"""NDJSON framing shared by the server and the client.

Implements protocol_blueprint.md section 2: every message is one JSON object
on a single line followed by exactly one newline, UTF-8 encoded.
"""

import json

MAX_LINE_BYTES = 64 * 1024  # 64 KiB guard from protocol_blueprint.md 2.2
PORT_MIN = 1024
PORT_MAX = 65535

# Exceptions that mean "the peer is gone" (protocol_blueprint.md section 5).
CONNECTION_ERRORS = (BrokenPipeError, ConnectionResetError,
                     ConnectionAbortedError)


def parse_port(text):
    """Port number from a CLI string, or None if not an int in range."""
    try:
        port = int(text)
    except (TypeError, ValueError):
        return None
    if PORT_MIN <= port <= PORT_MAX:
        return port
    return None


def encode(obj):
    """Serialize one message as a single NDJSON line (bytes)."""
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def send_line(conn, obj):
    """Send one message. Returns False (no raise) if the peer is gone."""
    try:
        conn.sendall(encode(obj))
        return True
    except CONNECTION_ERRORS:
        return False


class MalformedLine:
    """A line that could not be turned into a message.

    LineBuffer yields these instead of raising, so a bad line never kills the
    receiving thread. The server answers with ERROR MALFORMED_MESSAGE.
    """

    def __init__(self, detail):
        self.detail = detail

    def __repr__(self):
        return "MalformedLine({!r})".format(self.detail)


class LineBuffer:
    """Per-connection receive buffer that extracts complete NDJSON lines.

    feed() takes the bytes from one recv() and returns a list containing a
    dict for every complete, valid message and a MalformedLine for every bad
    one. Bytes after the last newline are kept for the next feed().
    """

    def __init__(self, max_line_bytes=MAX_LINE_BYTES):
        self.max_line_bytes = max_line_bytes
        self.buffer = b""
        self.discarding = False  # inside an oversize line, skip to its "\n"

    def feed(self, data):
        results = []
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if self.discarding:
                # Tail end of a line already reported as too long.
                self.discarding = False
                continue
            if not line.strip():
                continue
            results.append(self._parse(line))
        if len(self.buffer) > self.max_line_bytes:
            results.append(MalformedLine("Line exceeds maximum length"))
            self.buffer = b""
            self.discarding = True
        return results

    def _parse(self, line):
        if len(line) > self.max_line_bytes:
            return MalformedLine("Line exceeds maximum length")
        try:
            obj = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError:
            return MalformedLine("Line is not valid UTF-8")
        except ValueError:
            return MalformedLine("Line is not valid JSON")
        if not isinstance(obj, dict):
            return MalformedLine("Message must be a JSON object")
        if not isinstance(obj.get("type"), str):
            return MalformedLine("Message has no 'type' string")
        return obj
