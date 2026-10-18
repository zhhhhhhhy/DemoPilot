"""SQLite-authoritative revision/lease checked release of immutable artifacts.

Files are staged before BEGIN IMMEDIATE; only the committed DB pointer is
servable. Interrupted staging can leave an unreferenced directory, never a
half-published release. This is a single-machine design, not a distributed DB.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .quotation_browser import tree_hash


class ReleaseRejected(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ReleaseRegistry:
    def __init__(self, root, *, require_business=True):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.db = self.root / "release.sqlite3"
        with self.transaction() as con:
            schema = """
            CREATE TABLE IF NOT EXISTS policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),business_required INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS intents(project TEXT PRIMARY KEY,revision INTEGER NOT NULL,contract_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project TEXT NOT NULL,revision INTEGER NOT NULL,token TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(project,revision));
            CREATE TABLE IF NOT EXISTS checks(id TEXT PRIMARY KEY,job TEXT NOT NULL,artifact TEXT NOT NULL,kind TEXT NOT NULL,passed INTEGER NOT NULL,report TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS releases(project TEXT PRIMARY KEY,revision INTEGER NOT NULL,artifact TEXT NOT NULL,job TEXT NOT NULL,check_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS release_history(project TEXT NOT NULL,revision INTEGER NOT NULL,artifact TEXT NOT NULL,job TEXT NOT NULL,check_id TEXT NOT NULL,PRIMARY KEY(project,revision));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
            """
            for statement in schema.split(";"):
                if statement.strip():
                    con.execute(statement)
            con.execute("INSERT OR IGNORE INTO policy VALUES(1,?)", (int(require_business),))
            if con.execute("SELECT business_required FROM policy").fetchone()[0] != int(
                require_business
            ):
                raise ReleaseRejected(
                    "Cannot silently weaken or change an existing registry policy"
                )
        self.require_business = require_business

    @contextmanager
    def transaction(self):
        con = sqlite3.connect(self.db, timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            yield con
            if con.in_transaction:
                con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _event(self, con, kind, payload):
        con.execute(
            "INSERT INTO events(time,kind,payload) VALUES(?,?,?)",
            (datetime.now(UTC).isoformat(), kind, json.dumps(payload, ensure_ascii=False)),
        )

    def set_intent(self, project, revision, contract):
        if not project or revision < 1:
            raise ReleaseRejected("Invalid project/revision")
        digest = canonical_hash(contract)
        with self.transaction() as con:
            prior = con.execute("SELECT * FROM intents WHERE project=?", (project,)).fetchone()
            if prior and (
                revision < prior["revision"]
                or revision == prior["revision"]
                and digest != prior["contract_hash"]
            ):
                raise ReleaseRejected("Intent revision must be monotonic and immutable")
            if prior and revision == prior["revision"]:
                return digest
            con.execute("INSERT OR REPLACE INTO intents VALUES(?,?,?)", (project, revision, digest))
            con.execute(
                "UPDATE jobs SET status='superseded' WHERE project=? AND revision<? AND status='running'",
                (project, revision),
            )
            self._event(
                con, "intent_changed", dict(project=project, revision=revision, hash=digest)
            )
        return digest

    def claim(self, project, revision, job_id):
        with self.transaction() as con:
            current = con.execute(
                "SELECT revision FROM intents WHERE project=?", (project,)
            ).fetchone()
            if not current or current[0] != revision:
                raise ReleaseRejected("Stale requirement revision")
            existing = con.execute(
                "SELECT * FROM jobs WHERE project=? AND revision=?", (project, revision)
            ).fetchone()
            if existing:
                if existing["id"] == job_id:
                    return dict(existing)
                raise ReleaseRejected("Another job already owns this intent revision")
            token = secrets.token_hex(24)
            con.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?)", (job_id, project, revision, token, "running")
            )
            self._event(con, "claimed", dict(project=project, revision=revision, job=job_id))
            return dict(
                id=job_id, project=project, revision=revision, token=token, status="running"
            )

    def record_check(self, job_id, token, artifact_hash, report, *, kind="business"):
        with self.transaction() as con:
            job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["token"] != token or job["status"] != "running":
                raise ReleaseRejected("Invalid or terminal job lease")
            if report.get("source_sha256") != artifact_hash:
                raise ReleaseRejected("Check not bound to exact artifact bytes")
            passed = report.get("status") == "passed" and report.get("source_unchanged") is True
            if kind == "business":
                passed = (
                    passed
                    and report.get("planned_journeys", 0) > 0
                    and report.get("planned_journeys")
                    == report.get("executed_journeys")
                    == report.get("passed_journeys")
                )
            check_id = canonical_hash(
                dict(job=job_id, artifact=artifact_hash, report=report, kind=kind)
            )
            con.execute(
                "INSERT OR IGNORE INTO checks VALUES(?,?,?,?,?,?)",
                (
                    check_id,
                    job_id,
                    artifact_hash,
                    kind,
                    int(passed),
                    json.dumps(report, ensure_ascii=False),
                ),
            )
            self._event(
                con, "checked", dict(job=job_id, check=check_id, passed=bool(passed), kind=kind)
            )
            return check_id

    def publish(self, job_id, token, check_id, source):
        source = Path(source).resolve()
        digest = tree_hash(source)
        target = self.artifacts / digest
        if not target.exists():
            # A unique temporary directory prevents concurrent copy collisions.
            staging = self.artifacts / (".stage-" + secrets.token_hex(12))
            shutil.copytree(source, staging)
            if tree_hash(staging) != digest:
                raise ReleaseRejected("Source changed while staging")
            try:
                if not staging.resolve().is_relative_to(
                    self.artifacts.resolve()
                ) or not target.resolve().is_relative_to(self.artifacts.resolve()):
                    raise ReleaseRejected("Staging path escaped the owned artifact directory")
                staging.rename(target)
            except FileExistsError:
                if not staging.resolve().is_relative_to(self.artifacts.resolve()):
                    raise ReleaseRejected(
                        "Refusing cleanup outside the owned artifact directory"
                    ) from None
                shutil.rmtree(staging)
        if tree_hash(target) != digest:
            raise ReleaseRejected("Previously staged immutable artifact was tampered")
        with self.transaction() as con:
            job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job["token"] != token:
                raise ReleaseRejected("Invalid job lease")
            current = con.execute(
                "SELECT revision FROM intents WHERE project=?", (job["project"],)
            ).fetchone()
            check = con.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
            if not current or current[0] != job["revision"]:
                raise ReleaseRejected("New requirements superseded this build")
            if (
                not check
                or check["job"] != job_id
                or check["artifact"] != digest
                or not check["passed"]
            ):
                raise ReleaseRejected("Artifact did not pass its exact acceptance check")
            if self.require_business and check["kind"] != "business":
                raise ReleaseRejected("Business acceptance required")
            prior = con.execute(
                "SELECT * FROM releases WHERE project=?", (job["project"],)
            ).fetchone()
            if (
                job["status"] == "published"
                and prior
                and prior["job"] == job_id
                and prior["artifact"] == digest
            ):
                return dict(prior)  # retry is idempotent
            if job["status"] != "running":
                raise ReleaseRejected("Terminal job cannot publish")
            release = dict(
                project=job["project"],
                revision=job["revision"],
                artifact=digest,
                job=job_id,
                check_id=check_id,
            )
            con.execute(
                "INSERT OR REPLACE INTO releases VALUES(:project,:revision,:artifact,:job,:check_id)",
                release,
            )
            con.execute(
                "INSERT INTO release_history VALUES(:project,:revision,:artifact,:job,:check_id)",
                release,
            )
            con.execute("UPDATE jobs SET status='published' WHERE id=?", (job_id,))
            self._event(con, "published", release)
            return release

    def fail(self, job_id, token, reason):
        with self.transaction() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["token"] != token:
                raise ReleaseRejected("Invalid job lease")
            if row["status"] == "running":
                con.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
            self._event(con, "failed", dict(job=job_id, reason=reason))

    def resolve(self, project):
        with self.transaction() as con:
            row = con.execute(
                "SELECT r.* FROM releases r JOIN intents i ON i.project=r.project AND i.revision=r.revision WHERE r.project=?",
                (project,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        path = self.artifacts / result["artifact"]
        if not path.is_dir() or tree_hash(path) != result["artifact"]:
            raise ReleaseRejected("Released artifact missing or tampered")
        result["path"] = str(path)
        return result

    def snapshot(self):
        with self.transaction() as con:
            return {
                t: [dict(row) for row in con.execute("SELECT * FROM " + t)]
                for t in ("intents", "jobs", "releases", "events")
            }

    def resolve_accepted_bundle(self, project, revision, digest):
        """Historical accepted URLs stay pinned; current-intent URLs stay fresh."""
        with self.transaction() as con:
            row = con.execute(
                "SELECT * FROM release_history WHERE project=? AND revision=? AND artifact=?",
                (project, revision, digest),
            ).fetchone()
        if not row:
            return None
        path = self.artifacts / digest
        if not path.is_dir() or tree_hash(path) != digest:
            raise ReleaseRejected("Accepted bundle missing or tampered")
        return dict(row, path=str(path))
