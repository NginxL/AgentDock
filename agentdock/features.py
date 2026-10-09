"""Explicit opt-in boundaries for integrations awaiting native acceptance."""

import json

from .errors import Conflict, Forbidden, Invalid

FEATURES = ("automatic_failover", "native_switching", "acp_agents")


class FeatureStore:
    def features(self):
        with self.lock:
            row = self.db.execute(
                "SELECT value FROM metadata WHERE key='experimental_features'"
            ).fetchone()
            stored = json.loads(row[0]) if row else {}
            return {name: stored.get(name) is True for name in FEATURES}

    def require_feature(self, name):
        if not self.features().get(name, False):
            error = Forbidden(
                "Enable this experimental feature in account settings first"
            )
            error.code = "experimental_disabled"
            raise error

    def set_feature(self, name, enabled, acknowledged=False):
        if name not in FEATURES or type(enabled) is not bool:
            raise Invalid("Invalid experimental feature")
        if enabled and acknowledged is not True:
            raise Invalid(
                "Review and acknowledge the experimental feature limitations first"
            )
        with self.transaction():
            settings = self.features()
            if (
                not enabled
                and settings[name]
                and self.db.execute(
                    "SELECT 1 FROM runs WHERE status IN ('queued','running') LIMIT 1"
                ).fetchone()
            ):
                raise Conflict(
                    "Stop queued and active tasks before disabling an experimental feature"
                )
            settings[name] = enabled
            self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES('experimental_features',?)",
                (json.dumps(settings),),
            )
            return settings
