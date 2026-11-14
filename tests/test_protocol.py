"""LineBuffer framing tests (protocol_blueprint.md section 2)."""

import json
import unittest

from protocol import MAX_LINE_BYTES, LineBuffer, MalformedLine, encode


class LineBufferTest(unittest.TestCase):
    def test_fragmentation(self):
        """One message split across several recv() chunks."""
        wire = encode({"type": "MOVE", "move_name": "Flamethrower"})
        buf = LineBuffer()
        self.assertEqual(buf.feed(wire[:5]), [])
        self.assertEqual(buf.feed(wire[5:20]), [])
        self.assertEqual(buf.feed(wire[20:]),
                         [{"type": "MOVE", "move_name": "Flamethrower"}])
        self.assertEqual(buf.buffer, b"")

    def test_coalescing(self):
        """Several messages arriving in one recv() chunk."""
        msgs = [{"type": "MOVE", "move_name": "Surf"},
                {"type": "SWITCH", "switch_to": "Snorlax"},
                {"type": "DISCONNECT"}]
        wire = b"".join(encode(m) for m in msgs)
        self.assertEqual(LineBuffer().feed(wire), msgs)

    def test_blueprint_three_recv_example(self):
        """Fragmentation and coalescing together (blueprint 2.3)."""
        first = {"type": "STATE_UPDATE", "round": 3}
        error = {"type": "ERROR", "error_code": "INVALID_MOVE",
                 "detail": "..."}
        last = {"type": "STATE_UPDATE", "round": 4}
        wire = b"".join(encode(m) for m in (first, error, last))
        cut1 = wire.index(b'{"type": "ERROR"') + len(b'{"type": "ERR')
        cut2 = wire.index(b'"round": 4')
        buf = LineBuffer()
        self.assertEqual(buf.feed(wire[:cut1]), [first])
        self.assertEqual(buf.buffer, b'{"type": "ERR')
        self.assertEqual(buf.feed(wire[cut1:cut2]), [error])
        self.assertTrue(buf.buffer.startswith(b'{"type": "STATE_UPDATE"'))
        self.assertEqual(buf.feed(wire[cut2:]), [last])
        self.assertEqual(buf.buffer, b"")

    def test_oversize_line(self):
        """A line longer than 64 KiB is reported once and skipped."""
        buf = LineBuffer()
        big = b'{"type": "MOVE", "move_name": "' + b"x" * MAX_LINE_BYTES
        results = buf.feed(big)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], MalformedLine)
        self.assertEqual(buf.buffer, b"")
        # The rest of the oversize line is dropped, then framing recovers.
        tail = b'"}\n' + encode({"type": "DISCONNECT"})
        self.assertEqual(buf.feed(tail), [{"type": "DISCONNECT"}])

    def test_oversize_complete_line(self):
        line = json.dumps({"type": "MOVE",
                           "move_name": "x" * MAX_LINE_BYTES}).encode()
        results = LineBuffer().feed(line + b"\n")
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], MalformedLine)

    def test_malformed_lines_do_not_raise(self):
        wire = (b"not json\n" + b"[1, 2]\n" + b'{"no_type": 1}\n'
                + b"\xff\xfe\n" + encode({"type": "DISCONNECT"}))
        results = LineBuffer().feed(wire)
        self.assertEqual(len(results), 5)
        for item in results[:4]:
            self.assertIsInstance(item, MalformedLine)
        self.assertEqual(results[4], {"type": "DISCONNECT"})

    def test_utf8_round_trip(self):
        msg = {"type": "LOBBY_WAIT", "message": "Pokémon"}
        self.assertEqual(LineBuffer().feed(encode(msg)), [msg])


if __name__ == "__main__":
    unittest.main()
