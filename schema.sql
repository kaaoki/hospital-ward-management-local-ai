-- ============================================================
-- 院内患者管理支援ツール(ローカルAI版) DBスキーマ
-- SQLite用。本番運用ではSQL Server等への移行を想定。
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 1. users: ログイン・権限管理
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('doctor', 'nurse', 'staff')),
    display_name    TEXT NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ------------------------------------------------------------
-- 2. patients: 患者マスタ
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    patient_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    birth_date          DATE NOT NULL,
    gender              TEXT NOT NULL CHECK (gender IN ('男性', '女性', 'その他')),
    department          TEXT NOT NULL,
    primary_doctor_id   INTEGER,
    status              TEXT NOT NULL DEFAULT '入院待ち'
                            CHECK (status IN ('入院待ち', '入院中', '退院済み')),
    created_at          DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (primary_doctor_id) REFERENCES users(user_id)
);

-- ------------------------------------------------------------
-- 3. wards / rooms / beds: 病棟・病室・ベッド管理
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wards (
    ward_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_name   TEXT NOT NULL UNIQUE   -- 例: "3階東病棟"
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ward_id     INTEGER NOT NULL,
    room_number TEXT NOT NULL,          -- 例: "301"
    FOREIGN KEY (ward_id) REFERENCES wards(ward_id),
    UNIQUE (ward_id, room_number)
);

CREATE TABLE IF NOT EXISTS beds (
    bed_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id      INTEGER NOT NULL,
    bed_label    TEXT NOT NULL,         -- 例: "A", "B"
    is_occupied  INTEGER NOT NULL DEFAULT 0 CHECK (is_occupied IN (0, 1)),
    FOREIGN KEY (room_id) REFERENCES rooms(room_id),
    UNIQUE (room_id, bed_label)
);

-- ------------------------------------------------------------
-- 4. admissions: 入院・退院・転棟履歴
--    現在の入院状況は discharged_at IS NULL のレコードで判定する
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admissions (
    admission_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id              INTEGER NOT NULL,
    bed_id                  INTEGER NOT NULL,
    admitted_at              DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    discharged_at           DATETIME,          -- NULLなら入院中
    transfer_from_bed_id    INTEGER,           -- 転棟の場合の転棟元ベッド
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (bed_id) REFERENCES beds(bed_id),
    FOREIGN KEY (transfer_from_bed_id) REFERENCES beds(bed_id)
);

-- ------------------------------------------------------------
-- 5. patient_history: 患者情報の変更履歴(データの中身の変更)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patient_history (
    history_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   INTEGER NOT NULL,
    changed_by   INTEGER NOT NULL,
    changed_at   DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    field_name   TEXT NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (changed_by) REFERENCES users(user_id)
);

-- ------------------------------------------------------------
-- 6. audit_log: 操作ログ(誰が・いつ・何をしたか。AI問い合わせも含む)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    action        TEXT NOT NULL,        -- 'view' / 'edit' / 'ai_query' 等
    target_table  TEXT,
    target_id     INTEGER,
    detail        TEXT,                 -- 補足(AI検索なら質問文など)
    timestamp     DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- ------------------------------------------------------------
-- インデックス(検索・空床確認のパフォーマンス対策)
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_admissions_current
    ON admissions (bed_id, discharged_at);

CREATE INDEX IF NOT EXISTS idx_patients_status
    ON patients (status);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_time
    ON audit_log (user_id, timestamp);
