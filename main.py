import os
import json
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Environment Variables
CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
GDRIVE_REMOTE = os.environ.get("GDRIVE_REMOTE", "").strip()

DOWNLOAD_DIR = "./downloads"
PROCESSED_DIR = "./processed"
WATERMARK_IMAGE = "front.png"
INDEX_FILE_NAME = "title_index.txt"

# =========================================================
# আপনার ইউটিউব চ্যানেলের ডিফল্ট ডেসক্রিপশন এবং ট্যাগস
# =========================================================
DEFAULT_DESCRIPTION = """ধন্যবাদ আমার ভিডিওটি দেখার জন্য!
ভিডিওটি ভালো লাগলে লাইক, কমেন্ট এবং সাবস্ক্রাইব করুন।

#viral #video #trending"""

DEFAULT_TAGS = ["viral", "trending", "bangla", "video"]
# =========================================================

def get_remote_path(remote_target, filename):
    """rclone এর জন্য সঠিক পাথ তৈরি করে (যেমন: remote:file বা remote/file)"""
    remote_target = remote_target.rstrip('/')
    if remote_target.endswith(':'):
        return f"{remote_target}{filename}"
    return f"{remote_target}/{filename}"

def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprintwrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def apply_watermark(input_path, watermark_path, output_path):
    if not os.path.exists(watermark_path):
        print(f"Warning: '{watermark_path}' পাওয়া যায়নি! মূল ভিডিওটিই আপলোড করা হবে।")
        return input_path

    try:
        duration = get_video_duration(input_path)
        print(f"Video duration: {duration:.2f} seconds")

        if duration <= 10:
            enable_expr = "between(t,0,10000)"
        else:
            start_last = max(0.0, duration - 5.0)
            enable_expr = f"between(t,0,5)+between(t,{start_last:.2f},{duration:.2f})"

        filter_complex = f"[0:v][1:v]overlay=x=(W-w)/2:y=H-h-20:enable='{enable_expr}'[outv]"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", watermark_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "0:a?",
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

