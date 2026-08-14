"""
Henxi - Database Layer
SQLite database for accounts, tokens, sessions, and quest logs.
"""

import sqlite3
import json
import threading
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

DB_PATH = Path(__file__).parent / "bot_data.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database schema."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    UNIQUE NOT NULL,
                username    TEXT,
                global_name TEXT,
                avatar      TEXT,
                added_at    TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'offline',
                last_seen   TEXT
            );

            CREATE TABLE IF NOT EXISTS tokens (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER NOT NULL,
                token       TEXT    UNIQUE NOT NULL,
                build_number INTEGER DEFAULT 0,
                last_error  TEXT,
                added_at    TEXT    NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id    INTEGER NOT NULL,
                started_at  TEXT    NOT NULL,
                stopped_at TEXT,
                reason      TEXT,
                FOREIGN KEY (token_id) REFERENCES tokens(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quest_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id    INTEGER NOT NULL,
                quest_name  TEXT,
                quest_id    TEXT,
                task_type   TEXT,
                action      TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                message     TEXT,
                created_at  TEXT    NOT NULL,
                FOREIGN KEY (token_id) REFERENCES tokens(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.commit()


# ── Token management ──────────────────────────────────────────────────────────

def add_account(token: str, build_number: int = 0) -> Optional[int]:
    import requests
    import base64

    # Decode token to get user_id
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload = json.loads(base64.b64decode(parts[1] + "==").decode())
            user_id = str(payload.get("id", payload.get("sub", "")))
        else:
            user_id = token[:32]
    except Exception:
        user_id = token[:32]

    # Try to fetch real username
    username = global_name = None
    try:
        headers = {
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get("https://discord.com/api/v9/users/@me", headers=headers, timeout=10)
        if r.status_code == 200:
            u = r.json()
            username = u.get("username")
            global_name = u.get("global_name")
            user_id = u.get("id", user_id)
    except Exception:
        pass

    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM accounts WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        if row:
            account_id = row["id"]
            conn.execute(
                "UPDATE accounts SET last_seen = ? WHERE id = ?",
                (now, account_id)
            )
        else:
            cur = conn.execute(
                """INSERT INTO accounts (user_id, username, global_name, added_at, status, last_seen)
                   VALUES (?, ?, ?, ?, 'offline', ?)""",
                (user_id, username, global_name, now, now)
            )
            account_id = cur.lastrowid

        # Upsert token
        cur2 = conn.execute(
            "SELECT id FROM tokens WHERE token = ?", (token,)
        )
        trow = cur2.fetchone()
        if trow:
            token_id = trow["id"]
            conn.execute(
                "UPDATE tokens SET build_number = COALESCE(?, build_number), last_error = NULL WHERE id = ?",
                (build_number, token_id)
            )
        else:
            cur3 = conn.execute(
                "INSERT INTO tokens (account_id, token, build_number, added_at) VALUES (?, ?, ?, ?)",
                (account_id, token, build_number, now)
            )
            token_id = cur3.lastrowid

        conn.commit()
        return token_id


def remove_account(user_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM accounts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM accounts WHERE id = ?", (row["id"],))
        conn.commit()
        return True


def get_all_accounts() -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT a.*, t.token, t.build_number, t.last_error,
                   s.id as session_id, s.started_at, s.stopped_at
            FROM accounts a
            LEFT JOIN tokens t ON t.account_id = a.id
            LEFT JOIN (
                SELECT token_id, id, started_at, stopped_at,
                       ROW_NUMBER() OVER (PARTITION BY token_id ORDER BY started_at DESC) as rn
                FROM sessions
            ) s ON s.token_id = t.id AND s.rn = 1
            ORDER BY a.added_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def update_account_status(user_id: str, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE accounts SET status = ?, last_seen = ? WHERE user_id = ?",
            (status, datetime.now(timezone.utc).isoformat(), user_id)
        )
        conn.commit()


# ── Session management ────────────────────────────────────────────────────────

def start_session(token_id: int) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET stopped_at = ?, reason = 'auto' WHERE token_id = ? AND stopped_at IS NULL",
            (now, token_id)
        )
        cur = conn.execute(
            "INSERT INTO sessions (token_id, started_at) VALUES (?, ?)",
            (token_id, now)
        )
        conn.commit()
        return cur.lastrowid


def stop_session(session_id: int, reason: str = "manual"):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET stopped_at = ?, reason = ? WHERE id = ?",
            (now, reason, session_id)
        )
        conn.commit()


# ── Quest log ────────────────────────────────────────────────────────────────

def log_quest(token_id: int, quest_name: str, quest_id: str,
              task_type: str, action: str, status: str = "pending", message: str = ""):
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO quest_log (token_id, quest_name, quest_id, task_type, action, status, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (token_id, quest_name, quest_id, task_type, action, status, message, now)
        )
        conn.commit()


def get_quest_logs(limit: int = 100) -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ql.*, t.token, a.username, a.user_id
            FROM quest_log ql
            JOIN tokens t ON t.id = ql.token_id
            JOIN accounts a ON a.id = t.account_id
            ORDER BY ql.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    with get_conn() as conn:
        total_accounts = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
        active_sessions = conn.execute(
            "SELECT COUNT(*) as c FROM sessions WHERE stopped_at IS NULL"
        ).fetchone()["c"]
        total_logs = conn.execute("SELECT COUNT(*) as c FROM quest_log").fetchone()["c"]
        completed_logs = conn.execute(
            "SELECT COUNT(*) as c FROM quest_log WHERE status = 'completed'"
        ).fetchone()["c"]
        enrolled_logs = conn.execute(
            "SELECT COUNT(*) as c FROM quest_log WHERE action = 'enrolled'"
        ).fetchone()["c"]
        recent_logs = conn.execute("""
            SELECT ql.*, a.username
            FROM quest_log ql
            JOIN tokens t ON t.id = ql.token_id
            JOIN accounts a ON a.id = t.account_id
            ORDER BY ql.created_at DESC LIMIT 20
        """).fetchall()
        return {
            "total_accounts": total_accounts,
            "active_sessions": active_sessions,
            "total_logs": total_logs,
            "completed_logs": completed_logs,
            "enrolled_logs": enrolled_logs,
            "recent_logs": [dict(r) for r in recent_logs],
        }
