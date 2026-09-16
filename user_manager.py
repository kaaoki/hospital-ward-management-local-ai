"""
user_manager.py
ユーザー(ログインアカウント)の一覧取得・新規作成を行う。

設計方針:
- ユーザー管理は事務職(staff)ロールのみがアクセスできる想定(app.py側で制御)。
- パスワードは必ずbcryptでハッシュ化してから保存する。平文は一切保持しない。
- ユーザー作成自体も audit_log に記録し、「誰がどのアカウントを発行したか」を追跡できるようにする。
"""

import bcrypt
from db import get_connection, log_action


def list_users():
    """全ユーザーの一覧を取得する(パスワードハッシュは含めない)"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT user_id, username, role, display_name, created_at FROM users ORDER BY user_id"
    ).fetchall()
    conn.close()
    return rows


def username_exists(username: str) -> bool:
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row is not None


def create_user(username: str, plain_password: str, role: str, display_name: str, created_by: int) -> int:
    """
    新規ユーザーを作成する。
    role: 'doctor' / 'nurse' / 'staff'
    戻り値: 新規user_id
    """
    if username_exists(username):
        raise ValueError(f"ユーザー名 '{username}' は既に使用されています")
    if role not in ("doctor", "nurse", "staff"):
        raise ValueError(f"不正なroleです: {role}")

    password_hash = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, display_name),
    )
    conn.commit()
    new_user_id = cur.lastrowid

    log_action(
        conn, created_by, "create", "users", new_user_id,
        f"新規ユーザー作成: {username}({role})",
    )
    conn.close()
    return new_user_id
