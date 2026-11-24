import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT, source BLOB
);"""

LEDGER = """CREATE TABLE IF NOT EXISTS compensation_ledger (
    compensation TEXT PRIMARY KEY, customer TEXT NOT NULL, period TEXT NOT NULL,
    run_id TEXT NOT NULL, offset_cents INTEGER NOT NULL, settled_cents INTEGER NOT NULL,
    recorded TEXT NOT NULL
);"""


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute(SCHEMA)
            db.execute(LEDGER)
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(runs)")
            }
            if "source" not in columns:
                try:
                    db.execute("ALTER TABLE runs ADD COLUMN source BLOB")
                except sqlite3.OperationalError:
                    pass  # 另一连接已补列
            yield db

    def register(self, run_id, report, source=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO runs(id,report,created,source) VALUES (?,?,?,?)"
                " ON CONFLICT(id) DO NOTHING",
                (
                    run_id,
                    json.dumps(report, ensure_ascii=False),
                    report["manifest"]["created"],
                    source,
                ),
            )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result.pop("source", None)
        result["report"] = json.loads(result["report"])
        return result

    def source(self, run_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT source FROM runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        return row["source"]

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def ledger(self, compensation_ids):
        """查询已签发的补偿编号，返回 {编号: 签发批次}。"""
        wanted = sorted(set(compensation_ids))
        if not wanted:
            return {}
        marks = ",".join("?" for _ in wanted)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT compensation,run_id FROM compensation_ledger WHERE compensation IN ({marks})",
                wanted,
            ).fetchall()
        return {row["compensation"]: row["run_id"] for row in rows}

    def refresh(self, run_id, report):
        """用当前台账重算未签发批次，保留原清单与复核状态。"""
        with self.connect() as db:
            db.execute(
                "UPDATE runs SET report=? WHERE id=? AND status!='APPROVED'",
                (json.dumps(report, ensure_ascii=False), run_id),
            )
        return self.load(run_id)

    def revise(self, run_id, revision, status, note, now, report=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT report,status FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise DomainIssue("RUN_NOT_FOUND")
            if row["status"] == "APPROVED":
                raise DomainIssue("RUN_FINALIZED")
            stored = json.dumps(report, ensure_ascii=False) if report else row["report"]
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1,report=?"
                " WHERE id=? AND revision=?",
                (status, note, now, stored, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
            if status == "APPROVED":
                self._post(db, run_id, json.loads(stored), now)
        return self.load(run_id)

    @staticmethod
    def _post(db, run_id, report, now):
        if report.get("kind") != "compensation":
            return
        for item in report.get("treatments", []):
            if item["treatment"] not in ("APPLIED", "SETTLED"):
                continue
            try:
                db.execute(
                    "INSERT INTO compensation_ledger"
                    "(compensation,customer,period,run_id,offset_cents,settled_cents,recorded)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        item["compensation"],
                        item["customer"],
                        item["period"],
                        run_id,
                        item["offset_cents"],
                        item["settled_cents"],
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise DomainIssue("COMPENSATION_ALREADY_POSTED") from error

    def ledger_entries(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM compensation_ledger ORDER BY recorded,compensation"
                )
            ]
