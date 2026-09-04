import os
import sys
import json
import base64
import subprocess
import importlib.util
from threading import Lock


# ============================================================
# AUTO INSTALL PYTHON PACKAGES
# ============================================================

def ensure_package(import_name, pip_name=None):
    if importlib.util.find_spec(import_name) is not None:
        return

    package = pip_name or import_name

    print(f"[INSTALL] Installing {package}...")

    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        package
    ])


ensure_package("fastapi")
ensure_package("uvicorn")
ensure_package("dotenv", "python-dotenv")
ensure_package("yt_dlp", "yt-dlp")


# ============================================================
# IMPORT
# ============================================================

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn


# ============================================================
# ENV
# ============================================================

load_dotenv()


# ============================================================
# CONFIG
# ============================================================

AUTHOR = "khanhduy"

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

COOKIE_FILE = os.path.join(
    BASE_DIR,
    "cookies_runtime.txt"
)

OUTPUT_FILE = os.path.join(
    BASE_DIR,
    "output.json"
)

PORT = int(
    os.getenv("PORT", "3000")
)

YOUTUBE_COOKIES_B64 = os.getenv(
    "YOUTUBE_COOKIES_B64",
    ""
)

output_lock = Lock()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="YouTube Direct MP4 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"]
)


# ============================================================
# COOKIE FROM ENV
# ============================================================

def create_cookie_file():
    """
    Đọc cookies.txt đã encode Base64 từ ENV:
    YOUTUBE_COOKIES_B64=...
    """

    cookie_b64 = os.getenv(
        "YOUTUBE_COOKIES_B64",
        ""
    ).strip()

    if not cookie_b64:
        print(
            "[COOKIE] ⚠️ Không có YOUTUBE_COOKIES_B64"
        )

        return False

    try:
        # Hỗ trợ ENV bị xuống dòng/khoảng trắng
        cookie_b64 = "".join(
            cookie_b64.split()
        )

        cookie_data = base64.b64decode(
            cookie_b64,
            validate=True
        )

        text = cookie_data.decode(
            "utf-8",
            errors="replace"
        )

        if "Netscape HTTP Cookie File" not in text:
            print(
                "[COOKIE] ⚠️ Cookie không có header Netscape"
            )

        with open(
            COOKIE_FILE,
            "wb"
        ) as f:
            f.write(cookie_data)

        print(
            "[COOKIE] ✅ Đã tạo cookies_runtime.txt từ ENV"
        )

        return True

    except Exception as error:
        print(
            "[COOKIE] ❌ Decode lỗi:",
            str(error)
        )

        return False


# ============================================================
# NODE CHECK
# ============================================================

def get_node_version():
    try:
        result = subprocess.run(
            ["node", "-v"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return result.stdout.strip()

    except Exception:
        pass

    return None


# ============================================================
# SAVE OUTPUT
# ============================================================

def save_output(data):
    with output_lock:
        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )


# ============================================================
# SHORT ERROR
# ============================================================

def short_error(text, limit=3000):
    if not text:
        return "Unknown error"

    text = str(text).strip()

    if len(text) > limit:
        return text[:limit] + "..."

    return text


# ============================================================
# RUN YT-DLP
# ============================================================

def run_ytdlp(video_url):
    command = [
        sys.executable,
        "-m",
        "yt_dlp"
    ]

    # Cookie
    if os.path.exists(COOKIE_FILE):
        command.extend([
            "--cookies",
            COOKIE_FILE
        ])

    # Node.js >= 22 dùng giải JS challenge
    node_version = get_node_version()

    if node_version:
        command.extend([
            "--js-runtimes",
            "node"
        ])

    command.extend([
        "--remote-components",
        "ejs:github",

        "--extractor-args",
        "youtube:player_client=default,web_embedded",

        "--dump-single-json",

        "--skip-download",

        "--no-playlist",

        "--socket-timeout",
        "20",

        "--retries",
        "2",

        "--extractor-retries",
        "2",

        video_url
    ])

    print("")
    print("======================================")
    print("[YT-DLP] URL:", video_url)
    print("[YT-DLP] Node:", node_version or "NOT FOUND")
    print(
        "[YT-DLP] Cookie:",
        "YES"
        if os.path.exists(COOKIE_FILE)
        else "NO"
    )
    print("======================================")

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120
    )

    if result.returncode != 0:
        error = (
            result.stderr.strip()
            or result.stdout.strip()
            or "yt-dlp failed"
        )

        raise RuntimeError(
            short_error(error)
        )

    try:
        return json.loads(
            result.stdout
        )

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Không parse được JSON từ yt-dlp: "
            + str(error)
        )


# ============================================================
# FIND ITAG 18
# ============================================================

def find_itag_18(info):
    formats = info.get(
        "formats",
        []
    )

    for fmt in formats:
        if (
            str(fmt.get("format_id")) == "18"
            and fmt.get("url")
        ):
            return fmt

    return None


# ============================================================
# FIND PROGRESSIVE MP4
# ============================================================

