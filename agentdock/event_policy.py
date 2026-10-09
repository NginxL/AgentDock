"""Control, accounting and final messages must survive progress truncation."""

ESSENTIAL_KINDS = frozenset(
    {
        "token_usage",
        "account_rate_limit",
        "input_receipt",
        "input_control",
        "model_info",
        "assistant_message",
        "remote_bind",
        "remote_tool",
        "remote_approval",
    }
)


def essential(kind, payload):
    return kind in ESSENTIAL_KINDS or (
        kind == "agent_message" and payload.get("phase") == "final_answer"
    )
