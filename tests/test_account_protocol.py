import unittest

from agentdock.providers import (
    ProviderError,
    _Callbacks,
    _Claude,
    _Codex,
    account_error,
)


class Pipe:
    def __init__(self, rows=()):
        self.rows = iter(rows)
        self.sent = []

    def next(self):
        return next(self.rows)

    def send(self, message):
        self.sent.append(message)


class AccountProtocolTests(unittest.TestCase):
    def test_only_structured_rejection_codes_enable_failover(self):
        for payload, code in [
            ({"error": {"codexErrorInfo": "usageLimitExceeded"}}, "quota_exhausted"),
            (
                {
                    "data": {
                        "codexErrorInfo": {
                            "httpConnectionFailed": {"httpStatusCode": 401}
                        }
                    }
                },
                "auth_expired",
            ),
            ({"error": "rate_limit"}, "rate_limited"),
            ({"error": {"type": "authentication_error"}}, "auth_expired"),
        ]:
            with self.subTest(payload=payload):
                error = account_error(payload, "safe")
                self.assertEqual(error.code, code)
                self.assertTrue(error.rejected)
        for payload in (
            {"message": "usageLimitExceeded secret-token"},
            {"code": 403},
            {"error": {"codexErrorInfo": "sandboxError"}},
            {"error": "Tool returned rate_limit"},
        ):
            error = account_error(payload, "safe")
            self.assertIsNone(error.code)
            self.assertFalse(error.rejected)
            self.assertEqual(str(error), "safe")

    def test_codex_error_notifications_preserve_safe_code_not_raw_message(self):
        pipe = Pipe()
        adapter = _Codex(
            pipe,
            _Callbacks(pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}),
        )
        with self.assertRaises(ProviderError) as caught:
            adapter.handle(
                {
                    "method": "error",
                    "params": {
                        "willRetry": False,
                        "error": {
                            "message": "private-token",
                            "codexErrorInfo": "rateLimitExceeded",
                            "retryAfterSeconds": 12,
                        },
                    },
                }
            )
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertEqual(caught.exception.retry_after, 12)
        self.assertNotIn("private-token", str(caught.exception))

    def test_claude_rejected_limit_stops_before_any_assistant_error_is_rendered(self):
        pipe = Pipe(
            [
                {
                    "type": "control_response",
                    "response": {
                        "request_id": "agentdock_initialize",
                        "subtype": "success",
                        "response": {},
                    },
                },
                {
                    "type": "rate_limit_event",
                    "rate_limit_info": {
                        "status": "rejected",
                        "rateLimitType": "five_hour",
                    },
                },
            ]
        )
        events = []
        adapter = _Claude(
            pipe,
            _Callbacks(
                pipe,
                lambda k, p: events.append((k, p)),
                lambda *a: None,
                lambda *a: None,
                {},
            ),
            "native",
        )
        with self.assertRaises(ProviderError) as caught:
            adapter.run("Prompt")
        self.assertEqual(caught.exception.code, "quota_exhausted")
        self.assertEqual([k for k, _ in events], ["account_rate_limit"])


if __name__ == "__main__":
    unittest.main()
