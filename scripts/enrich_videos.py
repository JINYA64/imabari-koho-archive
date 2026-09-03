#!/usr/bin/env python3
"""
data/videos.json の各動画に対して、Gemini APIで
- 政策分野タグ（固定リストから1つ）
- 1〜2文の要約
- 平易な言い換えタイトル
を生成し、data/videos_enriched.json に保存するスクリプト。

既にタグ付け済みの video_id はスキップするので、
2回目以降の実行は新しく追加された動画のみを処理する（APIクォータ節約）。

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
# 2026年9月時点、無料枠のレート制限が緩めな軽量モデル（分類・要約用途には十分）。
# gemini-2.5-flash-lite: 無料枠 15 RPM / 1,000 RPD
# 将来モデル名が変わった場合はここを更新する。
MODEL = "gemini-3.6-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
SOURCE_PATH = os.path.join(BASE_DIR, "data", "videos.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "data", "videos_enriched.json")

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

REQUEST_INTERVAL_SEC = 4.5  # 15 RPM制限(4秒間隔が下限)に対し、安全マージンを取った間隔
MAX_RETRIES = 5


def build_prompt(title, description):
    cat_list = "\n".join(f"- {c}" for c in CATEGORIES)
    # 説明文が長すぎる場合は先頭のみ使う（タイムスタンプ一覧やハッシュタグの羅列を避ける）
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


def call_gemini(prompt, retries=MAX_RETRIES):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        },
    }).encode("utf-8")

    req = Request(
        f"{API_URL}?key={API_KEY}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(retries):
        try:
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429:
                # Googleのエラー詳細に retryDelay が含まれていれば、それを優先的に使う
                wait = 20 * (attempt + 1)
                try:
                    err_json = json.loads(err_body)
                    details = err_json.get("error", {}).get("details", [])
                    for d in details:
                        if "retryDelay" in d:
                            delay_str = d["retryDelay"]  # 例: "43s"
                            wait = int(re.sub(r"[^0-9]", "", delay_str)) + 2
                except Exception:
                    pass
                print(f"  レート制限(429)。詳細: {err_body[:400]}", file=sys.stderr)
                print(f"  {wait}秒待機してリトライします...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code in (500, 503, 504):
                wait = 15 * (attempt + 1)
                print(f"  サーバー側混雑({e.code})。{wait}秒待機してリトライします...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [HTTPError] status={e.code} body={err_body[:300]}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(10)
                continue
            raise
        except URLError as e:
            print(f"  [URLError] {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(10)
                continue
            raise
    raise RuntimeError("リトライ上限に達しました")


def parse_response(text):
    # モデルが万一コードブロックで囲んだ場合に備えて除去
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

    if not to_process:
        print("新規処理対象はありません。終了します。")
        return

    processed_count = 0
    error_count = 0

    for i, video in enumerate(to_process, 1):
        vid = video["video_id"]
        title = video.get("title", "")
        print(f"[{i}/{len(to_process)}] {title[:40]}...")

        try:
            prompt = build_prompt(title, video.get("description", ""))
            raw = call_gemini(prompt)
            parsed = parse_response(raw)
            enriched_videos[vid] = parsed
            processed_count += 1
        except Exception as e:
            print(f"  エラー: {e}", file=sys.stderr)
            error_count += 1
            # 失敗した動画はスキップし、次回実行時に再試行される

        # 途中経過をこまめに保存（Actionsのタイムアウト等で中断しても進捗が残る）
        if i % 10 == 0 or i == len(to_process):
            enriched["videos"] = enriched_videos
            enriched["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(enriched, f, ensure_ascii=False, indent=2)

        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"完了: 成功{processed_count}本、失敗{error_count}本。")
    print(f"保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
