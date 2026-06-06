import sqlite3, os, time

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def init():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                free_uses INTEGER DEFAULT 2,
                paid_uses INTEGER DEFAULT 0,
                total_uses INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                created_at INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crypto_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                stylizations INTEGER NOT NULL,
                amount_usd REAL NOT NULL,
                invoice_uuid TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'created',
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_claims (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, code)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promos (
                code TEXT PRIMARY KEY,
                amount INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                style TEXT NOT NULL,
                result_path TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                mode TEXT,
                style TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS funnel_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event TEXT NOT NULL,
                source TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                promo_code TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            )
        """)
        # migration: add columns if missing
        cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
        if "referrer_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL")
        if "created_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT 0")
        if "last_daily_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_daily_at INTEGER DEFAULT 0")
        if "username" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")
        if "first_name" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''")
        if "last_name" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_name TEXT DEFAULT ''")
        if "source" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN source TEXT DEFAULT ''")
        conn.execute("UPDATE users SET created_at = ? WHERE created_at = 0", (int(time.time()),))
        conn.executemany(
            "INSERT OR IGNORE INTO promos (code, amount, active, created_at) VALUES (?, ?, 1, ?)",
            [("START5", 5, int(time.time())), ("ART10", 10, int(time.time()))],
        )


def get_user(user_id: int) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {"user_id": user_id, "free_uses": 2, "paid_uses": 0, "total_uses": 0, "referrer_id": None, "created_at": 0, "last_daily_at": 0, "username": "", "first_name": "", "last_name": "", "source": ""}
    keys = ["user_id", "free_uses", "paid_uses", "total_uses", "referrer_id", "created_at", "last_daily_at", "username", "first_name", "last_name", "source"]
    return dict(zip(keys, row))


def create_user(user_id: int, referrer_id: int | None = None):
    with sqlite3.connect(DB_PATH) as conn:
        now = int(time.time())
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, free_uses, paid_uses, total_uses, referrer_id, created_at, last_daily_at) VALUES (?, 2, 0, 0, ?, ?, 0)",
            (user_id, referrer_id, now),
        )
        if referrer_id is not None:
            conn.execute(
                "UPDATE users SET referrer_id = COALESCE(referrer_id, ?) WHERE user_id = ?",
                (referrer_id, user_id),
            )


def update_user_profile(user_id: int, username: str = "", first_name: str = "", last_name: str = ""):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
            (username or "", first_name or "", last_name or "", user_id),
        )


def set_user_source(user_id: int, source: str):
    if not source:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET source = COALESCE(NULLIF(source, ''), ?) WHERE user_id = ?",
            (source[:64], user_id),
        )


def set_referrer(user_id: int, referrer_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL",
            (referrer_id, user_id),
        )


def use_free(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT free_uses FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            create_user(user_id)
            row = (2,)
        if row[0] > 0:
            conn.execute(
                "UPDATE users SET free_uses = free_uses - 1, total_uses = total_uses + 1 WHERE user_id = ?",
                (user_id,),
            )
            return True
        return False


def use_paid(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT paid_uses FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row[0] > 0:
            conn.execute(
                "UPDATE users SET paid_uses = paid_uses - 1, total_uses = total_uses + 1 WHERE user_id = ?",
                (user_id,),
            )
            return True
        return False


def add_paid_uses(user_id: int, amount: int = 50):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("UPDATE users SET paid_uses = paid_uses + ? WHERE user_id = ?", (amount, user_id))
        if cur.rowcount == 0:
            now = int(time.time())
            conn.execute(
                "INSERT INTO users (user_id, free_uses, paid_uses, total_uses, referrer_id, created_at, last_daily_at) VALUES (?, 2, ?, 0, NULL, ?, 0)",
                (user_id, amount, now),
            )


def refund_use(user_id: int, source: str):
    with sqlite3.connect(DB_PATH) as conn:
        if source == "free":
            conn.execute(
                "UPDATE users SET free_uses = free_uses + 1, total_uses = MAX(total_uses - 1, 0) WHERE user_id = ?",
                (user_id,),
            )
        elif source == "paid":
            conn.execute(
                "UPDATE users SET paid_uses = paid_uses + 1, total_uses = MAX(total_uses - 1, 0) WHERE user_id = ?",
                (user_id,),
            )


def add_free_uses(user_id: int, amount: int = 5):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("UPDATE users SET free_uses = free_uses + ? WHERE user_id = ?", (amount, user_id))
        if cur.rowcount == 0:
            now = int(time.time())
            conn.execute(
                "INSERT INTO users (user_id, free_uses, paid_uses, total_uses, referrer_id, created_at, last_daily_at) VALUES (?, ?, 0, 0, NULL, ?, 0)",
                (user_id, 2 + amount, now),
            )


def claim_daily(user_id: int, amount: int = 1) -> bool:
    now = int(time.time())
    day_start = now - (now % 86400)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT last_daily_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, free_uses, paid_uses, total_uses, created_at, last_daily_at) VALUES (?, 2, 0, 0, ?, 0)",
                (user_id, now),
            )
            row = (0,)
        if row[0] >= day_start:
            return False
        conn.execute(
            "UPDATE users SET free_uses = free_uses + ?, last_daily_at = ? WHERE user_id = ?",
            (amount, now, user_id),
        )
        return True


def get_promo(code: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT code, amount, active, created_at FROM promos WHERE code = ? AND active = 1",
            (code,),
        ).fetchone()
    if row is None:
        return None
    return {"code": row[0], "amount": row[1], "active": row[2], "created_at": row[3]}


def claim_promo(user_id: int, code: str, amount: int | None = None) -> bool:
    promo = get_promo(code)
    if promo is None:
        return False
    amount = promo["amount"] if amount is None else amount
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO promo_claims (user_id, code, created_at) VALUES (?, ?, ?)",
                (user_id, code, int(time.time())),
            )
        except sqlite3.IntegrityError:
            return False
        conn.execute(
            "UPDATE users SET free_uses = free_uses + ? WHERE user_id = ?",
            (amount, user_id),
        )
        return True


def set_promo(code: str, amount: int, active: int = 1):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO promos (code, amount, active, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET amount = excluded.amount, active = excluded.active",
            (code.upper(), amount, active, int(time.time())),
        )


def list_promos():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT code, amount, active FROM promos ORDER BY code").fetchall()
    return [{"code": r[0], "amount": r[1], "active": r[2]} for r in rows]


def deactivate_promo(code: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE promos SET active = 0 WHERE code = ?", (code.upper(),))


def delete_promo(code: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM promos WHERE code = ?", (code.upper(),))


def list_users(limit: int = 20):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id, free_uses, paid_uses, total_uses, created_at, username, first_name, last_name, source FROM users ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = ["user_id", "free_uses", "paid_uses", "total_uses", "created_at", "username", "first_name", "last_name", "source"]
    return [dict(zip(keys, r)) for r in rows]


def all_user_ids():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
    return [r[0] for r in rows]


def user_ids_by_source(source: str):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id FROM users WHERE COALESCE(NULLIF(source, ''), 'organic') = ?",
            (source,),
        ).fetchall()
    return [r[0] for r in rows]


def users_segment(limit_source: str = "", paid_only: bool = False, free_only: bool = False):
    query = "SELECT user_id FROM users WHERE 1=1"
    params = []
    if limit_source:
        query += " AND COALESCE(NULLIF(source, ''), 'organic') = ?"
        params.append(limit_source)
    if paid_only:
        query += " AND paid_uses > 0"
    if free_only:
        query += " AND free_uses > 0"
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [r[0] for r in rows]


def create_campaign(name: str, source: str, promo_code: str = ""):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO campaigns (name, source, promo_code, created_at) VALUES (?, ?, ?, ?)",
            (name[:64], source[:64], promo_code[:64], int(time.time())),
        )


def list_campaigns(limit: int = 20):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT name, source, promo_code, created_at FROM campaigns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"name": r[0], "source": r[1], "promo_code": r[2], "created_at": r[3]} for r in rows]


def payments_stats(limit: int = 10):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id, method, amount, status, created_at FROM payments ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"user_id": r[0], "method": r[1], "amount": r[2], "status": r[3], "created_at": r[4]} for r in rows]


def top_users(limit: int = 10):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id, total_uses FROM users ORDER BY total_uses DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"user_id": r[0], "total_uses": r[1]} for r in rows]


def add_history(user_id: int, mode: str, style: str, result_path: str | None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO history (user_id, mode, style, result_path, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, mode, style, result_path, int(time.time())),
        )


def get_history(user_id: int, limit: int = 5):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT mode, style, result_path, created_at FROM history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    keys = ["mode", "style", "result_path", "created_at"]
    return [dict(zip(keys, r)) for r in rows]


def create_job(user_id: int, status: str, mode: str = "", style: str = "") -> int:
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (user_id, status, mode, style, error, created_at, updated_at) VALUES (?, ?, ?, ?, '', ?, ?)",
            (user_id, status, mode, style, now, now),
        )
        return cur.lastrowid


def update_job(job_id: int | None, status: str, error: str = ""):
    if not job_id:
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, int(time.time()), job_id),
        )


def latest_jobs(user_id: int | None = None, limit: int = 10):
    with sqlite3.connect(DB_PATH) as conn:
        if user_id is None:
            rows = conn.execute(
                "SELECT id, user_id, status, mode, style, error, created_at, updated_at FROM jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, status, mode, style, error, created_at, updated_at FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    keys = ["id", "user_id", "status", "mode", "style", "error", "created_at", "updated_at"]
    return [dict(zip(keys, r)) for r in rows]


def remaining_free(user_id: int) -> int:
    row = get_user(user_id)
    return row.get("free_uses", 0)


def remaining_paid(user_id: int) -> int:
    row = get_user(user_id)
    return row.get("paid_uses", 0)


def log_payment(user_id: int, method: str, amount: int, status: str = "completed"):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO payments (user_id, method, amount, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, method, amount, status, int(time.time())),
        )


def log_funnel_event(user_id: int, event: str):
    user = get_user(user_id)
    source = user.get("source", "") if user else ""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO funnel_events (user_id, event, source, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event[:64], source[:64], int(time.time())),
        )


def funnel_stats(days: int = 30) -> dict:
    since = int(time.time()) - days * 86400
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT event, COUNT(*), COUNT(DISTINCT user_id) FROM funnel_events WHERE created_at >= ? GROUP BY event",
            (since,),
        ).fetchall()
        by_source = conn.execute(
            "SELECT COALESCE(NULLIF(source, ''), 'organic') AS source, COUNT(*) FROM funnel_events WHERE created_at >= ? AND event = 'start' GROUP BY COALESCE(NULLIF(source, ''), 'organic') ORDER BY COUNT(*) DESC LIMIT 10",
            (since,),
        ).fetchall()
    return {
        "events": [{"event": row[0], "count": row[1], "users": row[2]} for row in rows],
        "sources": [{"source": row[0], "count": row[1]} for row in by_source],
    }


def get_referrer(user_id: int) -> int | None:
    row = get_user(user_id)
    return row.get("referrer_id")


def add_crypto_payment(user_id: int, stylizations: int, amount_usd: float, invoice_uuid: str):
    with sqlite3.connect(DB_PATH) as conn:
        now = int(time.time())
        conn.execute(
            "INSERT OR IGNORE INTO crypto_payments (user_id, stylizations, amount_usd, invoice_uuid, status, created_at) VALUES (?, ?, ?, ?, 'created', ?)",
            (user_id, stylizations, amount_usd, invoice_uuid, now),
        )


def get_pending_crypto_payments() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_payments WHERE status = 'created'"
        ).fetchall()
    keys = ["id", "user_id", "stylizations", "amount_usd", "invoice_uuid", "status", "created_at"]
    return [dict(zip(keys, row)) for row in rows]


def update_crypto_payment(invoice_uuid: str, status: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE crypto_payments SET status = ? WHERE invoice_uuid = ?",
            (status, invoice_uuid),
        )


def get_crypto_payment(invoice_uuid: str):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT * FROM crypto_payments WHERE invoice_uuid = ?",
            (invoice_uuid,),
        ).fetchone()
    if row is None:
        return None
    keys = ["id", "user_id", "stylizations", "amount_usd", "invoice_uuid", "status", "created_at"]
    return dict(zip(keys, row))


def complete_crypto_payment(invoice_uuid: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM crypto_payments WHERE invoice_uuid = ? AND status = 'created'",
            (invoice_uuid,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE crypto_payments SET status = 'paid' WHERE invoice_uuid = ? AND status = 'created'",
            (invoice_uuid,),
        )
    keys = ["id", "user_id", "stylizations", "amount_usd", "invoice_uuid", "status", "created_at"]
    return dict(zip(keys, row))


def admin_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_uses = conn.execute("SELECT COALESCE(SUM(total_uses), 0) FROM users").fetchone()[0]
        total_paid_bought = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'completed'"
        ).fetchone()[0]
        total_free_left = conn.execute("SELECT COALESCE(SUM(free_uses), 0) FROM users").fetchone()[0]
        paid_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM payments WHERE status = 'completed'"
        ).fetchone()[0]
        since_24h = int(time.time()) - 86400
        active_24h = conn.execute("SELECT COUNT(*) FROM jobs WHERE updated_at > ?", (since_24h,)).fetchone()[0]
        revenue = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'completed'").fetchone()[0]
        sources = conn.execute(
            "SELECT COALESCE(NULLIF(source, ''), 'organic') AS source, COUNT(*) FROM users GROUP BY COALESCE(NULLIF(source, ''), 'organic') ORDER BY COUNT(*) DESC LIMIT 8"
        ).fetchall()
    return {
        "total": total,
        "total_uses": total_uses,
        "total_paid_bought": total_paid_bought,
        "total_free_left": total_free_left,
        "paid_users": paid_users,
        "active_24h": active_24h,
        "revenue": revenue,
        "sources": [{"source": row[0], "count": row[1]} for row in sources],
    }
