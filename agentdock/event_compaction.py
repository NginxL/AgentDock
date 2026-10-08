"""Remove replay deltas only when a later authoritative record preserves them."""

import json


class EventCompaction:
    def compact_run_events(self, run_id):
        with self.reader() as reader:
            run = reader._one("runs", run_id)
            if run["status"] in ("running", "queued"):
                return 0
            rows = reader.db.execute(
                "SELECT id,seq,kind,payload FROM events WHERE json_extract(payload,'$.run_id')=? ORDER BY seq",
                (run_id,),
            ).fetchall()
        completed = {}
        chunks = []
        for row in rows:
            payload = json.loads(row["payload"])
            item = payload.get("item") or {}
            identifier = (
                payload.get("item_id") or item.get("id") or item.get("tool_use_id")
            )
            if not identifier:
                continue
            identity = (payload.get("provider"), identifier, payload.get("part", 0))
            kind = row["kind"]
            if kind in ("agent_message", "reasoning_message"):
                completed[(kind, *identity)] = row["seq"]
            elif kind == "tool_result" and any(
                key in item
                for key in ("aggregatedOutput", "content", "result", "output")
            ):
                completed[(kind, *identity)] = row["seq"]
            elif kind in ("agent_message_chunk", "reasoning_chunk", "tool_output"):
                final = {
                    "agent_message_chunk": "agent_message",
                    "reasoning_chunk": "reasoning_message",
                    "tool_output": "tool_result",
                }[kind]
                chunks.append((row["id"], row["seq"], (final, *identity)))
        obsolete = [
            (identifier,)
            for identifier, seq, identity in chunks
            if completed.get(identity, -1) > seq
        ]
        if obsolete:
            with self.transaction():
                self.db.executemany("DELETE FROM events WHERE id=?", obsolete)
        return len(obsolete)
