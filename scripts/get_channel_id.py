import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv(dotenv_path="secrets/.env")

API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE_URL = "https://www.googleapis.com/youtube/v3/channels"
ARTISTS_CSV_PATH = "config/artists.csv"

ARTISTS = [
    ("RPT MCK", "@hoanglongmck", 1),
    ("Hngle", "@HNGLE", 2),
    ("Dangrangto", "@Dangrangto", 3),
    ("Quốc Thiên", "@QUOCTHIENOFFICIAL", 4),
    ("GREY D", "@GreyDST319", 5),
    ("HIEUTHUHAI", "@HIEUTHUHAIOFFICIAL", 6),
    ("Obito", "@TobieeOfficial", 7),
    ("Sơn Tùng M-TP", "@Sontungmtp", 8),
    ("buitruonglinh", "@buitruonglinh", 9),
    ("W/N", "@Winhmm", 10),
]

NEEDS_RESOLVE = {"", "TODO", "KHONG_TIM_THAY"}


def fetch_channel_id(handle: str, api_key: str) -> dict | None:
    resp = requests.get(BASE_URL, params={
        "part": "snippet",
        "forHandle": handle,
        "key": api_key,
    })
    data = resp.json()

    if "items" not in data or len(data["items"]) == 0:
        return None

    return {
        "channel_id": data["items"][0]["id"],
        "channel_title": data["items"][0]["snippet"]["title"],
    }


def sync_artists_csv(csv_path: str, artists: list) -> pd.DataFrame:
    new_df = pd.DataFrame(artists, columns=["artist_name", "channel_handle", "rank"])
    if os.path.exists(csv_path):
        old_df = pd.read_csv(csv_path, dtype={"channel_id": str}, keep_default_na=False)
        old_ids = dict(zip(old_df["channel_handle"], old_df["channel_id"]))
    else:
        old_ids = {}

    new_df["channel_id"] = new_df["channel_handle"].map(old_ids).fillna("TODO")
    return new_df[["artist_name", "channel_handle", "channel_id", "rank"]]


def resolve_channel_ids(df: pd.DataFrame, api_key: str) -> pd.DataFrame:
    for idx, row in df.iterrows():
        name = row["artist_name"]
        handle = row["channel_handle"]
        current_id = str(row["channel_id"]).strip()

        if current_id not in NEEDS_RESOLVE:
            print(f"[BỎ QUA] {name} đã có channel_id ({current_id}) - không gọi lại API")
            continue

        result = fetch_channel_id(handle, api_key)

        if result is None:
            print(f"[LỖI] Không tìm thấy kênh cho {name} ({handle}) - kiểm tra lại handle thủ công")
            df.at[idx, "channel_id"] = "KHONG_TIM_THAY"
            continue

        print(f"[OK] {name} ({handle}) -> {result['channel_id']}  "
              f"| title thật trên YouTube: {result['channel_title']}")
        df.at[idx, "channel_id"] = result["channel_id"]

    return df


def save_csv(df: pd.DataFrame, csv_path: str) -> None:
    df.to_csv(csv_path, index=False)
    print(f"\nĐã lưu {len(df)} dòng vào {csv_path}")


def main():
    df = sync_artists_csv(ARTISTS_CSV_PATH, ARTISTS)
    df = resolve_channel_ids(df, API_KEY)
    save_csv(df, ARTISTS_CSV_PATH)


if __name__ == "__main__":
    main()