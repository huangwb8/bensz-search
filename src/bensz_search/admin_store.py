"""Small durable identity/configuration store; secrets never enter public records."""

import base64
import hashlib
import hmac
import json
import queue
import secrets
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet

from .usage import SUCCESS, add, aggregate, merge, summary


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ":" + hashed


def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(":", 1)[0]), encoded)


class AdminStore:
    def __init__(self, path, encryption_secret):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.observation_lock = threading.Lock()
        self.timings = {
            "lock_wait_ms": deque(maxlen=512),
            "sqlite_wait_ms": deque(maxlen=512),
            "transaction_ms": deque(maxlen=512),
        }
        self.last_maintenance = 0
        self.readers = queue.LifoQueue(maxsize=4)
        self.reader_connections = []
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(encryption_secret.encode()).digest()))
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))
        # A concurrent startup may get immediate SQLITE_BUSY while switching WAL,
        # even though ordinary SQL honors the connection's busy timeout.
        deadline = time.monotonic() + 5
        while True:
            try:
                self.db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as error:
                if (
                    not any(word in str(error).lower() for word in ("locked", "busy"))
                    or time.monotonic() >= deadline
                ):
                    self.db.close()
                    raise
                time.sleep(0.025)
        with self.db:
            self.db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL, role TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf TEXT NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS providers (
                    name TEXT PRIMARY KEY, config TEXT NOT NULL, secret TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_keys (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, token TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL,
                    created_at REAL NOT NULL, last_used_at REAL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        self.db.execute("PRAGMA busy_timeout=5000")
        self._migrate()
        # A changed encryption secret must fail at startup, never silently lose credentials.
        with self.transaction():
            check = self.db.execute("SELECT value FROM meta WHERE name='encryption_check'").fetchone()
            if check:
                if self.cipher.decrypt(check[0].encode()) != b"bensz-search":
                    raise ValueError("Invalid encryption secret")
            else:
                self.db.execute(
                    "INSERT INTO meta VALUES ('encryption_check', ?)",
                    (self.cipher.encrypt(b"bensz-search").decode(),),
                )

        for _ in range(4):
            connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA query_only=ON")
            self.reader_connections.append(connection)
            self.readers.put(connection)

    @contextmanager
    def read(self):
        # Nested reads inside a writer transaction must see its uncommitted work.
        if self.lock._is_owned():
            yield self.db
            return
        connection = self.readers.get()
        try:
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            self.readers.put(connection)

    @contextmanager
    def transaction(self):
        started = time.monotonic()
        with self.lock:
            acquired = time.monotonic()
            try:
                with self.db:
                    if not self.db.in_transaction:
                        self.db.execute("BEGIN IMMEDIATE")
                    begun = time.monotonic()
                    with self.observation_lock:
                        self.timings["sqlite_wait_ms"].append((begun - acquired) * 1000)
                    yield
            finally:
                with self.observation_lock:
                    self.timings["lock_wait_ms"].append((acquired - started) * 1000)
                    self.timings["transaction_ms"].append((time.monotonic() - acquired) * 1000)

    def performance(self):
        with self.observation_lock:
            return {
                name: {
                    "samples": len(rows),
                    "max": max(rows, default=0),
                    "p95": sorted(rows)[int((len(rows) - 1) * 0.95)] if rows else 0,
                }
                for name, rows in self.timings.items()
            }

    def _migrate(self):
        """Additive, idempotent migrations; preserve all existing credentials and identities."""
        additions = {
            "users": {"enabled": "INTEGER NOT NULL DEFAULT 1"},
            "sessions": {"id": "TEXT", "created_at": "REAL"},
            "access_keys": {
                "expires_at": "REAL",
                "scopes": 'TEXT NOT NULL DEFAULT \'["search","protocol"]\'',
                "usage_count": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        with self.transaction():
            for table, columns in additions.items():
                existing = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
                for name, declaration in columns.items():
                    if name not in existing:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            for row in self.db.execute("SELECT token,expires_at FROM sessions WHERE id IS NULL").fetchall():
                self.db.execute(
                    "UPDATE sessions SET id=?,created_at=? WHERE token=?",
                    (secrets.token_hex(16), row["expires_at"] - 43200, row["token"]),
                )
            statements = """
                CREATE UNIQUE INDEX IF NOT EXISTS session_public_id ON sessions(id);
                CREATE INDEX IF NOT EXISTS session_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS key_user_created ON access_keys(user_id,created_at DESC);
                CREATE INDEX IF NOT EXISTS key_name ON access_keys(name COLLATE NOCASE,id);
                CREATE INDEX IF NOT EXISTS user_name ON users(username COLLATE NOCASE,id);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, actor_id INTEGER,
                    action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_time ON audit_events(timestamp);
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day TEXT NOT NULL, provider TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (day,provider)
                );
                CREATE TABLE IF NOT EXISTS user_usage_daily (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    day TEXT NOT NULL, provider TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (user_id,day,provider)
                );
                CREATE INDEX IF NOT EXISTS user_usage_day ON user_usage_daily(day);
            """
            for statement in statements.split(";"):
                if statement.strip():
                    self.db.execute(statement)

    def system_settings(self):
        from .settings import DEFAULT_SITE

        with self.read() as db:
            row = db.execute("SELECT value FROM meta WHERE name='system_settings'").fetchone()
            return {**DEFAULT_SITE, "revision": 0, **(json.loads(row[0]) if row else {})}

    def save_system_settings(self, fields, expected_revision, actor_id):
        with self.transaction():
            current = self.system_settings()
            if current["revision"] != expected_revision:
                raise ValueError("System settings changed; reload before saving")
            saved = {**fields, "revision": current["revision"] + 1}
            self.db.execute(
                "INSERT INTO meta(name,value) VALUES ('system_settings',?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (json.dumps(saved),),
            )
            self._audit(actor_id, "update", "system_settings", "site")
            return saved

    def _audit(self, actor_id, action, object_type, object_id):
        if actor_id is not None:
            self.db.execute(
                "INSERT INTO audit_events(timestamp,actor_id,action,object_type,object_id) VALUES (?,?,?,?,?)",
                (time.time(), actor_id, action, object_type, str(object_id)),
            )

    def bootstrap(self, username, password):
        hashed = password_hash(password)
        with self.transaction():
            if not self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                self.db.execute(
                    "INSERT INTO users(username,password,role,created_at) VALUES (?,?,'admin',?)",
                    (username, hashed, time.time()),
                )

    def create_user(self, username, password, role, actor_id=None):
        hashed = password_hash(password)
        with self.transaction():
            cursor = self.db.execute(
                "INSERT INTO users(username,password,role,created_at) VALUES (?,?,?,?)",
                (username, hashed, role, time.time()),
            )
            self._audit(actor_id, "create", "user", cursor.lastrowid)
            return {"id": cursor.lastrowid, "username": username, "role": role, "enabled": True}

    def users(self, limit=None, offset=0, query="", status="all", sort="name"):
        where, values = [], []
        if query:
            where.append("instr(lower(username), lower(?))>0")
            values.append(query)
        if status != "all":
            where.append("enabled=?")
            values.append(int(status == "active"))
        clause = " WHERE " + " AND ".join(where) if where else ""
        order = (
            {
                "name": "username COLLATE NOCASE,id",
                "name-desc": "username COLLATE NOCASE DESC,id",
                "newest": "created_at DESC,id DESC",
            }[sort]
            if limit is not None
            else "id"
        )
        with self.read() as db:
            total = db.execute("SELECT count(*) FROM users" + clause, values).fetchone()[0]
            rows = db.execute(
                "SELECT id,username,role,created_at,enabled FROM users"
                + clause
                + " ORDER BY "
                + order
                + (" LIMIT ? OFFSET ?" if limit is not None else ""),
                (*values, limit, offset) if limit is not None else values,
            ).fetchall()
        records = [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]
        return (
            {"users": records, "total": total, "limit": limit, "offset": offset}
            if limit is not None
            else records
        )

    def _protect_admin(self, user_id, role=None, enabled=None, deleting=False):
        row = self.db.execute("SELECT role,enabled FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise KeyError("用户不存在")
        removing = deleting or role == "member" or enabled is False
        if row["role"] == "admin" and row["enabled"] and removing:
            count = self.db.execute("SELECT count(*) FROM users WHERE role='admin' AND enabled=1").fetchone()[
                0
            ]
            if count <= 1:
                raise ValueError("不能删除、停用或降级最后一个启用的管理员")
        return row

    def update_user(self, user_id, role=None, enabled=None, password=None, actor_id=None):
        hashed = password_hash(password) if password else None
        with self.transaction():
            # Take the SQLite writer lock before the count/check, also across workers.
            self.db.execute("UPDATE users SET enabled=enabled WHERE id=?", (user_id,))
            self._protect_admin(user_id, role, enabled)
            values = {
                k: v
                for k, v in {"role": role, "enabled": enabled, "password": hashed}.items()
                if v is not None
            }
            if values:
                self.db.execute(
                    "UPDATE users SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                    (*values.values(), user_id),
                )
                if enabled is False or hashed:
                    self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                self._audit(actor_id, "update", "user", user_id)
            row = self.db.execute(
                "SELECT id,username,role,created_at,enabled FROM users WHERE id=?", (user_id,)
            ).fetchone()
            return {**dict(row), "enabled": bool(row["enabled"])}

    def login(self, username, password):
        with self.read() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        valid = password_matches(password, row["password"] if row else self.dummy_hash)
        if not row or not valid or not row["enabled"]:
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now, expires = time.time(), time.time() + 43200
        with self.transaction():
            current = self.db.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not current or not current["enabled"] or current["password"] != row["password"]:
                return None
            self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            self.db.execute(
                "INSERT INTO sessions(token,user_id,csrf,expires_at,id,created_at) VALUES (?,?,?,?,?,?)",
                (digest(token), current["id"], csrf, expires, secrets.token_hex(16), now),
            )
            return token, {
                "user": {k: current[k] for k in ("id", "username", "role")},
                "csrf_token": csrf,
                "expires_at": expires,
            }

    def session(self, token):
        with self.read() as db:
            row = db.execute(
                "SELECT u.id,u.username,u.role,s.csrf,s.expires_at FROM sessions s JOIN users u ON s.user_id=u.id "
                "WHERE s.token=? AND s.expires_at>? AND u.enabled=1",
                (digest(token), time.time()),
            ).fetchone()
            return (
                {
                    "user": {k: row[k] for k in ("id", "username", "role")},
                    "csrf_token": row["csrf"],
                    "expires_at": row["expires_at"],
                }
                if row
                else None
            )

    def sessions(self, user_id, token):
        with self.read() as db:
            return [
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "current": hmac.compare_digest(r["token"], digest(token)),
                }
                for r in db.execute(
                    "SELECT id,token,created_at,expires_at FROM sessions WHERE user_id=? AND expires_at>? "
                    "ORDER BY created_at DESC",
                    (user_id, time.time()),
                )
            ]

    def revoke_other_sessions(self, user_id, token):
        with self.transaction():
            count = self.db.execute(
                "DELETE FROM sessions WHERE user_id=? AND token!=?", (user_id, digest(token))
            ).rowcount
            self._audit(user_id, "revoke_others", "session", user_id)
            return count

    def logout(self, token):
        with self.transaction():
            self.db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))

    def change_password(self, user_id, current, new):
        with self.read() as db:
            row = db.execute("SELECT password,enabled FROM users WHERE id=?", (user_id,)).fetchone()
        if not row or not row["enabled"] or not password_matches(current, row["password"]):
            return False
        hashed = password_hash(new)
        with self.transaction():
            changed = self.db.execute(
                "UPDATE users SET password=? WHERE id=? AND password=? AND enabled=1",
                (hashed, user_id, row["password"]),
            ).rowcount
            if not changed:
                return False
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self._audit(user_id, "change_password", "user", user_id)
            return True

    def delete_user(self, user_id, actor_id=None):
        with self.transaction():
            self.db.execute("UPDATE users SET enabled=enabled WHERE id=?", (user_id,))
            self._protect_admin(user_id, deleting=True)
            count = self.db.execute("DELETE FROM users WHERE id=?", (user_id,)).rowcount
            self._audit(actor_id, "delete", "user", user_id)
            return count

    def providers(self, private=False):
        with self.read() as db:
            records = []
            for row in db.execute("SELECT * FROM providers ORDER BY name"):
                config = json.loads(row["config"])
                config["has_api_key"] = bool(row["secret"])
                if private:
                    config["api_key"] = (
                        self.cipher.decrypt(row["secret"].encode()).decode() if row["secret"] else ""
                    )
                records.append(config)
            return records

    def save_provider(self, config, api_key=None, actor_id=None, expected=None):
        with self.transaction():
            name = config["name"]
            # Acquire the writer lock before a sync's compare-and-swap, across workers as well.
            self.db.execute("UPDATE providers SET name=name WHERE name=?", (name,))
            previous = self.db.execute("SELECT * FROM providers WHERE name=?", (name,)).fetchone()
            if expected is not None:
                current = json.loads(previous["config"]) if previous else None
                if current is not None:
                    current["has_api_key"] = bool(previous["secret"])
                    current["api_key"] = (
                        self.cipher.decrypt(previous["secret"].encode()).decode()
                        if previous["secret"]
                        else ""
                    )
                if current != expected:
                    raise ValueError("配置已变化，请重新同步")
            secret = previous["secret"] if previous else ""
            if api_key is not None:
                secret = self.cipher.encrypt(api_key.encode()).decode() if api_key else ""
            self.db.execute(
                "INSERT OR REPLACE INTO providers VALUES (?,?,?)", (name, json.dumps(config), secret)
            )
            self._audit(actor_id, "update" if previous else "create", "provider", name)

    def delete_provider(self, name, actor_id=None):
        with self.transaction():
            count = self.db.execute("DELETE FROM providers WHERE name=?", (name,)).rowcount
            if count:
                self._audit(actor_id, "delete", "provider", name)
            return count

    def import_providers(self, records, actor_id):
        with self.transaction():
            # INSERT (not REPLACE) makes conflicts roll back the complete import.
            for config in records:
                self.db.execute(
                    "INSERT INTO providers(name,config,secret) VALUES (?,?,'')",
                    (config["name"], json.dumps(config)),
                )
                self._audit(actor_id, "import", "provider", config["name"])

    def seed_providers(self, records):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM meta WHERE name='providers_seeded'").fetchone():
                return
            for record in records:
                record = dict(record)
                key = record.pop("api_key", "")
                encrypted = self.cipher.encrypt(key.encode()).decode() if key else ""
                self.db.execute(
                    "INSERT OR IGNORE INTO providers(name,config,secret) VALUES (?,?,?)",
                    (record["name"], json.dumps(record), encrypted),
                )
            self.db.execute("INSERT INTO meta VALUES ('providers_seeded','true')")

    def keys(self, user_id=None, limit=None, offset=0, query="", status="all", sort="name"):
        terms, values = [], []
        if user_id is not None:
            terms.append("k.user_id=?")
            values.append(user_id)
        owner = " WHERE " + " AND ".join(terms) if terms else ""
        owner_values = list(values)
        active = "k.revoked=0 AND (k.expires_at IS NULL OR k.expires_at>?)"
        if query:
            terms.append("instr(lower(k.name || ' ' || u.username), lower(?))>0")
            values.append(query)
        if status != "all":
            terms.append("(" + active + ")" if status == "active" else "NOT (" + active + ")")
            values.append(time.time())
        clause = " WHERE " + " AND ".join(terms) if terms else ""
        source = " FROM access_keys k JOIN users u ON u.id=k.user_id"
        order = (
            {
                "name": "k.name COLLATE NOCASE,k.id",
                "name-desc": "k.name COLLATE NOCASE DESC,k.id",
                "newest": "k.created_at DESC,k.id",
            }[sort]
            if limit is not None
            else "k.created_at DESC"
        )
        with self.read() as db:
            total = db.execute("SELECT count(*)" + source + clause, values).fetchone()[0]
            active_count = db.execute(
                "SELECT count(*)" + source + owner + (" AND " if owner else " WHERE ") + active,
                (*owner_values, time.time()),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT k.id,k.user_id,u.username,k.name,k.prefix,k.created_at,k.last_used_at,k.revoked,"
                "k.expires_at,k.scopes,k.usage_count"
                + source
                + clause
                + " ORDER BY "
                + order
                + (" LIMIT ? OFFSET ?" if limit is not None else ""),
                (*values, limit, offset) if limit is not None else values,
            ).fetchall()
        records = [{**dict(row), "scopes": json.loads(row["scopes"])} for row in rows]
        return (
            {"keys": records, "total": total, "active_count": active_count, "limit": limit, "offset": offset}
            if limit is not None
            else records
        )

    def create_key(self, user_id, name, expires_at=None, scopes=None):
        scopes = ["search", "protocol"] if scopes is None else scopes
        if not scopes or set(scopes) - {"search", "protocol"}:
            raise ValueError("密钥权限范围无效")
        if expires_at is not None and expires_at <= time.time():
            raise ValueError("过期时间必须在未来")
        key, record_id = "sk-bs-" + secrets.token_urlsafe(32), secrets.token_hex(12)
        now = time.time()
        with self.transaction():
            self.db.execute(
                "INSERT INTO access_keys(id,user_id,name,token,prefix,created_at,expires_at,scopes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (record_id, user_id, name, digest(key), key[:14], now, expires_at, json.dumps(scopes)),
            )
            self._audit(user_id, "create", "key", record_id)
            row = self.db.execute(
                "SELECT k.id,k.user_id,u.username,k.name,k.prefix,k.created_at,k.last_used_at,k.revoked,k.expires_at,k.scopes,k.usage_count FROM access_keys k JOIN users u ON u.id=k.user_id WHERE k.id=?",
                (record_id,),
            ).fetchone()
            record = {**dict(row), "scopes": json.loads(row["scopes"])}
        return {"key": key, "record": record}

    def revoke_key(self, user_id, key_id, actor_id=None):
        with self.transaction():
            where = " AND user_id=?" if user_id is not None else ""
            count = self.db.execute(
                "UPDATE access_keys SET revoked=1 WHERE id=?" + where,
                (key_id, user_id) if user_id is not None else (key_id,),
            ).rowcount
            if count:
                self._audit(actor_id if actor_id is not None else user_id, "revoke", "key", key_id)
            return count

    def delete_key(self, user_id, key_id, actor_id=None):
        with self.transaction():
            where = " AND user_id=?" if user_id is not None else ""
            count = self.db.execute(
                "DELETE FROM access_keys WHERE id=?" + where,
                (key_id, user_id) if user_id is not None else (key_id,),
            ).rowcount
            if count:
                self._audit(actor_id if actor_id is not None else user_id, "delete", "key", key_id)
            return count

    def authenticate_key(self, key, required_scope=None):
        with self.read() as db:
            row = db.execute(
                "SELECT k.id,u.id AS user_id,u.username,k.scopes FROM access_keys k JOIN users u ON k.user_id=u.id "
                "WHERE k.token=? AND k.revoked=0 AND u.enabled=1 AND (k.expires_at IS NULL OR k.expires_at>?)",
                (digest(key), time.time()),
            ).fetchone()
            if row is None:
                return None
            record = {**dict(row), "scopes": json.loads(row["scopes"])}
            if required_scope is not None and required_scope not in record["scopes"]:
                raise PermissionError("访问密钥不具备该接口的权限")
            return record

    def record_key_use(self, key_id):
        with self.transaction():
            self.db.execute(
                "UPDATE access_keys SET last_used_at=?,usage_count=usage_count+1 WHERE id=?",
                (time.time(), key_id),
            )

    def audit(self, actor_id=None, object_type=None, since=None, until=None, limit=100, offset=0):
        terms, values = [], []
        for field, op, value in (
            ("actor_id", "=", actor_id),
            ("object_type", "=", object_type),
            ("timestamp", ">=", since),
            ("timestamp", "<=", until),
        ):
            if value is not None:
                terms.append(f"{field}{op}?")
                values.append(value)
        where = " WHERE " + " AND ".join(terms) if terms else ""
        with self.read() as db:
            total = db.execute("SELECT count(*) FROM audit_events" + where, values).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM audit_events" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
            return {"events": [dict(r) for r in rows], "total": total}

    def record_usage(self, event, key_id=None, user_id=None):
        day = event["timestamp"][:10]
        updates = {"": aggregate()}
        successful = event.get("result_count", 0) > 0
        partial = successful and any(a["status"] not in SUCCESS for a in event["attempts"])
        add(
            updates[""],
            "partial_success" if partial else "success" if successful else "failed",
            event["latency_ms"],
            event["estimated_cost_usd"],
            sum(bool(a.get("fallback")) for a in event["attempts"]),
        )
        for attempt in event["attempts"]:
            if attempt["status"] == "skipped":
                continue
            name = attempt["provider"]
            data = updates.setdefault(name, aggregate())
            add(
                data,
                attempt["status"],
                attempt["latency_ms"],
                attempt.get("estimated_cost_usd", 0),
                int(bool(attempt.get("fallback"))),
            )
        with self.transaction():
            # Acquire a cross-process writer lock before reading and merging daily data.
            if key_id:
                self.db.execute(
                    "UPDATE access_keys SET last_used_at=?,usage_count=usage_count+1 WHERE id=?",
                    (time.time(), key_id),
                )
            self._merge_daily_usage(day, updates)
            # A user deleted during an in-flight call must not break global accounting.
            if (
                user_id is not None
                and self.db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
            ):
                self._merge_daily_usage(day, updates, user_id)
            # Fixed retention keeps the embedded store small; statistics use UTC days.
            if time.monotonic() - self.last_maintenance >= 3600:
                cutoff = (datetime.now(UTC) - timedelta(days=365)).date().isoformat()
                self.db.execute("DELETE FROM usage_daily WHERE day<?", (cutoff,))
                self.db.execute("DELETE FROM user_usage_daily WHERE day<?", (cutoff,))
                self.last_maintenance = time.monotonic()

    def _merge_daily_usage(self, day, updates, user_id=None):
        if user_id is None:
            select = "SELECT data FROM usage_daily WHERE day=? AND provider=?"
            insert = "INSERT OR REPLACE INTO usage_daily(day,provider,data) VALUES (?,?,?)"
            prefix = (day,)
        else:
            select = "SELECT data FROM user_usage_daily WHERE user_id=? AND day=? AND provider=?"
            insert = "INSERT OR REPLACE INTO user_usage_daily(user_id,day,provider,data) VALUES (?,?,?,?)"
            prefix = (user_id, day)
        for name, update in updates.items():
            data = aggregate()
            merge(data, update)
            previous = self.db.execute(select, (*prefix, name)).fetchone()
            if previous:
                merge(data, json.loads(previous[0]))
            self.db.execute(insert, (*prefix, name, json.dumps(data)))

    def usage(self, days, user_id=None):
        start = (datetime.now(UTC) - timedelta(days=days - 1)).date()
        totals, providers, trend = aggregate(), {}, {}
        with self.read() as db:
            if user_id is None:
                rows = db.execute(
                    "SELECT * FROM usage_daily WHERE day>=? ORDER BY day,provider", (start.isoformat(),)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT day,provider,data FROM user_usage_daily "
                    "WHERE user_id=? AND day>=? ORDER BY day,provider",
                    (user_id, start.isoformat()),
                ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            if row["provider"]:
                merge(providers.setdefault(row["provider"], aggregate()), data)
            else:
                merge(totals, data)
                trend[row["day"]] = summary(data)
        return {
            "scope": f"{days}d",
            "persistent": True,
            "timezone": "UTC",
            "window_basis": f"last {days} UTC calendar days including today; shared SQLite file",
            "summary": summary(totals),
            "by_provider": [{"name": name, **summary(data)} for name, data in sorted(providers.items())],
            "trend": [
                {
                    "day": (start + timedelta(days=i)).isoformat(),
                    **trend.get((start + timedelta(days=i)).isoformat(), summary(aggregate())),
                }
                for i in range(days)
            ],
            "recent": [],
            "counters": {"requests": totals["requests"], "fallbacks": totals["fallbacks"]},
        }

    def close(self):
        # Lifespan drains async work before reaching this point. Borrow every
        # reader to wait for synchronous endpoints already using a connection.
        connections = [self.readers.get() for _ in self.reader_connections]
        with self.lock:
            for connection in connections:
                connection.close()
            self.db.close()
