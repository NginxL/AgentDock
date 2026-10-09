import unittest

from agentdock.text_buffer import TEXT_LIMIT, TRUNCATED, TextBuffer, bounded_text


class TextBufferTests(unittest.TestCase):
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
        buffer = TextBuffer()
        chunks = ["你好🌟" * 1111 for _ in range(100)] + ["FINAL CONCLUSION"]
        for chunk in chunks:
            buffer.append(chunk)
            self.assertLessEqual(len(buffer.text().encode()), TEXT_LIMIT)
        self.assertEqual(buffer.text(), bounded_text("".join(chunks)))
        self.assertTrue(buffer.text().endswith("FINAL CONCLUSION"))
