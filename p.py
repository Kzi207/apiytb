import subprocess
import json
import os
import sys

AUTHOR = "khanhduy"
COOKIE_FILE = "cookies.txt"
OUTPUT_FILE = "output.json"


def run_ytdlp(video_url):
    command = [
        "yt-dlp",

        "--cookies",
        COOKIE_FILE,

        "--js-runtimes",
        "node",

        "--remote-components",
        "ejs:github",

        "--extractor-args",
        "youtube:player_client=default,web_embedded",

        "--dump-single-json",

        "--skip-download",

        "--no-playlist",

        video_url
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        raise Exception(
            result.stderr.strip()
            or "yt-dlp chạy thất bại"
        )

    return json.loads(result.stdout)


def find_itag_18(info):
    formats = info.get("formats", [])

    for fmt in formats:
        if (
            str(fmt.get("format_id")) == "18"
            and fmt.get("url")
        ):
            return fmt

    return None


def find_progressive_mp4(info):
    """
    Fallback nếu video không có itag 18.
    Tìm MP4 có cả video + audio.
    """

    formats = info.get("formats", [])

    valid = []

    for fmt in formats:
        if not fmt.get("url"):
            continue

        if fmt.get("ext") != "mp4":
            continue

        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")

        if not vcodec or vcodec == "none":
            continue

        if not acodec or acodec == "none":
            continue

        valid.append(fmt)

    if not valid:
        return None

    valid.sort(
        key=lambda x: x.get("height") or 0,
        reverse=True
    )

    return valid[0]


def build_output(info, video_format):
    duration = info.get("duration")

    try:
        duration = round(float(duration or 0))
    except:
        duration = 0

    view_count = info.get("view_count")

    if view_count is None:
        view_count = "0"
    else:
        view_count = str(view_count)

    return {
        "status": True,

        "author": AUTHOR,

        "video": {
            "id": info.get("id"),

            "title": info.get("title"),

            "duration": duration,

            "channel": (
                info.get("channel")
                or info.get("uploader")
            ),

            "viewCount": view_count
        },

        "download": {
            "mp4": video_format.get("url")
        }
    }


def main():
    print("================================")
    print(" YouTube Direct MP4")
    print("================================")

    video_url = input(
        "Nhập link YouTube: "
    ).strip()

    if not video_url:
        print("❌ Chưa nhập link YouTube")
        return

    if not os.path.exists(COOKIE_FILE):
        print(
            f"❌ Không tìm thấy {COOKIE_FILE}"
        )
        return

    try:
        print("\n⏳ Đang lấy thông tin...")

        info = run_ytdlp(video_url)

        print(
            f"✅ Video: {info.get('title')}"
        )

        # ==========================
        # ƯU TIÊN ITAG 18
        # ==========================

        video_format = find_itag_18(info)

        if video_format:
            print(
                "✅ Tìm thấy itag 18"
            )

        else:
            print(
                "⚠️ Không có itag 18"
            )

            print(
                "⏳ Tìm MP4 progressive..."
            )

            video_format = (
                find_progressive_mp4(info)
            )

        if not video_format:
            raise Exception(
                "Không tìm thấy MP4 có cả video + audio"
            )

        output = build_output(
            info,
            video_format
        )

        # ==========================
        # SAVE
        # ==========================

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                output,
                f,
                ensure_ascii=False,
                indent=2
            )

        print("\n==============================")

        print(
            f"✅ Format: {video_format.get('format_id')}"
        )

        print(
            f"✅ Quality: {video_format.get('height')}p"
        )

        print(
            f"✅ Đã lưu: {OUTPUT_FILE}"
        )

        print("==============================\n")

        # ==========================
        # PRINT JSON
        # ==========================

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2
            )
        )

    except Exception as e:

        error_output = {
            "status": False,

            "author": AUTHOR,

            "error": str(e)
        }

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                error_output,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            json.dumps(
                error_output,
                ensure_ascii=False,
                indent=2
            )
        )


if __name__ == "__main__":
    main()