def get_title_index():
    local_index_path = os.path.join(DOWNLOAD_DIR, INDEX_FILE_NAME)
    if os.path.exists(local_index_path):
        try:
            with open(local_index_path, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0

def save_title_index(index, remote_target, flags):
    local_index_path = os.path.join(DOWNLOAD_DIR, INDEX_FILE_NAME)
    with open(local_index_path, "w", encoding="utf-8") as f:
        f.write(str(index))
    
    try:
        remote_index_path = get_remote_path(remote_target, INDEX_FILE_NAME)
        cmd = ["rclone", "copyto"] + flags + [local_index_path, remote_index_path]
        subprocess.run(cmd, check=True)
        print(f"Updated next title position ({index + 1}) to Google Drive.")
    except Exception as e:
        print(f"Failed to save title index to Google Drive: {e}")

def get_candidate_remotes(gdrive_remote):
    raw = gdrive_remote.strip()
    candidates = []
    
    # ১. ফোল্ডার নাম বা পাথ বা আইডি
    if raw and ":" not in raw and "/" not in raw and len(raw) > 20 and " " not in raw:
        candidates.append(f"gdrive,root_folder_id={raw}:")
    elif raw and ":" in raw:
        candidates.append(raw)
    elif raw:
        candidates.append(f"gdrive:{raw}")
    
    # ২. ফোল্ডার আইডি রিমোট (আপনার ফোল্ডারের সরাসরি আইডি)
    folder_id_target = "gdrive,root_folder_id=1KX4cfmalyTyXw08NRqkOLYEPQd_6GYn4:"
    if folder_id_target not in candidates:
        candidates.append(folder_id_target)

    # ৩. ফোল্ডার নাম রিমোট (মাই ড্রাইভ শর্টকাট)
    shared_name_target = "gdrive:3MinHell"
    if shared_name_target not in candidates:
        candidates.append(shared_name_target)

    return candidates

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    candidates = get_candidate_remotes(GDRIVE_REMOTE)
    
    attempts = []
    for target in candidates:
        attempts.append({"target": target, "flags": []})
        attempts.append({"target": target, "flags": ["--drive-shared-with-me"]})

    print("\n=================== GOOGLE DRIVE TARGET SEARCH ===================")
    print("Searching My Drive Shortcuts & Shared Folders...")
    print("==================================================================\n")

    remote_target = None
    used_flags = []
    success = False

    for attempt in attempts:
        target = attempt["target"]
        flags = attempt["flags"]
        
        # ডাউনলোড ফোল্ডার পরিষ্কার করা
        for item in os.listdir(DOWNLOAD_DIR):
            item_path = os.path.join(DOWNLOAD_DIR, item)
            if os.path.isfile(item_path):
                os.remove(item_path)

        cmd = ["rclone", "copy"] + flags + [target, DOWNLOAD_DIR]
        print(f"Executing: {' '.join(cmd)}")
        
        res = subprocess.run(cmd, capture_output=True, text=True)
        downloaded = os.listdir(DOWNLOAD_DIR)
        
        video_files = [
            f for f in downloaded 
            if os.path.isfile(os.path.join(DOWNLOAD_DIR, f)) 
            and f != INDEX_FILE_NAME 
            and not f.startswith(".")
        ]

        # শুধু তখনই সফল হিসেবে ধরবে যখন অন্তত ১টি ভিডিও ফাইল পাওয়া যাবে
        if res.returncode == 0 and len(video_files) > 0:
            print(f"\nSUCCESS: Connected to '{target}' and found {len(video_files)} video file(s)!")
            remote_target = target
            used_flags = flags
            success = True
            break

    if not success or not remote_target:
        print("Error: Could not find any video files in Google Drive targets.")
        return

    downloaded_files = os.listdir(DOWNLOAD_DIR)
    print(f"\nAll downloaded items from Google Drive: {downloaded_files}")

    video_files = [
        f for f in downloaded_files 
        if os.path.isfile(os.path.join(DOWNLOAD_DIR, f)) 
        and f != INDEX_FILE_NAME 
        and not f.startswith(".")
    ]

    print(f"Found {len(video_files)} video(s) to process: {video_files}")

    titles_list = load_titles()
    current_index = get_title_index()
    youtube = setup_youtube_api()

    for video in video_files:
        raw_video_path = os.path.join(DOWNLOAD_DIR, video)
        processed_video_path = os.path.join(PROCESSED_DIR, f"watermarked_{video}.mp4")

        # ১. ওয়াটারমার্ক প্রসেস করা
        final_video_path = apply_watermark(raw_video_path, WATERMARK_IMAGE, processed_video_path)

        # ২. ক্রমানুসারে টাইটেল নেওয়া
        actual_index = current_index % len(titles_list)
        selected_title = titles_list[actual_index]

        if len(selected_title) > 100:
            selected_title = selected_title[:97] + "..."

        print(f"\nProcessing File: '{video}'")
        print(f"Assigned Title ({actual_index + 1}/{len(titles_list)}): '{selected_title}'")

        body = {
            "snippet": {
                "title": selected_title,
                "description": DEFAULT_DESCRIPTION,
                "tags": DEFAULT_TAGS,
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public"
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

            # ইউটিউব আপলোড সফল হলেই কেবল টাইটেল ইনডেক্স বাড়ানো হবে
            current_index += 1

            # ৩. ড্রাইভে থাকা মূল ভিডিও ডিলিট করা
            remote_file_path = get_remote_path(remote_target, video)
            print(f"Deleting '{remote_file_path}' from Google Drive...")
            cmd_delete = ["rclone", "deletefile"] + used_flags + [remote_file_path]
            subprocess.run(cmd_delete, check=True)
            print("Deleted successfully from Google Drive.")

            # ৪. লোকাল ফাইল ডিলিট করে পরিষ্কার করা
            if os.path.exists(raw_video_path):
                os.remove(raw_video_path)
            if os.path.exists(processed_video_path) and processed_video_path != raw_video_path:
                os.remove(processed_video_path)

        except Exception as err:
            print(f"Failed to process '{video}': {err}")

    # নতুন ইনডেক্স ড্রাইভে সেভ করা
    save_title_index(current_index % len(titles_list), remote_target, used_flags)
    print("\nAll tasks completed successfully!")

if __name__ == "__main__":
    main()
