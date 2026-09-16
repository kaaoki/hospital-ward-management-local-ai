"""
patient_manager.py
患者情報の登録・検索・編集と、変更履歴(patient_history)の記録を行う。

設計方針:
- 患者情報の更新は必ず update_patient() 経由で行い、
  変更前後の値をフィールド単位で patient_history に記録する。
  (「誰が・いつ・何を・どう変えたか」を後から追跡できるようにするため)
- 検索・閲覧などの参照系操作も audit_log に 'view' として記録する。
  (案件要件の「操作履歴・変更履歴の管理」に対応)
"""

from datetime import datetime
from db import get_connection, log_action

# patients テーブルのうち、編集可能なフィールド
EDITABLE_FIELDS = ["name", "birth_date", "gender", "department", "primary_doctor_id", "status"]

# 診療科の選択肢(検索・編集・登録画面で共通利用)
DEPARTMENTS = [
    "循環器内科",
    "消化器内科",
    "呼吸器内科",
    "腎臓内科",
    "内分泌内科",
    "神経内科",
    "外科",
    "整形外科",
    "脳神経外科",
    "小児科",
    "産婦人科",
    "皮膚科",
    "泌尿器科",
    "眼科",
    "耳鼻咽喉科",
    "精神科",
    "麻酔科",
    "救急科",
]


def search_patients(keyword: str = "", status: str | None = None, department: str | None = None):
    """
    患者を検索する。keywordは氏名の部分一致。statusやdepartmentで絞り込み可能。
    戻り値: sqlite3.Row のリスト
    """
    conn = get_connection()
    query = "SELECT * FROM patients WHERE 1=1"
    params = []

    if keyword:
        query += " AND name LIKE ?"
        params.append(f"%{keyword}%")
    if status:
        query += " AND status = ?"
        params.append(status)
    if department:
        query += " AND department = ?"
        params.append(department)

    query += " ORDER BY patient_id"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def get_patient(patient_id: int):
    """patient_idで1件取得"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    conn.close()
    return row


def create_patient(data: dict, created_by: int) -> int:
    """
    新規患者を登録する。
    data: {name, birth_date, gender, department, primary_doctor_id, status}
    戻り値: 新規patient_id
    """
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO patients (name, birth_date, gender, department, primary_doctor_id, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            data["name"],
            data["birth_date"],
            data["gender"],
            data["department"],
            data.get("primary_doctor_id"),
            data.get("status", "入院待ち"),
        ),
    )
    conn.commit()
    patient_id = cur.lastrowid

    log_action(conn, created_by, "create", "patients", patient_id, f"新規患者登録: {data['name']}")
    conn.close()
    return patient_id


def update_patient(patient_id: int, updates: dict, changed_by: int) -> None:
    """
    患者情報を更新する。updatesに含まれるフィールドのみ更新し、
    変更があったフィールドごとに patient_history へ old/new を記録する。
    """
    conn = get_connection()
    current = conn.execute(
        "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()

    if current is None:
        conn.close()
        raise ValueError(f"patient_id={patient_id} が見つかりません")

    changed_fields = []
    for field, new_value in updates.items():
        if field not in EDITABLE_FIELDS:
            continue
        old_value = current[field]
        if str(old_value) != str(new_value):
            conn.execute(
                """INSERT INTO patient_history
                   (patient_id, changed_by, changed_at, field_name, old_value, new_value)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    patient_id,
                    changed_by,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    field,
                    str(old_value) if old_value is not None else None,
                    str(new_value) if new_value is not None else None,
                ),
            )
            changed_fields.append(field)

    if changed_fields:
        set_clause = ", ".join(f"{f} = ?" for f in changed_fields)
        values = [updates[f] for f in changed_fields]
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        values.append(patient_id)
        conn.execute(
            f"UPDATE patients SET {set_clause}, updated_at = ? WHERE patient_id = ?",
            values,
        )
        conn.commit()
        log_action(
            conn, changed_by, "edit", "patients", patient_id,
            f"更新フィールド: {', '.join(changed_fields)}",
        )

    conn.close()


def get_patient_history(patient_id: int):
    """指定患者の変更履歴を新しい順に取得"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT h.*, u.display_name AS changed_by_name
           FROM patient_history h
           LEFT JOIN users u ON h.changed_by = u.user_id
           WHERE h.patient_id = ?
           ORDER BY h.changed_at DESC""",
        (patient_id,),
    ).fetchall()
    conn.close()
    return rows


def record_view(patient_id: int, viewed_by: int) -> None:
    """患者情報の閲覧を監査ログに記録する(誰がいつ誰の情報を見たかを追跡)"""
    conn = get_connection()
    log_action(conn, viewed_by, "view", "patients", patient_id)
    conn.close()
