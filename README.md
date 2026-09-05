# YouTube Data Pipeline

Pipeline thu thập dữ liệu video/comment/thống kê kênh của 10 nghệ sĩ hàng đầu
Việt Nam từ YouTube Data API v3, lưu vào BigQuery, chạy tự động 2 lần/ngày
qua cron trên Google Cloud VM.

## Danh sách nghệ sĩ & tiêu chí "top 10"

Nguồn tham khảo: **YouTube Charts VN — Weekly Top Artists (theo views)**
https://charts.youtube.com/charts/TopArtists/vn/weekly
Tuần: 31/07/2026 – 06/08/2026. Truy cập ngày: 27/08/2026.

Danh sách đầy đủ (rank, nghệ sĩ, channel_id) nằm trong `config/artists.csv`.

Ghi chú xử lý 2 trường hợp đặc biệt trong bảng xếp hạng gốc:
- DONAL và Dangrangto hợp tác chung trên 1 bài hát trong bảng xếp hạng →
  Dangrangto được chọn làm đại diện; buitruonglinh (top 11 gốc) lên thay
  vị trí của DONAL.
- "Anh Trai Vượt Ngàn Chông Gai" là 1 chương trình truyền hình (không phải
  nghệ sĩ cá nhân) nên bị loại khỏi bảng xếp hạng; W/N (top 12 gốc) lên
  thay vị trí đó.

## Kiến trúc pipeline

```
YouTube Data API v3
    │
    ▼
etl/fetch.py       (gọi API: channels, playlistItems, videos, commentThreads)
    │
    ▼
etl/transform.py   (parse duration, chuẩn hoá timestamp, ép kiểu, map schema)
    │
    ▼
etl/load.py        (ghi vào BigQuery)
    │
    ├──► dataset youtube_raw       (bảng raw_responses — WRITE_APPEND, giữ lịch sử)
    └──► dataset youtube_processed (bảng video/comment/channel_snapshot — WRITE_TRUNCATE, full load)
```

`main.py` điều phối toàn bộ luồng trên cho từng kênh trong `config/artists.csv`,
gom dữ liệu của **tất cả** kênh trước khi ghi đè (xem mục Chiến lược load bên dưới).

## Cấu trúc thư mục

```
youtube_data_pipeline/
├── config/
│   └── artists.csv          # danh sách 10 nghệ sĩ + channel_id + rank
├── data/
│   ├── raw/                 # (rỗng, chỉ giữ .gitkeep — không commit data thật)
│   └── processed/           # (rỗng, chỉ giữ .gitkeep)
├── etl/
│   ├── __init__.py
│   ├── fetch.py             # gọi YouTube Data API v3, có retry/backoff
│   ├── transform.py         # chuẩn hoá dữ liệu theo schema
│   ├── load.py              # ghi vào BigQuery
│   └── utils.py             # cấu hình logging dùng chung
├── logs/                     # log runtime (.gitkeep, không commit log thật)
├── schema/
│   └── bigquery_ddl.sql     # DDL tạo 4 bảng BigQuery
├── scripts/
│   └── get_channel_id.py    # công cụ hỗ trợ 1 lần (Ngày 2) — KHÔNG thuộc pipeline chính
├── secrets/                  # KHÔNG commit — .env, service_account.json
├── .gitignore
├── main.py                   # entry point, chạy bởi cron
├── requirements.txt
└── README.md
```

> **Lưu ý bảo mật**: `secrets/` chứa API key và service account credential thật,
> đã được loại trừ hoàn toàn khỏi Git qua `.gitignore`. `config/` chỉ chứa dữ liệu
> xác định phạm vi pipeline (danh sách nghệ sĩ), không chứa thông tin xác thực.

## Cài đặt

```bash
git clone <repo-url>
cd youtube_data_pipeline
python3 -m venv venv           # tuỳ chọn - có thể dùng conda hoặc bỏ qua
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Cấu hình

Tạo thư mục `secrets/` và file `secrets/.env` với nội dung sau, điền giá trị thật vào:

```
YOUTUBE_API_KEY=<API key YouTube Data API v3, đã Restrict theo API>
GOOGLE_APPLICATION_CREDENTIALS=secrets/service_account.json
GCP_PROJECT_ID=<Project ID trên Google Cloud, không phải Project Name>
BQ_RAW_DATASET=youtube_raw
BQ_PROCESSED_DATASET=youtube_processed
```

Đặt file Service Account JSON key thật vào `secrets/service_account.json`.

## Schema BigQuery

Chạy `schema/bigquery_ddl.sql` trên BigQuery Console (sau khi đã tạo 2 dataset
`youtube_raw` và `youtube_processed` cùng 1 location) để tạo 4 bảng:

| Bảng | Dataset | Ghi chú |
|---|---|---|
| `video` | youtube_processed | Mỗi dòng = 1 video. Field chính: `video_id`, `duration_seconds`, `tags` (ARRAY), `view_count`, `like_count`, `comment_count` |
| `comment` | youtube_processed | Mỗi dòng = 1 comment top-level, liên kết `video_id`. Giới hạn `max_pages=5`/video (xem Chiến lược lấy comment) |
| `channel_snapshot` | youtube_processed | Mỗi lần cron chạy ghi 1 dòng/kênh — dùng để chứng minh growth theo ngày |
| `raw_responses` | youtube_raw | Payload JSON gốc của mọi lần gọi API, cột `endpoint` phân biệt nguồn |

## Chạy local

Test nhanh với 1 kênh trước khi chạy full:
```bash
python main.py --limit-channels 1
```

Chạy full 10 kênh (mất khoảng 60-90 phút tuỳ lượng comment):
```bash
python main.py
```

Tham số CLI: `--limit-channels N` (giới hạn N kênh đầu), `--log-level` (DEBUG/INFO/WARNING/ERROR).

Test độc lập từng module (không chạy full pipeline):
```bash
python etl/fetch.py --channel-id <UC...> --max-pages 1
python etl/transform.py --channel-id <UC...>
python etl/load.py --live   # CẨN THẬN: ghi thật 1 dòng test, ghi đè channel_snapshot
```

## Chạy trên VM (Google Cloud Compute Engine)

```bash
git clone <repo-url>
cd youtube_data_pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Đưa `secrets/.env` và `secrets/service_account.json` lên VM **không qua Git**:
```bash
gcloud compute scp secrets/.env <instance-name>:~/youtube_data_pipeline/secrets/
gcloud compute scp secrets/service_account.json <instance-name>:~/youtube_data_pipeline/secrets/
```

