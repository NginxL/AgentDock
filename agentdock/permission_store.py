"""PermissionStore domain operations; mutations share the owning Store transaction."""
from __future__ import annotations
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone



from .errors import Invalid, Conflict, Forbidden, now


class PermissionStore:
    def create_approval(self, run_id, request, options):
        if not isinstance(options,list) or not 1<=len(options)<=20 or any(not isinstance(x,dict) or not isinstance(x.get("optionId"),str) for x in options): raise Invalid("Invalid permission options")
        if len({x["optionId"] for x in options})!=len(options): raise Invalid("Duplicate permission option")
        with self.transaction():
            run=self._one("runs",run_id)
            if run["status"]!="running": raise Conflict("Run is no longer active")
            a=dict(id=str(uuid.uuid4()),run_id=run_id,session_id=run["session_id"],project_id=run["project_id"],request=json.dumps(request),options=json.dumps(options),status="pending",picked_option_id=None,created_at=now())
            self.db.execute("INSERT INTO approvals VALUES(:id,:run_id,:session_id,:project_id,:request,:options,:status,:picked_option_id,:created_at)",a)
            self._event(run["project_id"],run["session_id"],"approval_required",{"approval_id":a["id"],"run_id":run_id})
            return self._one("approvals",a["id"])


    def resolve_approval(self, identifier, option_id):
        with self.transaction():
            a=self._one("approvals",identifier)
            if a["status"]!="pending" or self._one("runs",a["run_id"])["status"]!="running": raise Conflict("Permission request is no longer pending")
            if option_id not in [x["optionId"] for x in a["options"]]: raise Invalid("Unknown permission option")
            self.db.execute("UPDATE approvals SET status='resolved',picked_option_id=? WHERE id=?",(option_id,identifier))
            self._event(a["project_id"],a["session_id"],"approval_resolved",{"approval_id":identifier,"option_id":option_id,"run_id":a["run_id"]})
            return self._one("approvals",identifier)


    def issue_capability(self, run_id, lifetime=3600):
        if not isinstance(lifetime, (int, float)) or not 1 <= lifetime <= 172800:
            raise Invalid('Invalid capability lifetime')
        token=secrets.token_urlsafe(32)
        with self.transaction():
            if self._one("runs",run_id)["status"]!="running": raise Forbidden("Run is not active")
            expires=(datetime.now(timezone.utc)+timedelta(seconds=lifetime)).isoformat(timespec="seconds")
            self.db.execute("INSERT INTO capabilities VALUES(?,?,?,0)",(hashlib.sha256(token.encode()).hexdigest(),run_id,expires))
        return token


    def revoke_capabilities(self, run_id):
        with self.transaction(): self.db.execute("UPDATE capabilities SET revoked=1 WHERE run_id=?",(run_id,))


    def _cap_run(self, token):
        if not isinstance(token,str) or len(token)>200: raise Forbidden("Invalid capability")
        cap=self.db.execute("SELECT * FROM capabilities WHERE hash=?",(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not cap or cap["revoked"] or cap["expires_at"]<=now(): raise Forbidden("Expired or invalid capability")
        run=self._one("runs",cap["run_id"])
        if run["status"]!="running": raise Forbidden("Run is not active")
        return run


    def capability_run(self, token):
        with self.lock: return self._cap_run(token)

