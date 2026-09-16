"""
bed_manager.py
病棟・病室・ベッドの空床管理と、入院・退院・転棟の処理を行う。

設計方針:
- 「現在の入院状況」は admissions テーブルの discharged_at IS NULL で判定する。
  ベッド側の is_occupied フラグは高速な一覧表示用のキャッシュとして持たせ、
  入退院・転棟のたびに整合するよう更新する。
- 入院・退院・転棟はいずれも audit_log に記録し、patients.status も連動して更新する。
"""

from datetime import datetime
from db import get_connection, log_action


def get_ward_bed_status():
    """
    病棟ごとのベッド一覧と、現在の入居患者(いれば)を取得する。
    空床状況の一覧表示に使う。
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            w.ward_name,
            r.room_number,
            b.bed_id,
            b.bed_label,
            b.is_occupied,
            p.patient_id,
            p.name AS patient_name
        FROM beds b
        JOIN rooms r ON b.room_id = r.room_id
        JOIN wards w ON r.ward_id = w.ward_id
        LEFT JOIN admissions a ON a.bed_id = b.bed_id AND a.discharged_at IS NULL
        LEFT JOIN patients p ON a.patient_id = p.patient_id
        ORDER BY w.ward_name, r.room_number, b.bed_label
        """
    ).fetchall()
    conn.close()
    return rows


def get_current_bed_for_patient(patient_id: int):
    """
    指定患者が現在入院中の場合、そのベッド情報(病棟・病室・ベッド)を返す。
    入院中でなければNoneを返す。
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT w.ward_name, r.room_number, b.bed_label, a.admitted_at
        FROM admissions a
        JOIN beds b ON a.bed_id = b.bed_id
        JOIN rooms r ON b.room_id = r.room_id
        JOIN wards w ON r.ward_id = w.ward_id
        WHERE a.patient_id = ? AND a.discharged_at IS NULL
        """,
        (patient_id,),
    ).fetchone()
    conn.close()
    return row


def get_available_beds(ward_name: str | None = None):
    """空いているベッドの一覧を取得する(入院・転棟先の選択肢に使う)"""
    conn = get_connection()
    query = """
        SELECT b.bed_id, w.ward_name, r.room_number, b.bed_label
        FROM beds b
        JOIN rooms r ON b.room_id = r.room_id
        JOIN wards w ON r.ward_id = w.ward_id
        WHERE b.is_occupied = 0
    """
    params = []
    if ward_name:
        query += " AND w.ward_name = ?"
        params.append(ward_name)
    query += " ORDER BY w.ward_name, r.room_number, b.bed_label"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def admit_patient(patient_id: int, bed_id: int, performed_by: int) -> None:
    """
    患者を指定ベッドに入院させる。
    - ベッドが空いていることを確認
    - admissions に新規レコードを作成
    - beds.is_occupied を更新
    - patients.status を「入院中」に更新
    """
    conn = get_connection()
    bed = conn.execute("SELECT is_occupied FROM beds WHERE bed_id = ?", (bed_id,)).fetchone()
    if bed is None:
        conn.close()
        raise ValueError(f"bed_id={bed_id} が見つかりません")
    if bed["is_occupied"]:
        conn.close()
        raise ValueError("指定されたベッドは既に使用中です")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO admissions (patient_id, bed_id, admitted_at) VALUES (?, ?, ?)",
        (patient_id, bed_id, now),
    )
    conn.execute("UPDATE beds SET is_occupied = 1 WHERE bed_id = ?", (bed_id,))
    conn.execute(
        "UPDATE patients SET status = '入院中', updated_at = ? WHERE patient_id = ?",
        (now, patient_id),
    )
    conn.commit()
    log_action(conn, performed_by, "admit", "patients", patient_id, f"bed_id={bed_id} に入院")
    conn.close()


def discharge_patient(patient_id: int, performed_by: int) -> None:
    """
    患者を退院させる。
    - 現在のadmissionsレコード(discharged_at IS NULL)を検索し、discharged_atを設定
    - beds.is_occupied を0に戻す
    - patients.status を「退院済み」に更新
    """
    conn = get_connection()
    admission = conn.execute(
        "SELECT admission_id, bed_id FROM admissions WHERE patient_id = ? AND discharged_at IS NULL",
        (patient_id,),
    ).fetchone()
    if admission is None:
        conn.close()
        raise ValueError("現在入院中のレコードが見つかりません")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE admissions SET discharged_at = ? WHERE admission_id = ?",
        (now, admission["admission_id"]),
    )
    conn.execute("UPDATE beds SET is_occupied = 0 WHERE bed_id = ?", (admission["bed_id"],))
    conn.execute(
        "UPDATE patients SET status = '退院済み', updated_at = ? WHERE patient_id = ?",
        (now, patient_id),
    )
    conn.commit()
    log_action(conn, performed_by, "discharge", "patients", patient_id)
    conn.close()


def transfer_patient(patient_id: int, new_bed_id: int, performed_by: int) -> None:
    """
    患者を別のベッドに転棟させる。
    - 現在のadmissionsレコードをdischarged_atで終了させる
    - 新しいadmissionsレコードをtransfer_from_bed_id付きで作成
    - 旧ベッドをis_occupied=0、新ベッドをis_occupied=1に更新
    """
    conn = get_connection()
    current = conn.execute(
        "SELECT admission_id, bed_id FROM admissions WHERE patient_id = ? AND discharged_at IS NULL",
        (patient_id,),
    ).fetchone()
    if current is None:
        conn.close()
        raise ValueError("現在入院中のレコードが見つかりません(転棟には入院中である必要があります)")

    new_bed = conn.execute("SELECT is_occupied FROM beds WHERE bed_id = ?", (new_bed_id,)).fetchone()
    if new_bed is None:
        conn.close()
        raise ValueError(f"bed_id={new_bed_id} が見つかりません")
    if new_bed["is_occupied"]:
        conn.close()
        raise ValueError("転棟先のベッドは既に使用中です")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    old_bed_id = current["bed_id"]

    conn.execute(
        "UPDATE admissions SET discharged_at = ? WHERE admission_id = ?",
        (now, current["admission_id"]),
    )
    conn.execute(
        """INSERT INTO admissions (patient_id, bed_id, admitted_at, transfer_from_bed_id)
           VALUES (?, ?, ?, ?)""",
        (patient_id, new_bed_id, now, old_bed_id),
    )
    conn.execute("UPDATE beds SET is_occupied = 0 WHERE bed_id = ?", (old_bed_id,))
    conn.execute("UPDATE beds SET is_occupied = 1 WHERE bed_id = ?", (new_bed_id,))
    conn.commit()
    log_action(
        conn, performed_by, "transfer", "patients", patient_id,
        f"bed_id={old_bed_id} から bed_id={new_bed_id} へ転棟",
    )
    conn.close()
