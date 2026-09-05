import argparse
import logging
import os

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def get_bigquery_client(project_id: str) -> bigquery.Client:
    return bigquery.Client(project=project_id)


def load_processed_table(client: bigquery.Client, dataset: str, table: str, rows: list) -> None:
    if not rows:
        logger.warning("Không có dòng nào để load vào %s.%s - bỏ qua, GIỮ NGUYÊN bảng cũ", dataset, table)
        return

    table_ref = f"{client.project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    try:
        job = client.load_table_from_json(rows, table_ref, job_config=job_config)
        job.result()  # đợi job chạy xong - raise lỗi ngay nếu job thất bại (vd sai schema)
    except Exception:
        logger.exception("Load thất bại vào %s", table_ref)
        raise

    logger.info("Đã ghi đè %d dòng vào %s (WRITE_TRUNCATE)", len(rows), table_ref)


def load_raw_responses(client: bigquery.Client, dataset: str, rows: list) -> None:
    if not rows:
        logger.warning("Không có raw response nào để load - bỏ qua")
        return

    table_ref = f"{client.project}.{dataset}.raw_responses"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    try:
        job = client.load_table_from_json(rows, table_ref, job_config=job_config)
        job.result()
    except Exception:
        logger.exception("Load raw thất bại vào %s", table_ref)
        raise

    logger.info("Đã nối thêm %d dòng raw vào %s (WRITE_APPEND)", len(rows), table_ref)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-test cho etl/load.py")
    parser.add_argument(
        "--live", action="store_true",
        help="THẬT SỰ ghi vào BigQuery (mặc định chỉ dry-run, không ghi gì cả)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


if __name__ == "__main__":
    from dotenv import load_dotenv

    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    load_dotenv(dotenv_path="secrets/.env")
    project_id = os.getenv("GCP_PROJECT_ID")
    processed_dataset = os.getenv("BQ_PROCESSED_DATASET", "youtube_processed")

    test_rows = [{
        "channel_id": "TEST_CHANNEL_ID",
        "channel_title": "Test Channel",
        "subscriber_count": 1,
        "view_count_total": 1,
        "video_count_total": 1,
        "snapshot_date": "2026-01-01",
        "extracted_at": "2026-01-01T00:00:00+00:00",
    }]

    if not args.live:
        logger.info(
            "[DRY-RUN] Sẽ ghi đè %s.channel_snapshot bằng %d dòng test - "
            "KHÔNG thật sự ghi (thêm --live để ghi thật)",
            processed_dataset, len(test_rows),
        )
    else:
        logger.warning(
            "[LIVE] Sắp GHI ĐÈ THẬT bảng channel_snapshot bằng 1 dòng test "
            "- dữ liệu thật đang có sẽ bị XOÁ, chỉ dùng khi chắc chắn!"
        )
        client = get_bigquery_client(project_id)
        load_processed_table(client, processed_dataset, "channel_snapshot", test_rows)