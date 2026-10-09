import json
import unittest

from agentdock.text_buffer import TEXT_LIMIT, TRUNCATED, TextBuffer, bounded_text


class TextBufferTests(unittest.TestCase):
    def test_escaped_reply_fits_the_event_budget_and_keeps_its_conclusion(self):
        for content in (
            '{"id": "a1", "name": "item", "tags": ["x", "y"]}\n' * 2400,
            "\x01" * 119000,
            ('"\\' + "".join(chr(i) for i in range(32)) + "中文🌟") * 5000,
        ):
            with self.subTest(prefix=repr(content[:10])):
                reply = content + "FINAL CONCLUSION"
                bounded = bounded_text(reply)
                self.assertTrue(bounded.endswith("FINAL CONCLUSION"))
                self.assertEqual(bounded.count(TRUNCATED), 1)
                self.assertEqual(bounded_text(bounded), bounded)
                self.assertLessEqual(
                    len(json.dumps(bounded, ensure_ascii=False).encode()) - 2,
                    TEXT_LIMIT,
                )
                payload = {
                    "run_id": "r" * 36,
                    "provider": "claude",
                    "item_id": "i" * 256,
                    "part": 0,
                    "phase": "final_answer",
                    "content": {"type": "text", "text": bounded},
                }
                self.assertLessEqual(
                    len(json.dumps(payload, ensure_ascii=False).encode()), 131072
                )

    def test_escaped_boundary_preserves_exactly_fitting_text(self):
        for char, width in (
            ("x", 1),
            ('"', 2),
            ("\\", 2),
            ("\n", 2),
            ("\x01", 6),
            ("中", 3),
        ):
            with self.subTest(char=repr(char)):
                reply = char * (TEXT_LIMIT // width)
                self.assertEqual(bounded_text(reply), reply)
                bounded = bounded_text(reply + "!")
                self.assertTrue(bounded.startswith(TRUNCATED))
                self.assertTrue(bounded.endswith("!"))

    def test_final_bound_is_idempotent_and_preserves_unicode_tail(self):
        for reply in (
            "A" * 60000 + "B" * 30000 + "CONCLUSION",
            "A" * 150000 + "CONCLUSION",
            "长回复" * 30000 + "结论 CONCLUSION",
            "x" * TEXT_LIMIT,
        ):
            with self.subTest(length=len(reply)):
                bounded = bounded_text(reply)
                self.assertLessEqual(len(bounded.encode()), TEXT_LIMIT)
                self.assertEqual(bounded_text(bounded), bounded)
                if len(reply.encode()) <= TEXT_LIMIT:
                    self.assertEqual(bounded, reply)
                else:
                    self.assertEqual(bounded.count(TRUNCATED), 1)
                    self.assertTrue(bounded.endswith("CONCLUSION"))

    def test_incremental_and_complete_messages_have_the_same_bound(self):
        for chunk in ("你好🌟" * 1111, '"\\\x01\b\n' * 400):
            with self.subTest(prefix=repr(chunk[:10])):
                buffer = TextBuffer()
                chunks = [chunk] * 100 + ["FINAL CONCLUSION"]
                for part in chunks:
                    buffer.append(part)
                    self.assertLessEqual(len(buffer.text().encode()), TEXT_LIMIT)
                self.assertEqual(buffer.text(), bounded_text("".join(chunks)))
                self.assertTrue(buffer.text().endswith("FINAL CONCLUSION"))
