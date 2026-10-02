"""Small durable identity/configuration store; secrets never enter public records."""

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet


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
        with self.db:
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
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
        # A changed encryption secret must fail at startup, never silently lose credentials.
        check = self.db.execute("SELECT value FROM meta WHERE name='encryption_check'").fetchone()
        if check:
            if self.cipher.decrypt(check[0].encode()) != b"bensz-search":
                raise ValueError("Invalid encryption secret")
        else:
            with self.db:
                self.db.execute(
                    "INSERT INTO meta VALUES ('encryption_check', ?)",
                    (self.cipher.encrypt(b"bensz-search").decode(),),
                )

    def bootstrap(self, username, password):
        with self.lock:
            if not self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                self.create_user(username, password, "admin")

    def create_user(self, username, password, role):
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT INTO users(username,password,role,created_at) VALUES (?,?,?,?)",
                (username, password_hash(password), role, time.time()),
            )
            return {"id": cursor.lastrowid, "username": username, "role": role}

    def users(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT id,username,role,created_at FROM users")]

    def login(self, username, password):
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            valid = password_matches(password, row["password"] if row else self.dummy_hash)
            if not row or not valid:
                return None
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            expires = time.time() + 43200
            with self.db:
                self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
                self.db.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), row["id"], csrf, expires)
                )
            return token, {"user": {k: row[k] for k in ("id", "username", "role")}, "csrf_token": csrf}

    def session(self, token):
        with self.lock:
            row = self.db.execute(
                "SELECT u.id,u.username,u.role,s.csrf FROM sessions s JOIN users u ON s.user_id=u.id "
                "WHERE s.token=? AND s.expires_at>?",
                (digest(token), time.time()),
            ).fetchone()
            return (
                {"user": {k: row[k] for k in ("id", "username", "role")}, "csrf_token": row["csrf"]}
                if row
                else None
            )

    def logout(self, token):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE token=?", (digest(token),))

    def change_password(self, user_id, current, new):
        with self.lock, self.db:
            row = self.db.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not password_matches(current, row[0]):
                return False
            self.db.execute("UPDATE users SET password=? WHERE id=?", (password_hash(new), user_id))
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            return True

    def delete_user(self, user_id):
        with self.lock, self.db:
            return self.db.execute("DELETE FROM users WHERE id=?", (user_id,)).rowcount

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

    def save_provider(self, config, api_key=None):
        with self.lock, self.db:
            name = config["name"]
            previous = self.db.execute("SELECT secret FROM providers WHERE name=?", (name,)).fetchone()
            secret = previous[0] if previous else ""
            if api_key is not None:
                secret = self.cipher.encrypt(api_key.encode()).decode() if api_key else ""
            self.db.execute(
                "INSERT OR REPLACE INTO providers VALUES (?,?,?)", (name, json.dumps(config), secret)
            )

    def delete_provider(self, name):
        with self.lock, self.db:
            return self.db.execute("DELETE FROM providers WHERE name=?", (name,)).rowcount

    def seed_providers(self, records):
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM meta WHERE name='providers_seeded'").fetchone():
                return
            for record in records:
                record = dict(record)
                key = record.pop("api_key", "")
                self.save_provider(record, key)
            self.db.execute("INSERT INTO meta VALUES ('providers_seeded','true')")

    def keys(self, user_id):
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT id,name,prefix,created_at,last_used_at,revoked FROM access_keys WHERE user_id=? ORDER BY created_at DESC",
                    (user_id,),
                )
            ]

    def create_key(self, user_id, name):
        key, record_id = "sk-bs-" + secrets.token_urlsafe(32), secrets.token_hex(12)
        now = time.time()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO access_keys VALUES (?,?,?,?,?,?,NULL,0)",
                (record_id, user_id, name, digest(key), key[:14], now),
            )
        return {
            "key": key,
            "record": {
                "id": record_id,
                "name": name,
                "prefix": key[:14],
                "created_at": now,
                "last_used_at": None,
                "revoked": False,
            },
        }

    def revoke_key(self, user_id, key_id):
        with self.lock, self.db:
            return self.db.execute(
                "UPDATE access_keys SET revoked=1 WHERE id=? AND user_id=?", (key_id, user_id)
            ).rowcount

    def authenticate_key(self, key):
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT k.id,u.id AS user_id,u.username FROM access_keys k JOIN users u ON k.user_id=u.id "
                "WHERE k.token=? AND k.revoked=0",
                (digest(key),),
            ).fetchone()
            if row:
                self.db.execute("UPDATE access_keys SET last_used_at=? WHERE id=?", (time.time(), row["id"]))
            return dict(row) if row else None

    def close(self):
        self.db.close()
