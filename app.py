"""
app.py
院内患者管理支援ツール(ローカルAI版) - Streamlitメインアプリ

構成:
- ログイン画面(username/password, bcryptで照合)
- サイドバーでページ選択(ロールに応じて表示するページを出し分け)
- 各ページ: ダッシュボード / 患者検索・一覧 / 新規登録 / 患者詳細 / AI検索(今後実装)

起動方法:
    python -m streamlit run app.py
"""

import streamlit as st
import bcrypt
import pandas as pd

from db import get_connection
import patient_manager as pm
import bed_manager as bm
import ai_search
import user_manager as um
import audit_viewer as av

st.set_page_config(page_title="院内患者管理支援ツール", layout="wide")

NAV_KEY = "nav_page"  # サイドバーのページ選択ラジオボタンのsession_stateキー


# ============================================================
# 認証まわり
# ============================================================
def authenticate(username: str, password: str):
    """usernameとpasswordを照合し、成功すればユーザー情報のRowを返す。失敗すればNone。"""
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if user is None:
        return None
    if bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return user
    return None


def login_page():
    st.title("院内患者管理支援ツール")
    st.caption("ローカルAI版(ポートフォリオ用サンプル・架空データ)")

    with st.form("login_form"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン")

    if submitted:
        user = authenticate(username, password)
        if user is None:
            st.error("ユーザー名またはパスワードが正しくありません")
        else:
            st.session_state["user"] = dict(user)
            st.rerun()

    with st.expander("デモ用ログイン情報"):
        st.write(
            "医師: dr_yamada / password123\n\n"
            "看護師: nurse_suzuki / password123\n\n"
            "事務: staff_takahashi / password123"
        )


def logout():
    del st.session_state["user"]
    st.rerun()


# ============================================================
# ページ: ダッシュボード
# ============================================================
def page_dashboard(user):
    st.header("ダッシュボード")

    bed_rows = [dict(r) for r in bm.get_ward_bed_status()]
    df = pd.DataFrame(bed_rows)

    total_beds = len(df)
    occupied = df["is_occupied"].sum() if not df.empty else 0
    available = total_beds - occupied

    col1, col2, col3 = st.columns(3)
    col1.metric("総ベッド数", total_beds)
    col2.metric("使用中", int(occupied))
    col3.metric("空床", int(available))

    st.subheader("病棟ごとの空床状況")
    if not df.empty:
        summary = (
            df.groupby("ward_name")
            .agg(総ベッド数=("bed_id", "count"), 使用中=("is_occupied", "sum"))
            .reset_index()
        )
        summary["空床"] = summary["総ベッド数"] - summary["使用中"]
        st.dataframe(summary, use_container_width=True, hide_index=True)

    st.subheader("入院中の患者一覧")
    admitted_df = df[df["patient_id"].notna()] if not df.empty else pd.DataFrame()
    if not admitted_df.empty:
        display_df = admitted_df[
            ["ward_name", "room_number", "bed_label", "patient_name"]
        ].rename(
            columns={
                "ward_name": "病棟",
                "room_number": "病室",
                "bed_label": "ベッド",
                "patient_name": "患者名",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("現在入院中の患者はいません")


# ============================================================
# ページ: 患者検索・一覧
# ============================================================
def page_patient_search(user):
    st.header("患者検索・一覧")

    col1, col2, col3 = st.columns(3)
    keyword = col1.text_input("氏名(部分一致)")
    status = col2.selectbox("入院状況", ["", "入院待ち", "入院中", "退院済み"])
    department = col3.selectbox("診療科", [""] + pm.DEPARTMENTS)

    results = pm.search_patients(
        keyword=keyword, status=status or None, department=department or None
    )

    if not results:
        st.info("該当する患者が見つかりませんでした")
        return

    df = pd.DataFrame([dict(r) for r in results])
    display_df = df[["patient_id", "name", "birth_date", "gender", "department", "status"]].rename(
        columns={
            "patient_id": "ID",
            "name": "氏名",
            "birth_date": "生年月日",
            "gender": "性別",
            "department": "診療科",
            "status": "状況",
        }
    )

    st.caption("行をクリックすると、その患者の詳細ページを開きます。")
    event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="patient_search_results",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        selected_idx = selected_rows[0]
        selected_id = int(df.iloc[selected_idx]["patient_id"])
        st.session_state["pending_nav"] = "患者詳細"
        st.session_state["selected_patient_id"] = selected_id
        st.rerun()


# ============================================================
# ページ: 新規登録
# ============================================================
def page_patient_register(user):
    st.header("患者新規登録")

    conn = get_connection()
    doctors = conn.execute("SELECT user_id, display_name FROM users WHERE role = 'doctor'").fetchall()
    conn.close()
    doctor_options = {d["display_name"]: d["user_id"] for d in doctors}

    with st.form("register_form"):
        name = st.text_input("氏名")
        birth_date = st.date_input("生年月日")
        gender = st.selectbox("性別", ["男性", "女性", "その他"])
        department = st.selectbox("診療科", pm.DEPARTMENTS)
        doctor_name = st.selectbox("主治医", list(doctor_options.keys()))
        status = st.selectbox("入院状況", ["入院待ち", "入院中", "退院済み"])
        submitted = st.form_submit_button("登録")

    if submitted:
        if not name or not department:
            st.error("氏名と診療科は必須です")
            return

        new_id = pm.create_patient(
            {
                "name": name,
                "birth_date": birth_date.strftime("%Y-%m-%d"),
                "gender": gender,
                "department": department,
                "primary_doctor_id": doctor_options[doctor_name],
                "status": status,
            },
            created_by=user["user_id"],
        )
        st.success(f"患者を登録しました(ID: {new_id})")


# ============================================================
# ページ: 患者詳細(編集・入退院/転棟・変更履歴)
# ============================================================
def page_patient_detail(user):
    st.header("患者詳細")

    patient_id = st.session_state.get("selected_patient_id")
    if patient_id is None:
        st.info("「患者検索・一覧」から患者を選択してください")
        return

    patient = pm.get_patient(patient_id)
    if patient is None:
        st.error("患者情報が見つかりません")
        return

    pm.record_view(patient_id, viewed_by=user["user_id"])

    st.subheader(f"{patient['name']}(ID: {patient['patient_id']})")
    col1, col2 = st.columns(2)
    col1.write(f"生年月日: {patient['birth_date']}")
    col1.write(f"性別: {patient['gender']}")
    col2.write(f"診療科: {patient['department']}")
    col2.write(f"状況: {patient['status']}")

    if patient["status"] == "入院中":
        bed_info = bm.get_current_bed_for_patient(patient_id)
        if bed_info:
            st.info(
                f"🛏️ 入院先: {bed_info['ward_name']} {bed_info['room_number']}号室 "
                f"{bed_info['bed_label']}ベッド(入院日時: {bed_info['admitted_at']})"
            )

    st.divider()
    st.subheader("情報編集")
    with st.form("edit_form"):
        current_dept_index = (
            pm.DEPARTMENTS.index(patient["department"]) if patient["department"] in pm.DEPARTMENTS else 0
        )
        new_department = st.selectbox("診療科", pm.DEPARTMENTS, index=current_dept_index)
        new_status = st.selectbox(
            "入院状況",
            ["入院待ち", "入院中", "退院済み"],
            index=["入院待ち", "入院中", "退院済み"].index(patient["status"]),
        )
        submitted = st.form_submit_button("更新")

    if submitted:
        pm.update_patient(
            patient_id,
            {"department": new_department, "status": new_status},
            changed_by=user["user_id"],
        )
        st.success("更新しました")
        st.rerun()

    st.divider()
    st.subheader("入院・退院・転棟")

    if patient["status"] != "入院中":
        available_beds = bm.get_available_beds()
        if available_beds:
            bed_labels = {
                f"{b['ward_name']} {b['room_number']}-{b['bed_label']}": b["bed_id"]
                for b in available_beds
            }
            selected_bed_label = st.selectbox("入院先ベッド", list(bed_labels.keys()))
            if st.button("入院させる"):
                bm.admit_patient(patient_id, bed_labels[selected_bed_label], performed_by=user["user_id"])
                st.success("入院処理を行いました")
                st.rerun()
        else:
            st.warning("現在空いているベッドがありません")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("退院させる"):
                bm.discharge_patient(patient_id, performed_by=user["user_id"])
                st.success("退院処理を行いました")
                st.rerun()
        with col_b:
            available_beds = bm.get_available_beds()
            if available_beds:
                bed_labels = {
                    f"{b['ward_name']} {b['room_number']}-{b['bed_label']}": b["bed_id"]
                    for b in available_beds
                }
                selected_bed_label = st.selectbox("転棟先ベッド", list(bed_labels.keys()))
                if st.button("転棟させる"):
                    bm.transfer_patient(
                        patient_id, bed_labels[selected_bed_label], performed_by=user["user_id"]
                    )
                    st.success("転棟処理を行いました")
                    st.rerun()

    st.divider()
    st.subheader("変更履歴")
    history = pm.get_patient_history(patient_id)
    if history:
        hist_df = pd.DataFrame([dict(h) for h in history])
        display_df = hist_df[
            ["changed_at", "changed_by_name", "field_name", "old_value", "new_value"]
        ].rename(
            columns={
                "changed_at": "日時",
                "changed_by_name": "変更者",
                "field_name": "項目",
                "old_value": "変更前",
                "new_value": "変更後",
            }
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.caption("変更履歴はありません")


# ============================================================
# ページ: AI検索(自然言語での問い合わせ、ローカルLLM連携)
# ============================================================
def page_ai_search(user):
    st.header("AI検索")
    st.caption(
        "患者の実名は仮名化した上でローカルLLMに渡し、回答表示時に実名へ復元しています。"
        "外部への通信は一切行いません。"
    )
    st.caption("※ 診断・治療方針の判断は行いません。あくまで検索・要約による業務支援です。")

    example_cols = st.columns(3)
    examples = ["循環器内科の入院患者を教えて", "3階東病棟で空いているベッドは？", "退院済みの患者は誰ですか？"]
    for col, example in zip(example_cols, examples):
        col.caption(f"例:「{example}」")

    question = st.text_input("質問を入力してください", key="ai_question")

    if st.button("質問する") and question:
        with st.spinner("ローカルLLMが回答を生成しています..."):
            answer = ai_search.ask(question, asked_by=user["user_id"])
        st.markdown("**回答:**")
        st.write(answer)


# ============================================================
# ページ: 監査ログ(事務職のみ閲覧可能)
# ============================================================
def page_audit_log(user):
    st.header("監査ログ")
    st.caption("誰が・いつ・何を操作したか(AIへの問い合わせ内容を含む)を確認できます。")

    col1, col2 = st.columns(2)
    action_options = [""] + av.get_distinct_actions()
    action = col1.selectbox(
        "操作種別",
        action_options,
        format_func=lambda a: av.ACTION_LABELS.get(a, "すべて") if a else "すべて",
    )
    limit = col2.number_input("表示件数", min_value=10, max_value=1000, value=200, step=10)

    rows = av.query_audit_log(action=action or None, limit=limit)
    if not rows:
        st.info("該当するログがありません")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    df["action_label"] = df["action"].map(lambda a: av.ACTION_LABELS.get(a, a))
    display_df = df[
        ["timestamp", "user_display_name", "action_label", "target_table", "target_id", "detail"]
    ].rename(
        columns={
            "timestamp": "日時",
            "user_display_name": "操作者",
            "action_label": "操作種別",
            "target_table": "対象テーブル",
            "target_id": "対象ID",
            "detail": "詳細",
        }
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ============================================================
# ページ: ユーザー管理(事務職のみアクセス可能)
# ============================================================
def page_user_management(user):
    st.header("ユーザー管理")

    st.subheader("ユーザー一覧")
    users = um.list_users()
    df = pd.DataFrame([dict(u) for u in users])
    display_df = df.rename(
        columns={
            "user_id": "ID",
            "username": "ユーザー名",
            "role": "ロール",
            "display_name": "表示名",
            "created_at": "作成日時",
        }
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("新規ユーザー作成")
    with st.form("create_user_form"):
        username = st.text_input("ユーザー名(ログインID)")
        password = st.text_input("初期パスワード", type="password")
        role = st.selectbox("ロール", ["doctor", "nurse", "staff"], format_func=lambda r: {
            "doctor": "医師", "nurse": "看護師", "staff": "事務"
        }[r])
        display_name = st.text_input("表示名(例: 山田 太郎(医師))")
        submitted = st.form_submit_button("作成")

    if submitted:
        if not username or not password or not display_name:
            st.error("すべての項目を入力してください")
        else:
            try:
                new_id = um.create_user(username, password, role, display_name, created_by=user["user_id"])
                st.success(f"ユーザーを作成しました(ID: {new_id})")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


# ============================================================
# メイン
# ============================================================
def main():
    if "user" not in st.session_state:
        login_page()
        return

    user = st.session_state["user"]

    st.sidebar.title("院内患者管理支援ツール")
    st.sidebar.write(f"ログイン中: {user['display_name']}({user['role']})")

    pages = ["ダッシュボード", "患者検索・一覧", "患者詳細"]
    if user["role"] in ("doctor", "staff"):
        pages.insert(2, "新規登録")
    pages.append("AI検索")
    if user["role"] == "staff":
        pages += ["監査ログ", "ユーザー管理"]

    # NAV_KEYの値がまだ無い、またはロール変更等で現在のpages一覧に存在しない場合は先頭にリセット
    if NAV_KEY not in st.session_state or st.session_state[NAV_KEY] not in pages:
        st.session_state[NAV_KEY] = pages[0]

    # 他のページ(例: 患者検索・一覧の行クリック)からの遷移予約があれば、
    # ウィジェット生成前にここで反映する(生成後にNAV_KEYを直接書き換えるとエラーになるため)
    if "pending_nav" in st.session_state:
        pending = st.session_state.pop("pending_nav")
        if pending in pages:
            st.session_state[NAV_KEY] = pending

    page = st.sidebar.radio("ページ選択", pages, key=NAV_KEY)

    if st.sidebar.button("ログアウト"):
        logout()

    if page == "ダッシュボード":
        page_dashboard(user)
    elif page == "患者検索・一覧":
        page_patient_search(user)
    elif page == "新規登録":
        page_patient_register(user)
    elif page == "患者詳細":
        page_patient_detail(user)
    elif page == "AI検索":
        page_ai_search(user)
    elif page == "監査ログ":
        page_audit_log(user)
    elif page == "ユーザー管理":
        page_user_management(user)


if __name__ == "__main__":
    main()
