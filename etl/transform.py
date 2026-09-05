import argparse
import logging
import re
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

SOURCE_NAME = "youtube_data_api_v3"

_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)


def parse_duration_to_seconds(duration: str) -> int | None:
    match = _DURATION_RE.match(duration or "")
    if not match:
        logger.error("Không parse được duration: %r", duration)
        raise ValueError(f"Không parse được duration: {duration!r}")

    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)

    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    
    if total == 0:
        logger.info("Duration = 0 (%r) - có thể là livestream/premiere chưa xác định thời lượng", duration)
        return None

    return total


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Không ép được kiểu int cho giá trị: %r", value)
        return None


def _now_extracted_at() -> str:
    """Timestamp hiện tại (UTC), dùng chung cho mọi bảng ở field extracted_at."""
    return datetime.now(timezone.utc).isoformat()


def _today_ingestion_date() -> str:
    """Ngày hiện tại (UTC), dùng cho field ingestion_date (kiểu DATE)."""
    return date.today().isoformat()


def transform_video(raw_video_item: dict, artist_name: str) -> dict:
    try:
        snippet = raw_video_item["snippet"]
        content_details = raw_video_item["contentDetails"]
        stats = raw_video_item.get("statistics", {})

        return {
            "artist_name": artist_name,
            "channel_id": snippet["channelId"],
            "channel_title": snippet["channelTitle"],
            "video_id": raw_video_item["id"],
            "video_title": snippet["title"],
            "description": snippet.get("description"),
            "published_at": snippet["publishedAt"],
            "duration_seconds": parse_duration_to_seconds(content_details["duration"]),
            "tags": snippet.get("tags", []),
            "category_id": snippet.get("categoryId"),
            "view_count": _to_int(stats.get("viewCount")),
            "like_count": _to_int(stats.get("likeCount")),      
            "comment_count": _to_int(stats.get("commentCount")),
            "extracted_at": _now_extracted_at(),
            "source": SOURCE_NAME,
            "ingestion_date": _today_ingestion_date(),
        }
    except KeyError as e:
        logger.error("Thiếu field %s khi transform video_id=%s", e, raw_video_item.get("id"))
        raise


def transform_comment(raw_thread_item: dict, artist_name: str, channel_id: str, video_id: str) -> dict:
    try:
        top_comment = raw_thread_item["snippet"]["topLevelComment"]
        comment_snippet = top_comment["snippet"]

        return {
            "artist_name": artist_name,
            "channel_id": channel_id,
            "video_id": video_id,
            "comment_id": top_comment["id"],
            "parent_id": None,
            "author_name": comment_snippet.get("authorDisplayName"),
            "comment_text": comment_snippet.get("textDisplay"),
            "published_at": comment_snippet["publishedAt"],
            "updated_at": comment_snippet.get("updatedAt"),
            "like_count": _to_int(comment_snippet.get("likeCount")),
            "reply_count": _to_int(raw_thread_item["snippet"].get("totalReplyCount")),
            "extracted_at": _now_extracted_at(),
            "ingestion_date": _today_ingestion_date(),
        }
    except KeyError as e:
        logger.error("Thiếu field %s khi transform comment của video_id=%s", e, video_id)
        raise


def transform_channel_snapshot(channel_details: dict) -> dict:
    try:
        return {
            "channel_id": channel_details["channel_id"],
            "channel_title": channel_details["channel_title"],
            "subscriber_count": _to_int(channel_details.get("subscriber_count")),
            "view_count_total": _to_int(channel_details.get("view_count_total")),
            "video_count_total": _to_int(channel_details.get("video_count_total")),
            "snapshot_date": _today_ingestion_date(),
            "extracted_at": _now_extracted_at(),
        }
    except KeyError as e:
        logger.error("Thiếu field %s khi transform channel_snapshot", e)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-test cho etl/transform.py - fetch dữ liệu thật rồi transform thử."
    )
    parser.add_argument(
        "--channel-id",
        default=None,
        help="channel_id cụ thể muốn test (mặc định: dòng đầu tiên trong config/artists.csv)",
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
    from fetch import get_channel_details, get_all_video_ids, get_videos_detail, get_comments

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

    logger.info("=== Test transform với kênh mẫu: %s (%s) ===", test_artist_name, test_channel_id)

    try:
        details = get_channel_details(test_channel_id, api_key)
        snapshot_row = transform_channel_snapshot(details)
        logger.info("transform_channel_snapshot: %s", snapshot_row)

        video_ids = get_all_video_ids(details["uploads_playlist_id"], api_key)
        videos = get_videos_detail(video_ids[:3], api_key)
        video_rows = [transform_video(v, test_artist_name) for v in videos]
        logger.info("transform_video: đã transform %d video, ví dụ dòng đầu: %s",
                    len(video_rows), video_rows[0])

        comments = get_comments(video_ids[0], api_key, max_pages=1)
        if comments:
            comment_row = transform_comment(comments[0], test_artist_name, test_channel_id, video_ids[0])
            logger.info("transform_comment: %s", comment_row)
        else:
            logger.info("Video đầu tiên không có comment để test transform_comment")

    except Exception:
        logger.exception("Self-test transform thất bại")