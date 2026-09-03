#!/usr/bin/env python3
"""
今治市 市政広報番組プレイリストの全動画メタデータを取得し、
data/videos.json として保存するスクリプト。

必要な環境変数:
  YOUTUBE_API_KEY  ... YouTube Data API v3 のAPIキー

使い方:
  python scripts/fetch_playlist.py
"""

import json
import os
import sys
import time
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

PLAYLIST_ID = "PL1J9vE0-N62iFpbzd-6kJ3gJXg26YNxf1"
API_KEY = os.environ.get("YOUTUBE_API_KEY")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "videos.json")
API_BASE = "https://www.googleapis.com/youtube/v3/playlistItems"


def fetch_page(page_token=None, retries=3):
    params = {
        "part": "snippet,contentDetails",
        "playlistId": PLAYLIST_ID,
        "maxResults": 50,
        "key": API_KEY,
    }
    if page_token:
        params["pageToken"] = page_token

    url = f"{API_BASE}?{urlencode(params)}"

    for attempt in range(retries):
        try:
            with urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            print(f"[HTTPError] status={e.code} body={body[:500]}", file=sys.stderr)
            if e.code in (403, 429) and attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"リトライします... {wait}秒待機", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except URLError as e:
            print(f"[URLError] {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise


def normalize_item(item):
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    thumbnails = snippet.get("thumbnails", {})
    # 可能な限り高画質のサムネイルを選ぶ
    thumb = (
        thumbnails.get("maxres")
        or thumbnails.get("standard")
        or thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    )

    video_id = content_details.get("videoId") or snippet.get("resourceId", {}).get("videoId")

    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "published_at": content_details.get("videoPublishedAt") or snippet.get("publishedAt", ""),
        "thumbnail_url": thumb.get("url", ""),
        "video_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "position": snippet.get("position"),
    }


def main():
    if not API_KEY:
        print("エラー: 環境変数 YOUTUBE_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    all_items = []
    page_token = None
    page_count = 0

    while True:
        page_count += 1
        print(f"ページ {page_count} を取得中...")
        data = fetch_page(page_token)

        for item in data.get("items", []):
            # 削除済み・非公開動画はスキップ
            title = item.get("snippet", {}).get("title", "")
            if title in ("Private video", "Deleted video"):
                continue
            all_items.append(normalize_item(item))

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.5)  # API負荷軽減のための小休止

    # 公開日の新しい順に並べる
    all_items.sort(key=lambda v: v.get("published_at") or "", reverse=True)

    output = {
        "playlist_id": PLAYLIST_ID,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_count": len(all_items),
        "videos": all_items,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"完了: {len(all_items)}本のメタデータを {OUTPUT_PATH} に保存しました。")


if __name__ == "__main__":
    main()
