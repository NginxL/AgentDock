"""FTS5 substring index with a literal fallback for short queries/builds."""

import sqlite3


class MemorySearch:
    def _migrate_memory_search(self):
        # Trigram preserves the existing substring behavior, including Chinese.
        # Very short queries cannot use trigram and retain the bounded fallback.
        with self.transaction():
            try:
                self.db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(key,content,content='memories',content_rowid='rowid',tokenize='trigram')"
                )
            except sqlite3.OperationalError as error:
                if "no such module" not in str(
                    error
                ) and "no such tokenizer" not in str(error):
                    raise
                return
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memories BEGIN INSERT INTO memory_fts(rowid,key,content) VALUES(new.rowid,new.key,new.content); END"
            )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memories BEGIN INSERT INTO memory_fts(memory_fts,rowid,key,content) VALUES('delete',old.rowid,old.key,old.content); END"
            )
            self.db.execute(
                "CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE ON memories BEGIN INSERT INTO memory_fts(memory_fts,rowid,key,content) VALUES('delete',old.rowid,old.key,old.content); INSERT INTO memory_fts(rowid,key,content) VALUES(new.rowid,new.key,new.content); END"
            )
            self.db.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

    def search_memory(self, project_id, query):
        with self.lock:
            indexed = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='memory_fts'"
            ).fetchone()
            if len(query.strip()) >= 3 and indexed:
                literal = '"' + query.replace('"', '""') + '"'
                return self._all(
                    """SELECT memories.* FROM memory_fts JOIN memories ON memories.rowid=memory_fts.rowid
                    WHERE memory_fts MATCH ? AND project_id=? AND archived=0 ORDER BY rank LIMIT 20""",
                    (literal, project_id),
                )
            return self._all(
                """SELECT * FROM memories WHERE project_id=? AND archived=0
                AND (instr(lower(key),lower(?))>0 OR instr(lower(content),lower(?))>0)
                ORDER BY updated_at DESC LIMIT 20""",
                (project_id, query, query),
            )
