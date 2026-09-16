"""
init_db.py
DB初期化 + ダミーデータ投入スクリプト。

使い方:
    python init_db.py

- schema.sql を実行してテーブルを作成
- 病棟/病室/ベッドのマスタと、架空の患者・ユーザーのダミーデータを投入
- 患者名・生年月日はすべて架空のもの(実在の人物とは無関係)
"""

import sqlite3
import bcrypt
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "hospital.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_schema(conn: sqlite3.Connection) -> None:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())


def seed_wards_rooms_beds(conn: sqlite3.Connection) -> dict:
    """病棟2つ、各病棟3部屋、各部屋2ベッドのダミー構成を作る。戻り値: bed_id一覧(病棟名->部屋番号->ベッドラベル->bed_id)"""
    cur = conn.cursor()
    bed_ids = {}

    wards = ["3階東病棟", "3階西病棟"]
    for ward_name in wards:
        cur.execute("INSERT INTO wards (ward_name) VALUES (?)", (ward_name,))
        ward_id = cur.lastrowid
        bed_ids[ward_name] = {}

        for room_num in range(1, 4):  # 各病棟3部屋
            room_number = f"{ward_name[0]}0{room_num}" if False else f"30{room_num}"
            cur.execute(
                "INSERT INTO rooms (ward_id, room_number) VALUES (?, ?)",
                (ward_id, room_number),
            )
            room_id = cur.lastrowid
            bed_ids[ward_name][room_number] = {}

            for bed_label in ["A", "B"]:  # 各部屋2ベッド
                cur.execute(
                    "INSERT INTO beds (room_id, bed_label, is_occupied) VALUES (?, ?, 0)",
                    (room_id, bed_label),
                )
                bed_ids[ward_name][room_number][bed_label] = cur.lastrowid

    conn.commit()
    return bed_ids


def seed_users(conn: sqlite3.Connection) -> dict:
    """ダミーのユーザー(医師/看護師/事務)を投入。戻り値: username -> user_id"""
    cur = conn.cursor()
    users = [
        ("dr_yamada", "password123", "doctor", "山田 太郎(医師)"),
        ("dr_sato", "password123", "doctor", "佐藤 花子(医師)"),
        ("nurse_suzuki", "password123", "nurse", "鈴木 一郎(看護師)"),
        ("staff_takahashi", "password123", "staff", "高橋 次郎(事務)"),
    ]
    user_ids = {}
    for username, plain_pw, role, display_name in users:
        cur.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
            (username, hash_password(plain_pw), role, display_name),
        )
        user_ids[username] = cur.lastrowid

    conn.commit()
    return user_ids


def seed_patients_and_admissions(conn: sqlite3.Connection, bed_ids: dict, user_ids: dict) -> None:
    """架空の患者データと、一部を入院中として登録"""
    cur = conn.cursor()

    dr_yamada_id = user_ids["dr_yamada"]
    dr_sato_id = user_ids["dr_sato"]

    patients = [
        ("架空 一郎", "1950-04-12", "男性", "循環器内科", dr_yamada_id, "入院中"),
        ("架空 花子", "1972-11-03", "女性", "整形外科", dr_sato_id, "入院中"),
        ("架空 次郎", "1988-07-22", "男性", "消化器内科", dr_yamada_id, "入院待ち"),
        ("架空 三郎", "1965-01-30", "男性", "呼吸器内科", dr_sato_id, "退院済み"),
        ("架空 良子", "1990-09-15", "女性", "循環器内科", dr_yamada_id, "入院中"),
    ]

    patient_ids = []
    now = datetime.now()
    for name, birth_date, gender, dept, doctor_id, status in patients:
        cur.execute(
            """INSERT INTO patients
               (name, birth_date, gender, department, primary_doctor_id, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, birth_date, gender, dept, doctor_id, status),
        )
        patient_ids.append((cur.lastrowid, status))

    conn.commit()

    # 入院中の患者をベッドに割り当てる(空いているベッドから順に使用)
    available_beds = []
    for ward_name, rooms in bed_ids.items():
        for room_number, beds in rooms.items():
            for bed_label, bed_id in beds.items():
                available_beds.append(bed_id)

    bed_iter = iter(available_beds)
    for patient_id, status in patient_ids:
        if status in ("入院中",):
            bed_id = next(bed_iter)
            admitted_at = now - timedelta(days=3)
            cur.execute(
                "INSERT INTO admissions (patient_id, bed_id, admitted_at) VALUES (?, ?, ?)",
                (patient_id, bed_id, admitted_at.strftime("%Y-%m-%d %H:%M:%S")),
            )
            cur.execute("UPDATE beds SET is_occupied = 1 WHERE bed_id = ?", (bed_id,))
        elif status == "退院済み":
            bed_id = next(bed_iter)
            admitted_at = now - timedelta(days=10)
            discharged_at = now - timedelta(days=2)
            cur.execute(
                """INSERT INTO admissions (patient_id, bed_id, admitted_at, discharged_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    patient_id,
                    bed_id,
                    admitted_at.strftime("%Y-%m-%d %H:%M:%S"),
                    discharged_at.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            # 退院済みなのでベッドは空きのまま(is_occupied=0)

    conn.commit()


def main():
    if DB_PATH.exists():
        print(f"既存のDBファイルが見つかりました: {DB_PATH}")
        answer = input("削除して作り直しますか? (y/N): ").strip().lower()
        if answer == "y":
            DB_PATH.unlink()
        else:
            print("処理を中止しました。")
            return

    conn = sqlite3.connect(DB_PATH)
    try:
        create_schema(conn)
        bed_ids = seed_wards_rooms_beds(conn)
        user_ids = seed_users(conn)
        seed_patients_and_admissions(conn, bed_ids, user_ids)
        print(f"DB初期化が完了しました: {DB_PATH}")
        print("投入したログインユーザー例: dr_yamada / password123 (医師)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
