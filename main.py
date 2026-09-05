import argparse
import json
import logging
import os
from datetime import datetime, timezone
import pandas as pd
from dotenv import load_dotenv
from etl.utils import setup_logging
from etl.fetch import get_channel_details, get_all_video_ids, get_videos_detail, get_comments
from etl.transform import transform_channel_snapshot, transform_video, transform_comment
from etl.load import get_bigquery_client, load_processed_table, load_raw_responses

logger = logging.getLogger(__name__)

ARTISTS_CSV_PATH = "config/artists.csv"
COMMENT_MAX_PAGES = 5 


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raw_row(raw_item: dict, endpoint: str) -> dict:
    return {
        "payload": json.dumps(raw_item, ensure_ascii=False),
        "endpoint": endpoint,
        "fetched_at": _now_iso(),
    }


def process_channel(row: pd.Series, api_key: str) -> dict:
    artist_name = row["artist_name"]
    channel_id = row["channel_id"]

    logger.info("=== Bắt đầu xử lý kênh: %s (%s) ===", artist_name, channel_id)

    empty_result = {"channel_snapshot": [], "video": [], "comment": [], "raw": []}

    try:
        details = get_channel_details(channel_id, api_key)
        snapshot_row = transform_channel_snapshot(details)
        video_ids = get_all_video_ids(details["uploads_playlist_id"], api_key)
        raw_videos = get_videos_detail(video_ids, api_key)
    except Exception:
        logger.exception(
            "Bỏ qua kênh %s (%s) do lỗi khi lấy channel/video list - xem traceback phía trên",
            artist_name, channel_id,
        )
        return empty_result

    video_rows = []
    raw_rows = []
    for v in raw_videos:
        try:
            video_rows.append(transform_video(v, artist_name))
            raw_rows.append(_raw_row(v, "videos.list"))
        except Exception:
            logger.exception(
                "Bỏ qua video_id=%s của kênh %s do lỗi transform - xem traceback phía trên",
                v.get("id"), artist_name,
            )
            continue

    comment_rows = []
    for video_id in video_ids:
        try:
            raw_comments = get_comments(video_id, api_key, max_pages=COMMENT_MAX_PAGES)
        except Exception:
            logger.exception(
                "Bỏ qua comment của video_id=%s (kênh %s) do lỗi fetch - xem traceback phía trên",
                video_id, artist_name,
            )
            continue

        for c in raw_comments:
            try:
                comment_rows.append(transform_comment(c, artist_name, channel_id, video_id))
                raw_rows.append(_raw_row(c, "commentThreads.list"))
            except Exception:
                logger.exception(
                    "Bỏ qua 1 comment của video_id=%s (kênh %s) do lỗi transform",
                    video_id, artist_name,
                )
                continue

    logger.info(
        "Xong kênh %s: %d video, %d comment",
        artist_name, len(video_rows), len(comment_rows),
    )

    return {
        "channel_snapshot": [snapshot_row],
        "video": video_rows,
        "comment": comment_rows,
        "raw": raw_rows,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="=== CHẠY PIPELINE YOUTUBE ===")
    parser.add_argument(
        "--limit-channels", type=int, default=None,
        help="Chỉ xử lý N kênh đầu tiên trong artists.csv - dùng để test nhanh trước khi chạy full 10 kênh",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    setup_logging(args.log_level)
    load_dotenv(dotenv_path="secrets/.env")

    api_key = os.getenv("YOUTUBE_API_KEY")
    project_id = os.getenv("GCP_PROJECT_ID")
    raw_dataset = os.getenv("BQ_RAW_DATASET", "youtube_raw")
    processed_dataset = os.getenv("BQ_PROCESSED_DATASET", "youtube_processed")

    df = pd.read_csv(ARTISTS_CSV_PATH)
    if args.limit_channels:
        df = df.head(args.limit_channels)
        logger.info("Chạy giới hạn: %d kênh", args.limit_channels)

    all_snapshots, all_videos, all_comments, all_raw = [], [], [], []

    for _, row in df.iterrows():
        result = process_channel(row, api_key)
        all_snapshots.extend(result["channel_snapshot"])
        all_videos.extend(result["video"])
        all_comments.extend(result["comment"])
        all_raw.extend(result["raw"])

    logger.info(
        "Tổng kết sau khi xử lý %d kênh: %d snapshot, %d video, %d comment "
        "- bắt đầu ghi vào BigQuery",
        len(df), len(all_snapshots), len(all_videos), len(all_comments),
    )

    client = get_bigquery_client(project_id)

    load_processed_table(client, processed_dataset, "channel_snapshot", all_snapshots)
    load_processed_table(client, processed_dataset, "video", all_videos)
    load_processed_table(client, processed_dataset, "comment", all_comments)

    load_raw_responses(client, raw_dataset, all_raw)

    logger.info("=== PIPELINE CHẠY XONG ===")


if __name__ == "__main__":
    main()