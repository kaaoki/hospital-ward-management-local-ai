"""
audit_viewer.py
audit_log(操作ログ)を検索・表示するためのクエリ関数。
記録自体は db.py の log_action() が担当し、このモジュールは閲覧専用。
"""

from db import get_connection


ACTION_LABELS = {
    "view": "閲覧",
    "create": "作成",
    "edit": "編集",
    "admit": "入院",
    "discharge": "退院",
    "transfer": "転棟",
    "ai_query": "AI問い合わせ",
}


def query_audit_log(
    user_id: int | None = None,
    action: str | None = None,
    target_table: str | None = None,
    limit: int = 200,
):
    """
    監査ログを新しい順に取得する。フィルタはすべて任意。
    """
    conn = get_connection()
    query = """
        SELECT a.*, u.display_name AS user_display_name
        FROM audit_log a
        LEFT JOIN users u ON a.user_id = u.user_id
        WHERE 1=1
    """
    params = []

    if user_id:
        query += " AND a.user_id = ?"
        params.append(user_id)
    if action:
        query += " AND a.action = ?"
        params.append(action)
    if target_table:
        query += " AND a.target_table = ?"
        params.append(target_table)

    query += " ORDER BY a.timestamp DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_distinct_actions():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
    conn.close()
    return [r["action"] for r in rows]
