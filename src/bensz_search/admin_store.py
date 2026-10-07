"""Small durable identity/configuration store; secrets never enter public records."""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
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
        self._migrate()
        # A changed encryption secret must fail at startup, never silently lose credentials.
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            check = self.db.execute("SELECT value FROM meta WHERE name='encryption_check'").fetchone()
            if check:
                if self.cipher.decrypt(check[0].encode()) != b"bensz-search":
                    raise ValueError("Invalid encryption secret")
            else:
                self.db.execute(
                    "INSERT INTO meta VALUES ('encryption_check', ?)",
                    (self.cipher.encrypt(b"bensz-search").decode(),),
                )

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
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
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
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, actor_id INTEGER,
                    action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_time ON audit_events(timestamp);
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day TEXT NOT NULL, provider TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY (day,provider)
                );
            """
            for statement in statements.split(";"):
                if statement.strip():
                    self.db.execute(statement)

    def _audit(self, actor_id, action, object_type, object_id):
        if actor_id is not None:
            self.db.execute(
                "INSERT INTO audit_events(timestamp,actor_id,action,object_type,object_id) VALUES (?,?,?,?,?)",
                (time.time(), actor_id, action, object_type, str(object_id)),
            )

    def bootstrap(self, username, password):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if not self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                self.db.execute(
                    "INSERT INTO users(username,password,role,created_at) VALUES (?,?,'admin',?)",
                    (username, password_hash(password), time.time()),
                )

    def create_user(self, username, password, role, actor_id=None):
        hashed = password_hash(password)
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT INTO users(username,password,role,created_at) VALUES (?,?,?,?)",
                (username, hashed, role, time.time()),
            )
            self._audit(actor_id, "create", "user", cursor.lastrowid)
            return {"id": cursor.lastrowid, "username": username, "role": role, "enabled": True}

    def users(self):
        with self.lock:
            return [
                {**dict(row), "enabled": bool(row["enabled"])}
                for row in self.db.execute(
                    "SELECT id,username,role,created_at,enabled FROM users ORDER BY id"
                )
            ]

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
        with self.lock, self.db:
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
            return next(row for row in self.users() if row["id"] == user_id)

    def login(self, username, password):
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            valid = password_matches(password, row["password"] if row else self.dummy_hash)
            if not row or not valid or not row["enabled"]:
                return None
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            now = time.time()
            expires = now + 43200
            with self.db:
                self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                self.db.execute(
                    "INSERT INTO sessions(token,user_id,csrf,expires_at,id,created_at) VALUES (?,?,?,?,?,?)",
                    (digest(token), row["id"], csrf, expires, secrets.token_hex(16), now),
                )
            return token, {
                "user": {k: row[k] for k in ("id", "username", "role")},
                "csrf_token": csrf,
                "expires_at": expires,
            }

    def session(self, token):
        with self.lock:
            row = self.db.execute(
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
        with self.lock:
            return [
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "expires_at": r["expires_at"],
                    "current": hmac.compare_digest(r["token"], digest(token)),
                }
                for r in self.db.execute(
                    "SELECT id,token,created_at,expires_at FROM sessions WHERE user_id=? AND expires_at>? "
                    "ORDER BY created_at DESC",
                    (user_id, time.time()),
                )
            ]

    def revoke_other_sessions(self, user_id, token):
        with self.lock, self.db:
            count = self.db.execute(
                "DELETE FROM sessions WHERE user_id=? AND token!=?", (user_id, digest(token))
            ).rowcount
            self._audit(user_id, "revoke_others", "session", user_id)
            return count

    def logout(self, token):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))

    def change_password(self, user_id, current, new):
        hashed = password_hash(new)
        with self.lock, self.db:
            row = self.db.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not password_matches(current, row[0]):
                return False
            self.db.execute("UPDATE users SET password=? WHERE id=?", (hashed, user_id))
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self._audit(user_id, "change_password", "user", user_id)
            return True

    def delete_user(self, user_id, actor_id=None):
        with self.lock, self.db:
            self.db.execute("UPDATE users SET enabled=enabled WHERE id=?", (user_id,))
            self._protect_admin(user_id, deleting=True)
            count = self.db.execute("DELETE FROM users WHERE id=?", (user_id,)).rowcount
            self._audit(actor_id, "delete", "user", user_id)
            return count

    def providers(self, private=False):
        with self.lock:
            records = []
            for row in self.db.execute("SELECT * FROM providers ORDER BY name"):
                config = json.loads(row["config"])
                config["has_api_key"] = bool(row["secret"])
                if private:
                    config["api_key"] = (
                        self.cipher.decrypt(row["secret"].encode()).decode() if row["secret"] else ""
                    )
                records.append(config)
            return records

    def save_provider(self, config, api_key=None, actor_id=None, expected=None):
        with self.lock, self.db:
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
        with self.lock, self.db:
            count = self.db.execute("DELETE FROM providers WHERE name=?", (name,)).rowcount
            if count:
                self._audit(actor_id, "delete", "provider", name)
            return count

    def import_providers(self, records, actor_id):
        with self.lock, self.db:
            # INSERT (not REPLACE) makes conflicts roll back the complete import.
            for config in records:
                self.db.execute(
                    "INSERT INTO providers(name,config,secret) VALUES (?,?,'')",
                    (config["name"], json.dumps(config)),
                )
                self._audit(actor_id, "import", "provider", config["name"])

    def seed_providers(self, records):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
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

    def keys(self, user_id=None):
        with self.lock:
            where = " WHERE k.user_id=?" if user_id is not None else ""
            rows = self.db.execute(
                "SELECT k.id,k.user_id,u.username,k.name,k.prefix,k.created_at,k.last_used_at,k.revoked,"
                "k.expires_at,k.scopes,k.usage_count FROM access_keys k JOIN users u ON u.id=k.user_id"
                + where
                + " ORDER BY k.created_at DESC",
                (user_id,) if user_id is not None else (),
            )
            return [{**dict(r), "scopes": json.loads(r["scopes"])} for r in rows]

    def create_key(self, user_id, name, expires_at=None, scopes=None):
        scopes = ["search", "protocol"] if scopes is None else scopes
        if not scopes or set(scopes) - {"search", "protocol"}:
            raise ValueError("密钥权限范围无效")
        if expires_at is not None and expires_at <= time.time():
            raise ValueError("过期时间必须在未来")
        key, record_id = "sk-bs-" + secrets.token_urlsafe(32), secrets.token_hex(12)
        now = time.time()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO access_keys(id,user_id,name,token,prefix,created_at,expires_at,scopes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (record_id, user_id, name, digest(key), key[:14], now, expires_at, json.dumps(scopes)),
            )
            self._audit(user_id, "create", "key", record_id)
            record = next(r for r in self.keys(user_id) if r["id"] == record_id)
        return {"key": key, "record": record}

    def revoke_key(self, user_id, key_id, actor_id=None):
        with self.lock, self.db:
            where = " AND user_id=?" if user_id is not None else ""
            count = self.db.execute(
                "UPDATE access_keys SET revoked=1 WHERE id=?" + where,
                (key_id, user_id) if user_id is not None else (key_id,),
            ).rowcount
            if count:
                self._audit(actor_id if actor_id is not None else user_id, "revoke", "key", key_id)
            return count

    def delete_key(self, user_id, key_id, actor_id=None):
        with self.lock, self.db:
            where = " AND user_id=?" if user_id is not None else ""
            count = self.db.execute(
                "DELETE FROM access_keys WHERE id=?" + where,
                (key_id, user_id) if user_id is not None else (key_id,),
            ).rowcount
            if count:
                self._audit(actor_id if actor_id is not None else user_id, "delete", "key", key_id)
            return count

    def authenticate_key(self, key, required_scope=None):
        with self.lock:
            row = self.db.execute(
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
        with self.lock, self.db:
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
        with self.lock:
            total = self.db.execute("SELECT count(*) FROM audit_events" + where, values).fetchone()[0]
            rows = self.db.execute(
                "SELECT * FROM audit_events" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
            return {"events": [dict(r) for r in rows], "total": total}

    def record_usage(self, event, key_id=None):
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
        with self.lock, self.db:
            # Acquire a cross-process writer lock before reading and merging daily data.
            self.db.execute("UPDATE meta SET value=value WHERE name='providers_seeded'")
            if key_id:
                self.db.execute(
                    "UPDATE access_keys SET last_used_at=?,usage_count=usage_count+1 WHERE id=?",
                    (time.time(), key_id),
                )
            for name, data in updates.items():
                previous = self.db.execute(
                    "SELECT data FROM usage_daily WHERE day=? AND provider=?", (day, name)
                ).fetchone()
                if previous:
                    merge(data, json.loads(previous[0]))
                self.db.execute(
                    "INSERT OR REPLACE INTO usage_daily VALUES (?,?,?)",
                    (day, name, json.dumps(data)),
                )
            # Fixed retention keeps the embedded store small; statistics use UTC days.
            cutoff = (datetime.now(UTC) - timedelta(days=365)).date().isoformat()
            self.db.execute("DELETE FROM usage_daily WHERE day<?", (cutoff,))

    def usage(self, days):
        start = (datetime.now(UTC) - timedelta(days=days - 1)).date()
        totals, providers, trend = aggregate(), {}, {}
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM usage_daily WHERE day>=? ORDER BY day,provider", (start.isoformat(),)
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
        with self.lock:
            self.db.close()
