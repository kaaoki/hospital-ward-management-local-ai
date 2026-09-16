"""
ai_search.py
自然言語による患者・病棟情報の検索・要約を、ローカルLLM(Ollama)で実現する。

設計方針(セキュリティ・情報管理面が最重要):
1. LLMに渡す前に、患者の実名を "P001" のような仮名IDに置き換える(仮名化)。
   → 万が一プロンプトやログが外部に漏れても、実名と紐付かない状態にするため。
2. LLMには「diagnosis(診断)や治療方針の判断は行わない」ことを明示し、
   あくまで与えられたデータの検索・要約に限定させる。
3. LLMからの回答に含まれる仮名ID("P001"等)を、表示直前に実名へ復元する。
4. すべての問い合わせ内容(質問文)を audit_log に 'ai_query' として記録する。
   → 「AIに何を尋ねたか」を後から監査できるようにするため。

前提: Ollamaがローカルで起動していること(デフォルト http://localhost:11434)。
モデルは環境変数 OLLAMA_MODEL で切り替え可能(デフォルト: llama3-elyza-jp-8b の想定)。
"""

import os
import json
import re
import requests

from db import get_connection, log_action
import bed_manager as bm

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "elyza:8b")

SYSTEM_INSTRUCTION = """あなたは病院内の業務支援アシスタントです。
以下のルールを厳守してください。

- 与えられた「データ」の範囲内でのみ回答してください。データにない情報は「データにありません」と答えてください。
- 診断・治療方針の判断は絶対に行わないでください。あなたの役割は検索・要約による業務効率化の支援のみです。
- 患者は実名ではなく "P001" のような仮名IDで記載されています。回答でも必ずこの仮名IDのまま使用してください。実名を推測して補完しないでください。
- 数値を扱う場合は、必ずデータの数値を確認してから回答してください。独自の基準で判断しないでください。
- 敬体(です・ます調)で、簡潔に回答してください。
"""


def _build_context_and_mapping():
    """
    現在の患者・ベッド状況を取得し、患者の実名を仮名IDに置き換えたデータと、
    仮名ID→実名の対応表(mapping)を作成する。
    """
    conn = get_connection()
    patients = conn.execute(
        "SELECT patient_id, name, department, status FROM patients ORDER BY patient_id"
    ).fetchall()
    conn.close()

    mapping = {}  # 仮名ID -> 実名
    context_patients = []
    for p in patients:
        pseudo_id = f"P{p['patient_id']:03d}"
        mapping[pseudo_id] = p["name"]
        context_patients.append(
            {
                "id": pseudo_id,
                "department": p["department"],
                "status": p["status"],
            }
        )

    bed_rows = [dict(r) for r in bm.get_ward_bed_status()]
    context_beds = []
    for b in bed_rows:
        entry = {
            "ward": b["ward_name"],
            "room": b["room_number"],
            "bed": b["bed_label"],
            "occupied": bool(b["is_occupied"]),
        }
        if b["patient_id"] is not None:
            entry["patient_id"] = f"P{b['patient_id']:03d}"
        context_beds.append(entry)

    context = {"patients": context_patients, "beds": context_beds}
    return context, mapping


def _pseudonymize_question(question: str, mapping: dict) -> str:
    """
    質問文中に実名が含まれる場合、仮名IDに置き換える。
    (例:「田中さんの状況は?」→「P003さんの状況は?」)
    完全一致のみ対応。部分一致・表記ゆれの誤爆を避けるための簡易実装。
    """
    pseudonymized = question
    for pseudo_id, real_name in mapping.items():
        if real_name in pseudonymized:
            pseudonymized = pseudonymized.replace(real_name, pseudo_id)
    return pseudonymized


def _depseudonymize_answer(answer: str, mapping: dict) -> str:
    """LLMの回答に含まれる仮名ID("P001"等)を実名に置き換えて表示用に復元する。"""
    def replace(match):
        pseudo_id = match.group(0)
        return mapping.get(pseudo_id, pseudo_id)

    return re.sub(r"P\d{3}", replace, answer)


def _call_ollama(prompt: str) -> str:
    """Ollama の /api/generate を呼び出し、生成されたテキストを返す。"""
    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "system": SYSTEM_INSTRUCTION,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return (
            "[エラー] ローカルLLM(Ollama)に接続できませんでした。"
            "Ollamaが起動しているか確認してください(ollama serve)。"
        )
    except requests.exceptions.HTTPError as e:
        # 404の場合、モデル名が見つからないケースが多い。
        # Ollamaのレスポンス本文に理由が入っているので、そのまま表示する。
        try:
            detail = e.response.json().get("error", e.response.text)
        except Exception:
            detail = e.response.text if e.response is not None else str(e)
        return (
            f"[エラー] Ollamaからエラーが返されました: {detail}\n\n"
            f"現在指定しているモデル名は '{OLLAMA_MODEL}' です。"
            "ターミナルで `ollama list` を実行し、実際にpull済みのモデル名と一致しているか確認してください。"
            "一致しない場合は環境変数 OLLAMA_MODEL に正しいモデル名を設定してください。"
        )
    except requests.exceptions.Timeout:
        return "[エラー] LLMの応答がタイムアウトしました。"
    except Exception as e:
        return f"[エラー] 予期しない問題が発生しました: {e}"


def ask(question: str, asked_by: int) -> str:
    """
    自然言語の質問を受け取り、仮名化 → LLM問い合わせ → 実名復元 の流れで回答を返す。
    問い合わせ内容は audit_log に記録する。
    """
    context, mapping = _build_context_and_mapping()
    pseudonymized_question = _pseudonymize_question(question, mapping)

    prompt = (
        f"# データ\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"# 質問\n{pseudonymized_question}\n"
    )

    raw_answer = _call_ollama(prompt)
    final_answer = _depseudonymize_answer(raw_answer, mapping)

    conn = get_connection()
    log_action(conn, asked_by, "ai_query", detail=question)
    conn.close()

    return final_answer
