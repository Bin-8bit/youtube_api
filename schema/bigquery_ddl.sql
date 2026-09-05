
-- DATASET: youtube_processed

-- Bảng video: mỗi dòng là 1 video của 1 nghệ sĩ
CREATE TABLE IF NOT EXISTS `youtube-api-pipeline-507116.youtube_processed.video` (
  artist_name     STRING,
  channel_id      STRING,
  channel_title   STRING,
  video_id        STRING,
  video_title     STRING,
  description     STRING,
  published_at    TIMESTAMP,
  duration_seconds INT64,
  tags            ARRAY<STRING>,
  category_id     STRING,
  view_count      INT64,
  like_count      INT64,
  comment_count   INT64,
  extracted_at    TIMESTAMP,
  source          STRING,
  ingestion_date  DATE
);

-- Bảng comment: mỗi dòng là 1 comment, liên kết ngược về video qua video_id
CREATE TABLE IF NOT EXISTS `youtube-api-pipeline-507116.youtube_processed.comment` (
  artist_name    STRING,
  channel_id     STRING,
  video_id       STRING,
  comment_id     STRING,
  parent_id      STRING,
  author_name    STRING,
  comment_text   STRING,
  published_at   TIMESTAMP,
  updated_at     TIMESTAMP,
  like_count     INT64,
  reply_count    INT64,
  extracted_at   TIMESTAMP,
  ingestion_date DATE
);

-- Bảng channel_snapshot: mỗi lần cron chạy ghi thêm 1 dòng cho mỗi kênh
CREATE TABLE IF NOT EXISTS `youtube-api-pipeline-507116.youtube_processed.channel_snapshot` (
  channel_id        STRING,
  channel_title     STRING,
  subscriber_count  INT64,
  view_count_total  INT64,
  video_count_total INT64,
  snapshot_date     DATE,
  extracted_at      TIMESTAMP
);

-- DATASET: youtube_raw

-- Bảng raw dùng chung cho mọi endpoint (channels.list, videos.list, playlistItems.list, commentThreads.list...)
CREATE TABLE IF NOT EXISTS `youtube-api-pipeline-507116.youtube_raw.raw_responses` (
  payload    STRING,
  endpoint   STRING,   
  fetched_at TIMESTAMP
);