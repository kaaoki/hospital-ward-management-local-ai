"""
db.py
DB接続と監査ログ(audit_log)を扱う共通モジュール。
patient_manager.py, bed_manager.py などから共通して利用する。
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "hospital.db"


def get_connection() -> sqlite3.Connection:
    """外部キー制約を有効化した接続を返す。Row操作を辞書的に扱えるようRow factoryを設定。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def log_action(
    conn: sqlite3.Connection,
    user_id: int,
    action: str,
    target_table: str | None = None,
    target_id: int | None = None,
    detail: str | None = None,
) -> None:
    """
    操作ログを記録する。
    action例: 'view', 'create', 'edit', 'admit', 'discharge', 'transfer', 'ai_query'
    AI検索(ai_query)の場合はdetailに質問文を入れることで、
    「AIに何を問い合わせたか」まで追跡できるようにしている。
    """
    conn.execute(
        """INSERT INTO audit_log (user_id, action, target_table, target_id, detail, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            action,
            target_table,
            target_id,
            detail,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