def find_progressive_mp4(info):
    """
    Fallback:
    tìm MP4 có cả video + audio trong cùng URL.
    """

    formats = info.get(
        "formats",
        []
    )

    valid = []

    for fmt in formats:
        if not fmt.get("url"):
            continue

        if fmt.get("ext") != "mp4":
            continue

        vcodec = fmt.get(
            "vcodec"
        )

        acodec = fmt.get(
            "acodec"
        )

        if (
            not vcodec
            or vcodec == "none"
        ):
            continue

        if (
            not acodec
            or acodec == "none"
        ):
            continue

        valid.append(fmt)

    if not valid:
        return None

    # Chọn độ phân giải cao nhất
    valid.sort(
        key=lambda x: (
            x.get("height") or 0
        ),
        reverse=True
    )

    return valid[0]


# ============================================================
# BUILD JSON
# ============================================================

def build_output(info, video_format):
    try:
        duration = round(
            float(
                info.get("duration")
                or 0
            )
        )
    except Exception:
        duration = 0

    view_count = info.get(
        "view_count"
    )

    if view_count is None:
        view_count = "0"
    else:
        view_count = str(
            view_count
        )

    return {
        "status": True,

        "author": AUTHOR,

        "video": {
            "id":
                info.get("id"),

            "title":
                info.get("title"),

            "duration":
                duration,

            "channel":
                (
                    info.get("channel")
                    or
                    info.get("uploader")
                ),

            "viewCount":
                view_count
        },

        "download": {
            "mp4":
                video_format.get("url")
        }
    }


# ============================================================
# VALIDATE URL
# ============================================================

def valid_youtube_url(url):
    url = url.lower()

    return (
        "youtube.com/" in url
        or
        "youtu.be/" in url
    )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():
    create_cookie_file()

    print("")
    print("======================================")
    print(" YouTube Direct MP4 API")
    print("======================================")
    print("Author:", AUTHOR)
    print("Port:", PORT)
    print(
        "Node:",
        get_node_version()
        or "NOT FOUND"
    )
    print(
        "Cookies:",
        "READY"
        if os.path.exists(COOKIE_FILE)
        else "NOT FOUND"
    )
    print("======================================")
    print("")


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return {
        "status": True,
        "author": AUTHOR,
        "endpoint":
            "/api/v1/url?url=YOUTUBE_URL",
        "example":
            "/api/v1/url?url=https://www.youtube.com/watch?v=81EY8f25Clo"
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": True,

        "author": AUTHOR,

        "node":
            get_node_version(),

        "cookie":
            os.path.exists(
                COOKIE_FILE
            ),

        "cookie_env":
            bool(
                os.getenv(
                    "YOUTUBE_COOKIES_B64"
                )
            )
    }


# ============================================================
# API
# ============================================================

@app.get("/api/v1/url")
def youtube_api(
    url: str = Query(
        ...,
        description="YouTube URL"
    )
):
    try:
        url = url.strip()

        if not url:
            result = {
                "status": False,
                "author": AUTHOR,
                "error":
                    "Thiếu URL YouTube"
            }

            save_output(result)

            return JSONResponse(
                status_code=400,
                content=result
            )

        if not valid_youtube_url(url):
            result = {
                "status": False,
                "author": AUTHOR,
                "error":
                    "URL YouTube không hợp lệ"
            }

            save_output(result)

            return JSONResponse(
                status_code=400,
                content=result
            )

        # ============================================
        # REFRESH COOKIE FILE NẾU CẦN
        # ============================================

        if (
            not os.path.exists(
                COOKIE_FILE
            )
            and os.getenv(
                "YOUTUBE_COOKIES_B64"
            )
        ):
            create_cookie_file()

        # ============================================
        # YT-DLP
        # ============================================

        info = run_ytdlp(
            url
        )

        print(
            "[VIDEO]",
            info.get("title")
        )

        # ============================================
        # ƯU TIÊN ITAG 18
        # ============================================

        video_format = find_itag_18(
            info
        )

        if video_format:
            print(
                "[FORMAT] ✅ itag 18"
            )

        else:
            print(
                "[FORMAT] ⚠️ Không có itag 18"
            )

            video_format = (
                find_progressive_mp4(
                    info
                )
            )

        # ============================================
        # NO FORMAT
        # ============================================

        if not video_format:
            raise RuntimeError(
                "Không tìm thấy MP4 "
                "có cả video + audio"
            )

        print(
            "[FORMAT ID]",
            video_format.get(
                "format_id"
            )
        )

        print(
            "[QUALITY]",
            str(
                video_format.get(
                    "height"
                )
                or "?"
            ) + "p"
        )

        # ============================================
        # OUTPUT
        # ============================================

        output = build_output(
            info,
            video_format
        )

        save_output(
            output
        )

        return JSONResponse(
            status_code=200,
            content=output
        )

    except subprocess.TimeoutExpired:
        output = {
            "status": False,
            "author": AUTHOR,
            "error":
                "yt-dlp timeout"
        }

        save_output(
            output
        )

        return JSONResponse(
            status_code=504,
            content=output
        )

    except Exception as error:
        output = {
            "status": False,
            "author": AUTHOR,
            "error":
                short_error(error)
        }

        save_output(
            output
        )

        return JSONResponse(
            status_code=500,
            content=output
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT
    )