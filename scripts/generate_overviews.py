#!/usr/bin/env python3
"""
docs/data/videos_enriched.json をもとに、政策分野（category）ごとに
動画の要約をAIにまとめさせ、話題（トピック）単位の紹介文を生成するスクリプト。

出力: docs/data/category_overviews.json
  {
    "generated_at": "...",
    "categories": {
      "子育て・教育": {
        "topics": [
          {
            "topic_title": "保育料の無償化",
            "overview": "...(丁寧語の紹介文)...",
            "video_ids": ["xxxx", "yyyy", ...]
          },
          ...
        ]
      },
      ...
    }
  }

必要な環境変数:
  GEMINI_API_KEY

使い方:
  python scripts/generate_overviews.py
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

MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
VIDEOS_PATH = os.path.join(BASE_DIR, "docs", "data", "videos.json")
ENRICHED_PATH = os.path.join(BASE_DIR, "docs", "data", "videos_enriched.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "docs", "data", "category_overviews.json")

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

RETRIES_PER_MODEL = 3
REQUEST_INTERVAL_SEC = 3


def build_prompt(category, items):
    lines = "\n".join(
        f'- video_id: "{it["video_id"]}" / タイトル: {it["plain_title"]} / 内容: {it["summary"]}'
        for it in items
    )
    return f"""あなたは今治市（愛媛県）の広報担当者です。
以下は、政策分野「{category}」に分類された市政広報番組の一覧（タイトルと内容要約）です。
これらを読んで、実際にどのような取り組みが行われてきたかを、話題（トピック）ごとに整理して紹介文を作成してください。

出力はJSON形式のみとし、説明文やMarkdownのコードブロック記号は一切不要です。
以下の構造で出力してください:

{{
  "topics": [
    {{
      "topic_title": "トピックの見出し（10〜20文字程度、具体的で内容が一目でわかるもの）",
      "overview": "そのトピックについて今治市が行ってきた取り組みを、丁寧語（〜です、〜ます）で3〜5文程度にまとめた紹介文。文頭を毎回「今治市は」で始めず、取り組みの内容そのものから自然に書き始めること。読み手が概要をすぐ掴めるよう、平易でわかりやすい文章にすること。",
      "video_ids": ["関連する動画のvideo_idを配列で。下記リストに実在するIDのみを使うこと"]
    }}
  ]
}}

ルール:
- トピックは内容のまとまりに応じて2〜6個程度に分ける（無理に1つにまとめない）
- 1つの動画が複数のトピックに関連していてもよい
- video_idは必ず下記リストに実在するものだけを使うこと（存在しないIDを作らない）
- 該当する動画が極端に少ない話題は、無理にトピック化せず「その他の取り組み」のようにまとめてよい

対象動画一覧:
{lines}
"""


def try_model(model, prompt):
    url = f"{API_BASE}/{model}:generateContent"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
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
            with urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429:
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
    for model in MODELS:
        text = try_model(model, prompt)
        if text is not None:
            return text, model
        time.sleep(2)
    raise RuntimeError("全モデルでクォータ超過またはエラーのため取得できませんでした")


def parse_response(text, valid_ids):
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    result = json.loads(cleaned)
    topics = result.get("topics", [])

    cleaned_topics = []
    for t in topics:
        vids = [v for v in t.get("video_ids", []) if v in valid_ids]
        if not vids:
            continue
        cleaned_topics.append({
            "topic_title": t.get("topic_title", "").strip(),
            "overview": t.get("overview", "").strip(),
            "video_ids": vids,
        })
    return cleaned_topics


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def main():
    if not API_KEY:
        print("エラー: 環境変数 GEMINI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    videos_data = load_json(VIDEOS_PATH, None)
    enriched_data = load_json(ENRICHED_PATH, None)
    if videos_data is None or enriched_data is None:
        print("エラー: videos.json または videos_enriched.json が見つかりません。", file=sys.stderr)
        sys.exit(1)

    enriched_videos = enriched_data.get("videos", {})

    # カテゴリごとに動画をグループ化
    by_category = {c: [] for c in CATEGORIES}
    for v in videos_data.get("videos", []):
        e = enriched_videos.get(v["video_id"])
        if not e or not e.get("summary"):
            continue
        cat = e.get("category", "その他")
        if cat not in by_category:
            cat = "その他"
        by_category[cat].append({
            "video_id": v["video_id"],
            "plain_title": e.get("plain_title", v.get("title", "")),
            "summary": e["summary"],
        })

    output = {"categories": {}}

    for cat, items in by_category.items():
        if not items:
            continue
        print(f"分野「{cat}」({len(items)}本)を処理中...")
        valid_ids = {it["video_id"] for it in items}
        try:
            prompt = build_prompt(cat, items)
            raw, used_model = call_gemini(prompt)
            topics = parse_response(raw, valid_ids)
            output["categories"][cat] = {"topics": topics}
            print(f"  -> 成功（{used_model}）: トピック{len(topics)}件")
        except Exception as e:
            print(f"  エラー: {e}", file=sys.stderr)
            # 失敗した分野は前回分があれば維持したいが、無ければ空で継続
            continue

        time.sleep(REQUEST_INTERVAL_SEC)

    output["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"完了。保存先: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
