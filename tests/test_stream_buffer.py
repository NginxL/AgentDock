import threading
import unittest

from agentdock.stream_buffer import StreamBuffer


class StreamBufferTests(unittest.TestCase):
    def test_order_final_flush_and_bounded_deltas(self):
        events = []
        buffer = StreamBuffer(lambda *args: events.append(args), interval=10)
        for _ in range(1000):
            buffer.push(
                "agent_message_chunk",
                {"item_id": "one", "content": {"type": "text", "text": "你"}},
            )
        buffer.push("tool_call", {"name": "fixture"})
        buffer.push(
            "agent_message_chunk",
            {"item_id": "two", "content": {"type": "text", "text": "Final"}},
        )
        buffer.push("assistant_message", {"text": "Final"})
        buffer.close()
        self.assertEqual(
            [e[0] for e in events],
            [
                "agent_message_chunk",
                "tool_call",
                "agent_message_chunk",
                "assistant_message",
            ],
        )
        self.assertEqual(events[0][1]["content"]["text"], "你" * 1000)

    def test_last_delta_is_visible_without_waiting_for_another_event(self):
        received = threading.Event()
        buffer = StreamBuffer(lambda *_: received.set(), interval=0.02)
        buffer.push("reasoning_chunk", {"text": "A visible progress summary"})
        self.assertTrue(received.wait(0.5))
        buffer.close()