Chạy thử thủ công để xác nhận hoạt động đúng như local:
```bash
python main.py --limit-channels 1
```

## Lịch chạy (cron)

VM chạy Ubuntu, cần đổi timezone trước khi setup cron:
```bash
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
```

Crontab (`crontab -e`), dùng đường dẫn tuyệt đối cho python trong venv:
```
0 7 * * *  cd /home/user/youtube_data_pipeline && /home/user/youtube_data_pipeline/venv/bin/python main.py >> logs/cron.log 2>&1
0 23 * * * cd /home/user/youtube_data_pipeline && /home/user/youtube_data_pipeline/venv/bin/python main.py >> logs/cron.log 2>&1
```

## Chiến lược load: FULL LOAD

Mỗi lần chạy, pipeline **ghi đè toàn bộ** 3 bảng processed (`WRITE_TRUNCATE`)
bằng dữ liệu mới nhất — không dùng incremental load. `main.py` fetch +
transform xong **cả 10 kênh** rồi mới ghi đè **đúng 1 lần** cho mỗi bảng,
tránh việc ghi đè giữa chừng làm mất dữ liệu của các kênh đã xử lý trước đó.

Batch load job (`load_table_from_json`) được dùng thay vì streaming insert
(`insert_rows_json`), vì `write_disposition="WRITE_TRUNCATE"` chỉ có tác
dụng với batch load job.

## Chiến lược lấy comment

Giới hạn cứng `max_pages=5`/video (áp dụng từ đầu, không đợi lỗi quota) —
vì 10 nghệ sĩ top VN có lượng comment rất lớn, lấy toàn bộ sẽ tốn quota
không cần thiết cho mục đích chứng minh pipeline hoạt động đúng.

## Xử lý lỗi & retry

**Ở tầng gọi API (`etl/fetch.py`)** — retry với exponential backoff (tối đa 5
lần), nhưng **chỉ retry với lỗi tạm thời**:
- HTTP 429, hoặc HTTP 403 có `reason` thuộc `quotaExceeded`,
  `rateLimitExceeded`, `userRateLimitExceeded` → chờ rồi thử lại
- Lỗi vĩnh viễn (`commentsDisabled`, `forbidden`, HTTP 400/404...) → **không**
  retry, trả lỗi ngay — retry không giải quyết được gì với loại lỗi này, chỉ
  tổ tốn thời gian chờ vô ích

**Ở tầng điều phối (`main.py`)** — bắt lỗi ở nhiều cấp độ riêng biệt, lỗi nhỏ
không kéo theo mất dữ liệu lớn:
- Lỗi khi lấy `channel_details`/danh sách video của 1 kênh → bỏ qua **cả
  kênh đó**, các kênh còn lại vẫn chạy tiếp
- Lỗi transform 1 video cụ thể → chỉ bỏ qua **video đó**, các video khác của
  cùng kênh vẫn được xử lý bình thường
- Lỗi khi lấy comment cho 1 video → chỉ bỏ qua **comment của video đó**,
  video vẫn được lưu vào bảng `video`, các video khác vẫn lấy comment bình thường
- Lỗi transform 1 comment cụ thể → chỉ bỏ qua **đúng comment đó**

Video tắt comment (`commentsDisabled`) được coi là trường hợp hợp lệ (không
phải lỗi) — trả về danh sách comment rỗng, không log ở mức ERROR.

**Video dạng livestream/premiere** (`duration` không có phần `PT...`, ví dụ
`P0D`) → `duration_seconds` được gán `None` thay vì raise lỗi, vì đây là
giá trị hợp lệ theo YouTube (chưa xác định thời lượng cố định), không phải
dữ liệu sai. Chỉ khi chuỗi `duration` hoàn toàn không đúng định dạng ISO 8601
(không parse được bằng regex) thì mới raise `ValueError` thật sự.

## Công cụ hỗ trợ (không thuộc pipeline chính thức)

`scripts/get_channel_id.py` — dùng 1 lần ở Ngày 2 để tra `channel_id` thật
từ `@handle`, cập nhật vào `config/artists.csv`. Không được cron gọi tới.