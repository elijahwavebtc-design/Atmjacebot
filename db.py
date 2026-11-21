"""Base de données SQLite du bot (aucune dépendance Telegram)."""
import os
import random
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "bot.db")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                code TEXT,
                grp TEXT,
                blocked INTEGER NOT NULL DEFAULT 0,
                registered_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY);
            """
        )


def norm(code):
    return (code or "").strip().upper()


# ---------- inscrits ----------
def is_registered(user_id):
    with conn() as c:
        return c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is not None


def has_code(user_id):
    with conn() as c:
        row = c.execute("SELECT code FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["code"])


def register(user_id, username, first_name):
    """Retourne True si c'est une nouvelle inscription."""
    with conn() as c:
        exists = c.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
        if exists:
            c.execute(
                "UPDATE users SET username=?, first_name=?, blocked=0 WHERE user_id=?",
                (username, first_name, user_id),
            )
            return False
        c.execute(
            "INSERT INTO users(user_id, username, first_name) VALUES (?,?,?)",
            (user_id, username, first_name),
        )
        return True


def mark_blocked(user_id):
    with conn() as c:
        c.execute("UPDATE users SET blocked=1 WHERE user_id=?", (user_id,))


# ---------- codes d'affiliation ----------
def add_code(code):
    code = norm(code)
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO codes(code) VALUES (?)", (code,))


def remove_code(code):
    code = norm(code)
    with conn() as c:
        cur = c.execute("DELETE FROM codes WHERE code=?", (code,))
        return cur.rowcount > 0


def list_codes():
    """Liste (code, nombre d'inscrits qui l'ont utilisé)."""
    with conn() as c:
        rows = c.execute(
            """SELECT codes.code AS code, COUNT(users.user_id) AS n
               FROM codes LEFT JOIN users ON users.code = codes.code
               GROUP BY codes.code ORDER BY codes.code"""
        ).fetchall()
        return [(r["code"], r["n"]) for r in rows]


def apply_code(user_id, code):
    """Retourne 'ok', 'already', 'invalid' ou 'not_registered'."""
    code = norm(code)
    with conn() as c:
        row = c.execute("SELECT code FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return "not_registered"
        if row["code"]:
            return "already"
        if c.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone() is None:
            return "invalid"
        c.execute("UPDATE users SET code=? WHERE user_id=?", (code, user_id))
        return "ok"


def code_exists(code):
    with conn() as c:
        return c.execute("SELECT 1 FROM codes WHERE code=?", (norm(code),)).fetchone() is not None


# ---------- statistiques, groupes ----------
def stats():
    with conn() as c:
        def n(where):
            return c.execute(f"SELECT COUNT(*) FROM users WHERE {where}").fetchone()[0]

        return {
            "total": n("1=1"),
            "a": n("grp='A' AND blocked=0"),
            "b": n("grp='B' AND blocked=0"),
            "sans_groupe": n("grp IS NULL AND blocked=0"),
            "affilies": n("code IS NOT NULL AND blocked=0"),
            "bloques": n("blocked=1"),
        }


def split():
    """Mélange tous les inscrits actifs et les répartit moitié A, moitié B."""
    with conn() as c:
        ids = [r["user_id"] for r in c.execute("SELECT user_id FROM users WHERE blocked=0")]
        random.shuffle(ids)
        half = (len(ids) + 1) // 2
        a, b = ids[:half], ids[half:]
        c.execute("UPDATE users SET grp=NULL")
        c.executemany("UPDATE users SET grp='A' WHERE user_id=?", [(i,) for i in a])
        c.executemany("UPDATE users SET grp='B' WHERE user_id=?", [(i,) for i in b])
        return len(a), len(b)


def recipients(target):
    """target : A, B, TOUS ou AFFILIES. Exclut ceux qui ont bloqué le bot."""
    where = {
        "A": "grp='A'",
        "B": "grp='B'",
        "TOUS": "1=1",
        "AFFILIES": "code IS NOT NULL",
    }[target]
    with conn() as c:
        rows = c.execute(f"SELECT user_id FROM users WHERE blocked=0 AND {where}").fetchall()
        return [r["user_id"] for r in rows]


def delete_group(group):
    with conn() as c:
        cur = c.execute("DELETE FROM users WHERE grp=?", (group,))
        return cur.rowcount
