import os
import json
import random
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Environment Variables
CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")
GDRIVE_REMOTE = os.environ.get("GDRIVE_REMOTE")

DOWNLOAD_DIR = "./downloads"
PROCESSED_DIR = "./processed"
WATERMARK_IMAGE = "front.png"

# =========================================================
# আপনার ইউটিউব চ্যানেলের ডিফল্ট ডেসক্রিপশন এবং ট্যাগস এখানে বসান
# =========================================================
DEFAULT_DESCRIPTION = """ধন্যবাদ আমার ভিডিওটি দেখার জন্য!
ভিডিওটি ভালো লাগলে লাইক, কমেন্ট এবং সাবস্ক্রাইব করুন।

#viral #video #trending"""

DEFAULT_TAGS = ["viral", "trending", "bangla", "video"]
# =========================================================

def get_video_duration(video_path):
    """FFprobe ব্যবহার করে ভিডিওর মোট সময়কাল (সেকেন্ডে) নির্ণয় করা"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprintwrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def apply_watermark(input_path, watermark_path, output_path):
    """ভিডিওর প্রথম ৫ সেকেন্ড এবং শেষের ৫ সেকেন্ডে নিচের দিকে মিডেলে front.png ওয়াটারমার্ক বসানো"""
    if not os.path.exists(watermark_path):
        print(f"Warning: '{watermark_path}' পাওয়া যায়নি! মূল ভিডিওটিই আপলোড করা হবে।")
        return input_path

    try:
        duration = get_video_duration(input_path)
        print(f"Video duration: {duration:.2f} seconds")

        # ১০ সেকেন্ড বা ছোট ভিডিও হলে পুরো ভিডিওতে দেখাবে
        if duration <= 10:
            enable_expr = "between(t,0,10000)"
        else:
            start_last = max(0.0, duration - 5.0)
            enable_expr = f"between(t,0,5)+between(t,{start_last:.2f},{duration:.2f})"

        # x=(W-w)/2 : আনুভূমিকভাবে মাঝখানে (Middle)
        # y=H-h-20  : একদম নিচে ২০ পিক্সেল উপরে (Bottom)
        filter_complex = f"[0:v][1:v]overlay=x=(W-w)/2:y=H-h-20:enable='{enable_expr}'[outv]"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", watermark_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "0:a?",  # অডিও থাকলে রাখবে, না থাকলেও সমস্যা নেই
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "copy",
            output_path
        ]

        print("Adding 'front.png' overlay with FFmpeg...")
        subprocess.run(cmd, check=True)
        return output_path

    except Exception as e:
        print(f"Failed to apply watermark: {e}. Uploading original video.")
        return input_path

def setup_youtube_api():
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    return build("youtube", "v3", credentials=creds)

def load_titles():
    title_file = "Titles.txt" if os.path.exists("Titles.txt") else "Tittles.txt"
    if not os.path.exists(title_file):
        print("Warning: Titles file not found. Using default title.")
        return ["My Awesome Video"]

    with open(title_file, "r", encoding="utf-8") as f:
        titles = [line.strip() for line in f if line.strip()]
    return titles if titles else ["My Awesome Video"]

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    print("Checking Google Drive for new videos using Rclone...")
    try:
        subprocess.run(["rclone", "copy", GDRIVE_REMOTE, DOWNLOAD_DIR], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error copying files from Drive: {e}")
        return

    video_extensions = ('.mp4', '.mkv', '.mov', '.avi', '.flv', '.wmv')
    downloaded_files = os.listdir(DOWNLOAD_DIR)
    video_files = [f for f in downloaded_files if f.lower().endswith(video_extensions)]

    if not video_files:
        print("No new videos found in Google Drive.")
        return

    print(f"Found {len(video_files)} video(s) to process.")

    titles_list = load_titles()
    youtube = setup_youtube_api()

    for video in video_files:
        raw_video_path = os.path.join(DOWNLOAD_DIR, video)
        processed_video_path = os.path.join(PROCESSED_DIR, f"watermarked_{video}")

        # ১. ওয়াটারমার্ক ওভারলে প্রসেস করা
        final_video_path = apply_watermark(raw_video_path, WATERMARK_IMAGE, processed_video_path)

        # ২. টাইটেল নির্বাচন
        selected_title = random.choice(titles_list)
        if len(selected_title) > 100:
            selected_title = selected_title[:97] + "..."

        print(f"\nProcessing File: '{video}'")
        print(f"Assigned Title: '{selected_title}'")

        body = {
            "snippet": {
                "title": selected_title,
                "description": DEFAULT_DESCRIPTION,
                "tags": DEFAULT_TAGS,
                "categoryId": "22"  # 22 = People & Blogs
            },
            "status": {
                "privacyStatus": "public"  # ভিডিও সরাসরি পাবলীক হয়ে যাবে
            }
        }

        try:
            print("Uploading to YouTube...")
            media = MediaFileUpload(final_video_path, chunksize=-1, resumable=True)
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"Upload Progress: {int(status.progress() * 100)}%")

            video_id = response.get("id")
            print(f"Successfully Uploaded! Video Link: https://youtu.be/{video_id}")

            # ৩. সফল আপলোডের পর গুগল ড্রাইভ থেকে মূল ফাইল ডিলিট
            remote_file_path = f"{GDRIVE_REMOTE}/{video}"
            print(f"Deleting '{remote_file_path}' from Google Drive...")
            subprocess.run(["rclone", "deletefile", remote_file_path], check=True)
            print("Deleted successfully from Google Drive.")

            # ৪. লোকাল ফাইল ক্লিনআপ
            if os.path.exists(raw_video_path):
                os.remove(raw_video_path)
            if os.path.exists(processed_video_path):
                os.remove(processed_video_path)

        except Exception as err:
            print(f"Failed to process '{video}': {err}")

    print("\nAll tasks completed successfully!")

if __name__ == "__main__":
    main()