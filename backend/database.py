import sqlite3
import threading
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple, Any

from backend.config import DB_PATH, RISK_LOW_THRESHOLD, RISK_HIGH_THRESHOLD

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fio TEXT NOT NULL,
    account_number TEXT,
    card_number TEXT,
    age INTEGER,
    deposit_amount REAL,
    current_rate REAL,
    market_rate REAL,
    login_count INTEGER,
    days_to_maturity INTEGER,
    rate_diff REAL,
    days_since_last_login INTEGER,
    product_count INTEGER,
    region TEXT,
    churn INTEGER,
    churn_probability REAL,
    last_activity_date TEXT
);
"""
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_clients_fio ON clients(fio);",
    "CREATE INDEX IF NOT EXISTS idx_clients_account ON clients(account_number);",
    "CREATE INDEX IF NOT EXISTS idx_clients_card ON clients(card_number);",
    "CREATE INDEX IF NOT EXISTS idx_clients_churn_prob ON clients(churn_probability);",
    "CREATE INDEX IF NOT EXISTS idx_clients_last_activity ON clients(last_activity_date);",
    "CREATE INDEX IF NOT EXISTS idx_clients_rate_diff ON clients(rate_diff);",
]
CLIENT_FIELDS = [
    "fio", "account_number", "card_number", "age", "deposit_amount",
    "current_rate", "market_rate", "rate_diff", "login_count",
    "days_to_maturity", "days_since_last_login", "product_count",
    "region", "churn", "last_activity_date",
]



class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._init_schema()


    def _apply_pragmas(self):
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA cache_size=-64000;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        self._conn.commit()


    def _init_schema(self):
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(SCHEMA)
            for idx_sql in INDEXES:
                cur.execute(idx_sql)
            self._conn.commit()


    @contextmanager
    def transaction(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


    def is_empty(self) -> bool:
        cur = self._conn.execute("SELECT COUNT(*) as c FROM clients;")
        return cur.fetchone()["c"] == 0


    def count_clients(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) as c FROM clients;")
        return cur.fetchone()["c"]


    def batch_insert(self, records: List[Dict], batch_size: int = 1000)-> int:
        cols = CLIENT_FIELDS + ["churn_probability"]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO clients ({', '.join(cols)}) VALUES ({placeholders})"
        inserted = 0
        with self.transaction() as cur:
            for i in range(0, len(records), batch_size):
                chunk = records[i:i + batch_size]
                rows = [tuple(rec.get(c) for c in cols) for rec in chunk]
                cur.executemany(sql, rows)
                inserted += len(rows)
        return inserted


    def batch_upsert(self, records: List[Dict], batch_size: int = 1000)-> int:
        with self.transaction() as cur:
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_account ""ON clients(account_number) WHERE account_number IS NOT NULL;")

        cols = CLIENT_FIELDS + ["churn_probability"]
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT OR REPLACE INTO clients ({', '.join(cols)}) VALUES ({placeholders})"
        upserted = 0
        with self.transaction() as cur:
            for i in range(0, len(records), batch_size):
                chunk = records[i:i + batch_size]
                rows = [tuple(rec.get(c) for c in cols) for rec in chunk]
                cur.executemany(sql, rows)
                upserted += len(rows)
        return upserted


    def update_churn_probabilities(self,id_prob_pairs: List[Tuple[int, float]],batch_size: int = 1000):
        sql = "UPDATE clients SET churn_probability = ? WHERE id = ?;"
        with self.transaction() as cur:
            for i in range(0, len(id_prob_pairs), batch_size):
                chunk = id_prob_pairs[i:i + batch_size]
                rows = [(prob, cid) for cid, prob in chunk]
                cur.executemany(sql, rows)


    def fetch_all_for_training(self) -> List[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT id, age, deposit_amount, current_rate, market_rate, rate_diff, "
            "login_count, days_to_maturity, days_since_last_login, product_count, churn "
            "FROM clients;"
        )
        return cur.fetchall()


    def fetch_ids_for_scoring(self) -> List[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT id, age, deposit_amount, current_rate, market_rate, rate_diff, "
            "login_count, days_to_maturity, days_since_last_login, product_count "
            "FROM clients;"
        )
        return cur.fetchall()


    def get_dashboard_aggregates(self) -> Dict[str, Any]:
        cur = self._conn.execute(
            """
            SELECT
                COUNT(*) as total_clients,
                COALESCE(SUM(deposit_amount), 0) as total_portfolio,
                COALESCE(AVG(churn_probability), 0) as avg_risk,
                SUM(CASE WHEN churn_probability > ? THEN 1 ELSE 0 END) as high_risk_count,
                SUM(CASE WHEN churn_probability >= ? AND churn_probability <= ? THEN 1 ELSE 0 END) as mid_risk_count,
                SUM(CASE WHEN churn_probability < ? THEN 1 ELSE 0 END) as low_risk_count
            FROM clients;
            """,
            (RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD, RISK_HIGH_THRESHOLD, RISK_LOW_THRESHOLD),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


    def get_monthly_stats(self, months: int = 12) -> List[Dict]:
        cur = self._conn.execute(
            """
            SELECT
                strftime('%Y-%m', last_activity_date) as month,
                COUNT(*) as new_clients,
                COALESCE(SUM(deposit_amount), 0) as total_deposits,
                COALESCE(AVG(churn_probability), 0) as avg_risk
            FROM clients
            WHERE last_activity_date IS NOT NULL
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?;
            """,
            (months,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()  # хронологический порядок для графика
        return rows


    def get_risk_distribution(self) -> Dict[str, int]:
        agg = self.get_dashboard_aggregates()
        return {
            "green": agg.get("low_risk_count", 0) or 0,
            "yellow": agg.get("mid_risk_count", 0) or 0,
            "red": agg.get("high_risk_count", 0) or 0,
        }


    def get_clients(self, filter_type: str = "default", search_query: str = "",last_id: int = 0, limit: int = 100) -> Tuple[List[Dict], bool]:
        params: List[Any] = [];where_clauses = []

        if search_query:
            like = f"%{search_query}%"
            where_clauses.append(
                "(fio LIKE ? OR account_number LIKE ? OR card_number LIKE ?)"
            )
            params.extend([like, like, like])
        order_col = "id"
        order_dir = "ASC"
        if filter_type == "alphabet":
            order_col, order_dir = "fio", "ASC"
        elif filter_type == "risk_high":
            order_col, order_dir = "churn_probability", "DESC"
        elif filter_type == "risk_low":
            order_col, order_dir = "churn_probability", "ASC"
        if last_id:
            where_clauses.append("id > ?")
            params.append(last_id)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"""
            SELECT id, fio, account_number, card_number, deposit_amount,
                   current_rate, churn_probability, region
            FROM clients
            {where_sql}
            ORDER BY {order_col} {order_dir}, id ASC
            LIMIT ?;
        """
        params.append(limit + 1) 
        cur = self._conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        has_more = len(rows) > limit
        return rows[:limit], has_more


    def search_client(self, query: str, limit: int = 50) -> List[Dict]:
        like = f"%{query}%"
        cur = self._conn.execute(
            """
            SELECT id, fio, account_number, card_number, deposit_amount,
                   current_rate, churn_probability, region
            FROM clients
            WHERE fio LIKE ? OR account_number LIKE ? OR card_number LIKE ?
            LIMIT ?;
            """,
            (like, like, like, limit),
        )
        return [dict(r) for r in cur.fetchall()]


    def fetch_all_for_export(self) -> List[Dict]:
        cur = self._conn.execute("SELECT * FROM clients ORDER BY id ASC;")
        return [dict(r) for r in cur.fetchall()]


    def total_count_for_query(self, search_query: str = "") -> int:
        if search_query:
            like = f"%{search_query}%"
            cur = self._conn.execute(
                "SELECT COUNT(*) as c FROM clients "
                "WHERE fio LIKE ? OR account_number LIKE ? OR card_number LIKE ?;",
                (like, like, like),
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) as c FROM clients;")
        return cur.fetchone()["c"]


    def close(self):
        self._conn.close()
