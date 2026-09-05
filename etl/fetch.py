import argparse
import logging
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/youtube/v3"


def _call_api(endpoint: str, params: dict, max_retries: int = 5) -> dict:
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            logger.warning(
                "Lỗi network khi gọi %s: %s - chờ %ss rồi thử lại (lần %d/%d)",
                endpoint, e, wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.json()

        try:
            error_body = resp.json()
        except ValueError:
            error_body = {}

        reason = error_body.get("error", {}).get("errors", [{}])[0].get("reason", "")

        RETRYABLE_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}

        if resp.status_code == 429 or (resp.status_code == 403 and reason in RETRYABLE_REASONS):
            wait = 2 ** attempt
            logger.warning(
                "HTTP %d (%s) khi gọi %s - chờ %ss rồi thử lại (lần %d/%d)",
                resp.status_code, reason, endpoint, wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            continue

        # Lỗi vĩnh viễn (commentsDisabled, forbidden, 400, 404...)
        logger.error("HTTP %d (%s) khi gọi %s - không retry, trả lỗi luôn", resp.status_code, reason, endpoint)
        return error_body

    logger.error("Gọi %s thất bại sau %d lần thử", endpoint, max_retries)
    raise RuntimeError(f"Gọi {endpoint} thất bại sau {max_retries} lần thử")


def get_channel_details(channel_id: str, api_key: str) -> dict:
    try:
        data = _call_api("channels", {
            "part": "snippet,statistics,contentDetails",
            "id": channel_id,
            "key": api_key,
        })
    except RuntimeError:
        logger.error("Không thể lấy channel details cho channel_id=%s", channel_id)
        raise

    if "items" not in data or len(data["items"]) == 0:
        logger.error("Không tìm thấy channel_id: %s", channel_id)
        raise ValueError(f"Không tìm thấy channel_id: {channel_id}")

    item = data["items"][0]
    stats = item.get("statistics", {})

    return {
        "channel_id": item["id"],
        "channel_title": item["snippet"]["title"],
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
        "subscriber_count": stats.get("subscriberCount"),
        "view_count_total": stats.get("viewCount"),
        "video_count_total": stats.get("videoCount"),
    }


def get_all_video_ids(playlist_id: str, api_key: str) -> list:
    video_ids = []
    page_token = None

    while True:
        params = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _call_api("playlistItems", params)
        except RuntimeError:
            logger.error("Không thể lấy playlistItems cho playlist_id=%s", playlist_id)
            raise

        for item in data.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    logger.info("Lấy được %d video_id từ playlist %s", len(video_ids), playlist_id)
    return video_ids


def get_videos_detail(video_ids: list, api_key: str) -> list:
    all_items = []

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        try:
            data = _call_api("videos", {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(batch),
                "key": api_key,
            })
        except RuntimeError:
            logger.error("Không thể lấy videos.list cho batch bắt đầu tại index %d", i)
            raise
        all_items.extend(data.get("items", []))

    return all_items


def get_comments(video_id: str, api_key: str, max_pages: int = 5) -> list:
    comments = []
    page_token = None
    page_count = 0

    while page_count < max_pages:
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": 100,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _call_api("commentThreads", params)
        except RuntimeError:
            logger.error("Không thể lấy comment cho video_id=%s", video_id)
            raise

        if "error" in data:
            reason = data["error"].get("errors", [{}])[0].get("reason", "")
            if reason == "commentsDisabled":
                logger.info("Video %s đã tắt comment, bỏ qua", video_id)
                return []
            logger.error("Lỗi commentThreads cho video %s: %s", video_id, data["error"])
            raise RuntimeError(f"Lỗi khi gọi commentThreads cho video {video_id}: {data['error']}")

        comments.extend(data.get("items", []))

        page_token = data.get("nextPageToken")
        page_count += 1
        if not page_token:
            break

    return comments

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-test cho etl/fetch.py - test 4 hàm gọi API bằng 1 kênh mẫu."
    )
    parser.add_argument(
        "--channel-id",
        default=None,
        help="channel_id cụ thể muốn test (mặc định: dòng đầu tiên trong artists.csv)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Số trang comment muốn test (mặc định 1 để test nhanh; pipeline chính thức dùng 5)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Mức độ log hiển thị (mặc định INFO)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import os
    import pandas as pd
    from dotenv import load_dotenv

    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv(dotenv_path="secrets/.env") 
    api_key = os.getenv("YOUTUBE_API_KEY")

    if args.channel_id:
        test_channel_id = args.channel_id
        test_artist_name = "(chỉ định qua --channel-id)"
    else:
        df = pd.read_csv("config/artists.csv")
        sample = df.iloc[0]
        test_channel_id = sample["channel_id"]
        test_artist_name = sample["artist_name"]

    logger.info("=== Test với kênh mẫu: %s (%s) ===", test_artist_name, test_channel_id)

    try:
        details = get_channel_details(test_channel_id, api_key)
        logger.info("get_channel_details: %s", details)

        video_ids = get_all_video_ids(details["uploads_playlist_id"], api_key)
        logger.info("get_all_video_ids: tìm thấy %d video", len(video_ids))

        videos = get_videos_detail(video_ids[:5], api_key)
        logger.info("get_videos_detail: lấy chi tiết %d video", len(videos))

        comments = get_comments(video_ids[0], api_key, max_pages=args.max_pages)
        logger.info("get_comments: lấy được %d comment", len(comments))

    except Exception:
        logger.exception("Self-test thất bại")