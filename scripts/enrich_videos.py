#!/usr/bin/env python3
"""
data/videos.json の各動画に対して、Gemini APIで
- 政策分野タグ（固定リストから1つ）
- 1〜2文の要約
- 平易な言い換えタイトル
を生成し、data/videos_enriched.json に保存するスクリプト。

既にタグ付け済みの video_id はスキップするので、
2回目以降の実行は新しく追加された動画のみを処理する（APIクォータ節約）。

429（クォータ超過・レート制限）が出たモデルは即座にスキップし、
リストの次のモデルで再試行する「フォールバック方式」を採用。
無料枠は基本的にモデルごとに別枠なので、これで実質的な処理可能量を合算できる。

必要な環境変数:
  GEMINI_API_KEY  ... Google AI Studio で発行したAPIキー

使い方:
  python scripts/enrich_videos.py
"""

import json
import os
import re
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

API_KEY = os.environ.get("GEMINI_API_KEY")
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# 429が出たら上から順に次のモデルを試す（無料枠はモデルごとに別枠のため）。
# 2026年9月時点のラインナップ。将来モデル名が変わった場合はここを更新する。
MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
SOURCE_PATH = os.path.join(BASE_DIR, "docs", "data", "videos.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "docs", "data", "videos_enriched.json")

# 政策分野の固定タグリスト（フィルタUIの選択肢と一致させる）
CATEGORIES = [
    "子育て・教育",
    "防災・インフラ",
    "産業・経済",
    "観光・魅力発信",
    "まちづくり・地域振興",
    "医療・福祉",
    "スポーツ（FC今治等）",
    "文化・伝統",
    "環境・SDGs",
    "市政運営・行政サービス",
    "その他",
]

REQUEST_INTERVAL_SEC = 4.5  # 成功時、次のリクエストまでの待機（レート制限対策）
RETRIES_PER_MODEL = 3  # 1モデルあたりの503等リトライ回数（429は即座に次モデルへ）


def build_prompt(title, description):
    cat_list = "\n".join(f"- {c}" for c in CATEGORIES)
    trimmed_desc = description[:600]
    return f"""あなたは自治体広報番組のアーカイブ担当者です。
以下の今治市（愛媛県）市政広報番組の情報から、次の3つをJSON形式のみで出力してください。
説明や前置き、Markdownのコードブロック記号は一切不要です。JSONオブジェクトのみを返してください。

出力するJSONのキー:
- "category": 以下のリストから最も当てはまるものを1つだけ選ぶ
{cat_list}
- "summary": 番組内容を70〜100文字程度の日本語で要約する（一般市民にもわかる平易な言葉で）
- "plain_title": 元のタイトルから番組回数表記や過剰な装飾を除いた、15〜25文字程度の簡潔でわかりやすいタイトル

番組タイトル: {title}
番組説明文: {trimmed_desc}
"""


def try_model(model, prompt):
    """
    1つのモデルで生成を試みる。
    成功: 生成テキストを返す
    429（クォータ超過）: None を返す（呼び出し側が次のモデルへ進む）
    503等の一時エラー: リトライしても最終的に失敗すれば None を返す
    """
    url = f"{API_BASE}/{model}:generateContent"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    for attempt in range(RETRIES_PER_MODEL):
        req = Request(
            f"{url}?key={API_KEY}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429:
                # クォータ超過。このモデルは諦めて次のモデルへ（長時間待たない）
                reason = err_body[:200].replace("\n", " ")
                print(f"    [{model}] 429（クォータ超過）: {reason}", file=sys.stderr)
                return None
            if e.code in (500, 503, 504):
                wait = 15 * (attempt + 1)
                print(f"    [{model}] サーバー混雑({e.code})。{wait}秒待機してリトライします...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"    [{model}] エラー status={e.code} body={err_body[:300]}", file=sys.stderr)
            if attempt < RETRIES_PER_MODEL - 1:
                time.sleep(10)
                continue
            return None
        except URLError as e:
            print(f"    [{model}] URLError: {e}", file=sys.stderr)
            if attempt < RETRIES_PER_MODEL - 1:
                time.sleep(10)
                continue
            return None
    return None


def call_gemini(prompt):
    """MODELSを順に試し、成功したモデル名とテキストを返す。全滅なら例外を投げる。"""
    for model in MODELS:
        text = try_model(model, prompt)
        if text is not None:
            return text, model
        time.sleep(2)  # 次のモデルに切り替える前の小休止
    raise RuntimeError("全モデルでクォータ超過またはエラーのため取得できませんでした")


def parse_response(text):
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    result = json.loads(cleaned)

    category = result.get("category", "その他")
    if category not in CATEGORIES:
        category = "その他"

    return {
        "category": category,
        "summary": result.get("summary", "").strip(),
        "plain_title": result.get("plain_title", "").strip(),
    }


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def main():
    if not API_KEY:
        print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    source = load_json(SOURCE_PATH, None)
    if source is None:
        print(f"エラー: {SOURCE_PATH} が見つかりません。先に fetch_playlist.py を実行してください。", file=sys.stderr)
        sys.exit(1)

    enriched = load_json(OUTPUT_PATH, {"videos": {}})
    enriched_videos = enriched.get("videos", {})

    all_videos = source.get("videos", [])
    to_process = [v for v in all_videos if v["video_id"] not in enriched_videos]

    print(f"全{len(all_videos)}本中、未処理{len(to_process)}本を処理します。")
    print(f"使用モデル（優先順）: {', '.join(MODELS)}")

    if not to_process:
        print("新規処理対象はありません。終了します。")
        return

    processed_count = 0
    error_count = 0
    model_usage = {}

    for i, video in enumerate(to_process, 1):
        vid = video["video_id"]
        title = video.get("title", "")
        print(f"[{i}/{len(to_process)}] {title[:40]}...")

        try:
            prompt = build_prompt(title, video.get("description", ""))
            raw, used_model = call_gemini(prompt)
            parsed = parse_response(raw)
            parsed["_model_used"] = used_model
            enriched_videos[vid] = parsed
            processed_count += 1
            model_usage[used_model] = model_usage.get(used_model, 0) + 1
            print(f"    -> 成功（{used_model}）")
        except Exception as e:
            print(f"  エラー: {e}", file=sys.stderr)
            error_count += 1
            # 失敗した動画はスキップし、次回実行時に再試行される

        if i % 10 == 0 or i == len(to_process):
            enriched["videos"] = enriched_videos
            enriched["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(enriched, f, ensure_ascii=False, indent=2)

        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"完了: 成功{processed_count}本、失敗{error_count}本。")
    print(f"モデル別使用内訳: {model_usage}")
    print(f"保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
