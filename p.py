import os
import sys
import json
import base64
import asyncio
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from threading import Lock

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

AUTHOR = "khanhduy"

BASE_DIR = Path(__file__).resolve().parent

COOKIE_FILE = BASE_DIR / "cookies_runtime.txt"
OUTPUT_FILE = BASE_DIR / "output.json"

PORT = int(os.getenv("PORT", "10000"))

YOUTUBE_COOKIES_B64 = os.getenv(
    "YOUTUBE_COOKIES_B64",
    ""
).strip()

YOUTUBE_USER_AGENT = os.getenv(
    "YOUTUBE_USER_AGENT",
    ""
).strip()

YOUTUBE_PROXY = os.getenv(
    "YOUTUBE_PROXY",
    ""
).strip()

YT_TIMEOUT = int(
    os.getenv("YT_TIMEOUT", "120")
)

output_lock = Lock()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="YouTube Direct MP4 API",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"]
)


# ============================================================
# COOKIE FROM ENV
# ============================================================

def create_cookie_file():
    cookie_b64 = os.getenv(
        "YOUTUBE_COOKIES_B64",
        ""
    ).strip()

    if not cookie_b64:
        print(
            "[COOKIE] YOUTUBE_COOKIES_B64 chưa được cấu hình"
        )
        return False

    try:
        # Xóa whitespace do copy ENV
        cookie_b64 = "".join(
            cookie_b64.split()
        )

        # Fix padding Base64 nếu cần
        missing_padding = len(cookie_b64) % 4

        if missing_padding:
            cookie_b64 += "=" * (
                4 - missing_padding
            )

        cookie_bytes = base64.b64decode(
            cookie_b64
        )

        cookie_text = cookie_bytes.decode(
            "utf-8",
            errors="replace"
        )

        # Render chạy Linux -> LF
        cookie_text = (
            cookie_text
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )

        # Netscape cookie validation
        if not (
            cookie_text.startswith(
                "# Netscape HTTP Cookie File"
            )
            or cookie_text.startswith(
                "# HTTP Cookie File"
            )
        ):
            print(
                "[COOKIE] Cookie không đúng Netscape format"
            )

            return False

        with open(
            COOKIE_FILE,
            "w",
            encoding="utf-8",
            newline="\n"
        ) as f:
            f.write(cookie_text)

        try:
            os.chmod(
                COOKIE_FILE,
                0o600
            )
        except Exception:
            pass

        print(
            f"[COOKIE] READY - {len(cookie_text)} bytes"
        )

        return True

    except Exception as e:
        print(
            "[COOKIE ERROR]",
            str(e)
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


def node_22_or_newer():
    version = get_node_version()

    if not version:
        return False

    try:
        number = version.lower().replace(
            "v",
            ""
        )

        major = int(
            number.split(".")[0]
        )

        return major >= 22

    except Exception:
        return False


# ============================================================
# YT-DLP VERSION
# ============================================================

def get_ytdlp_version():
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--version"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            return result.stdout.strip()

    except Exception:
        pass

    return None


# ============================================================
# REDACT SECRET
# ============================================================

def clean_error(text):
    text = str(text or "Unknown error")

    # Không để proxy credential lọt vào API
    proxy = os.getenv(
        "YOUTUBE_PROXY",
        ""
    ).strip()

    if proxy:
        text = text.replace(
            proxy,
            "***PROXY***"
        )

    if len(text) > 4000:
        text = text[:4000] + "..."

    return text


# ============================================================
# SAVE OUTPUT
# ============================================================

def save_output(data):
    """
    Atomic write để nhiều request hạn chế làm hỏng output.json.
    """

    with output_lock:
        temp_file = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(BASE_DIR),
                delete=False,
                suffix=".json"
            ) as f:
                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

                temp_file = f.name

            os.replace(
                temp_file,
                OUTPUT_FILE
            )

        except Exception as e:
            print(
                "[OUTPUT ERROR]",
                str(e)
            )

            if (
                temp_file
                and os.path.exists(
                    temp_file
                )
            ):
                try:
                    os.remove(
                        temp_file
                    )
                except Exception:
                    pass


# ============================================================
# VALIDATE YOUTUBE URL
# ============================================================

def valid_youtube_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in (
            "http",
            "https"
        ):
            return False

        host = (
            parsed.hostname
            or ""
        ).lower()

        allowed = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be"
        }

        return host in allowed

    except Exception:
        return False


# ============================================================
# BUILD YT-DLP COMMAND
# ============================================================

def build_command(video_url):
    command = [
        sys.executable,
        "-m",
        "yt_dlp",

        "--ignore-config",

        "--dump-single-json",

        "--skip-download",

        "--no-playlist",

        "--socket-timeout",
        "20",

        "--retries",
        "2",

        "--extractor-retries",
        "2"
    ]

    # ========================================================
    # COOKIE
    # ========================================================

    if COOKIE_FILE.exists():
        command.extend([
            "--cookies",
            str(COOKIE_FILE)
        ])

    # ========================================================
    # USER AGENT
    # ========================================================

    user_agent = os.getenv(
        "YOUTUBE_USER_AGENT",
        ""
    ).strip()

    if user_agent:
        command.extend([
            "--user-agent",
            user_agent
        ])

    # ========================================================
    # PROXY
    # ========================================================

    proxy = os.getenv(
        "YOUTUBE_PROXY",
        ""
    ).strip()

    if proxy:
        command.extend([
            "--proxy",
            proxy
        ])

    # ========================================================
    # JS CHALLENGE
    # ========================================================

    if node_22_or_newer():
        command.extend([
            "--js-runtimes",
            "node",

            "--remote-components",
            "ejs:github"
        ])

    # ========================================================
    # CLIENT
    # ========================================================

    command.extend([
        "--extractor-args",
        "youtube:player_client=default,web_embedded"
    ])

    # URL LUÔN CUỐI CÙNG
    command.append(
        video_url
    )

    return command


# ============================================================
# RUN YT-DLP
# ============================================================

def run_ytdlp(video_url):
    # Tạo lại cookie nếu server restart / file bị xóa
    if (
        not COOKIE_FILE.exists()
        and os.getenv(
            "YOUTUBE_COOKIES_B64"
        )
    ):
        create_cookie_file()

    command = build_command(
        video_url
    )

    print("")
    print(
        "========================================"
    )
    print(
        "[YT-DLP]",
        video_url
    )

    print(
        "[NODE]",
        get_node_version()
        or "NOT FOUND"
    )

    print(
        "[COOKIE]",
        "YES"
        if COOKIE_FILE.exists()
        else "NO"
    )

    print(
        "[USER AGENT]",
        "YES"
        if os.getenv(
            "YOUTUBE_USER_AGENT"
        )
        else "NO"
    )

    print(
        "[PROXY]",
        "YES"
        if os.getenv(
            "YOUTUBE_PROXY"
        )
        else "DIRECT"
    )

    print(
        "========================================"
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=YT_TIMEOUT
    )

    if result.returncode != 0:
        error = (
            result.stderr.strip()
            or result.stdout.strip()
            or "yt-dlp failed"
        )

        raise RuntimeError(
            clean_error(
                error
            )
        )

    try:
        return json.loads(
            result.stdout
        )

    except json.JSONDecodeError as e:
        print(
            "[STDOUT]",
            result.stdout[:1000]
        )

        print(
            "[STDERR]",
            result.stderr[:1000]
        )

        raise RuntimeError(
            "Không đọc được JSON từ yt-dlp: "
            + str(e)
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
            str(
                fmt.get(
                    "format_id"
                )
            ) == "18"
            and fmt.get(
                "url"
            )
        ):
            return fmt

    return None


# ============================================================
# FALLBACK PROGRESSIVE MP4
# ============================================================

def find_progressive_mp4(info):
    formats = info.get(
        "formats",
        []
    )

    valid = []

    for fmt in formats:
        if not fmt.get(
            "url"
        ):
            continue

        if fmt.get(
            "ext"
        ) != "mp4":
            continue

        vcodec = fmt.get(
            "vcodec"
        )

        acodec = fmt.get(
            "acodec"
        )

        # Phải có video
        if (
            not vcodec
            or vcodec == "none"
        ):
            continue

        # Phải có audio
        if (
            not acodec
            or acodec == "none"
        ):
            continue

        valid.append(
            fmt
        )

    if not valid:
        return None

    # Ưu tiên resolution cao
    valid.sort(
        key=lambda x: (
            x.get(
                "height"
            )
            or 0,
            x.get(
                "tbr"
            )
            or 0
        ),
        reverse=True
    )

    return valid[0]


# ============================================================
# OUTPUT JSON
# ============================================================

def build_output(
    info,
    video_format
):
    try:
        duration = round(
            float(
                info.get(
                    "duration"
                )
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
                info.get(
                    "id"
                ),

            "title":
                info.get(
                    "title"
                ),

            "duration":
                duration,

            "channel":
                (
                    info.get(
                        "channel"
                    )
                    or
                    info.get(
                        "uploader"
                    )
                ),

            "viewCount":
                view_count
        },

        "download": {
            "mp4":
                video_format.get(
                    "url"
                )
        }
    }


# ============================================================
# STARTUP
# ============================================================

@app.on_event(
    "startup"
)
async def startup():
    create_cookie_file()

    print("")
    print(
        "========================================"
    )
    print(
        "      YouTube Direct MP4 API"
    )
    print(
        "========================================"
    )

    print(
        "Author:",
        AUTHOR
    )

    print(
        "yt-dlp:",
        get_ytdlp_version()
    )

    print(
        "Node:",
        get_node_version()
        or "NOT FOUND"
    )

    print(
        "Cookie:",
        "READY"
        if COOKIE_FILE.exists()
        else "NOT FOUND"
    )

    print(
        "User-Agent:",
        "READY"
        if YOUTUBE_USER_AGENT
        else "NOT SET"
    )

    print(
        "Proxy:",
        "READY"
        if YOUTUBE_PROXY
        else "DIRECT"
    )

    print(
        "========================================"
    )
    print("")


# ============================================================
# HOME
# ============================================================

@app.get("/")
async def home():
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
async def health():
    cookie_exists = (
        COOKIE_FILE.exists()
    )

    cookie_size = (
        COOKIE_FILE.stat().st_size
        if cookie_exists
        else 0
    )

    return {
        "status": True,

        "author": AUTHOR,

        "python":
            sys.version.split()[0],

        "yt_dlp":
            get_ytdlp_version(),

        "node":
            get_node_version(),

        "node22":
            node_22_or_newer(),

        "cookie_env":
            bool(
                os.getenv(
                    "YOUTUBE_COOKIES_B64"
                )
            ),

        "cookie_file":
            cookie_exists,

        "cookie_size":
            cookie_size,

        "user_agent":
            bool(
                os.getenv(
                    "YOUTUBE_USER_AGENT"
                )
            ),

        "proxy":
            bool(
                os.getenv(
                    "YOUTUBE_PROXY"
                )
            )
    }


# ============================================================
# API
# ============================================================

@app.get(
    "/api/v1/url"
)
async def youtube_api(
    url: str = Query(
        ...,
        description="YouTube URL"
    )
):
    url = url.strip()

    if not valid_youtube_url(
        url
    ):
        output = {
            "status": False,

            "author": AUTHOR,

            "error":
                "URL YouTube không hợp lệ"
        }

        save_output(
            output
        )

        return JSONResponse(
            status_code=400,
            content=output
        )

    try:
        # Chạy subprocess ngoài event loop
        info = await asyncio.to_thread(
            run_ytdlp,
            url
        )

        print(
            "[VIDEO]",
            info.get(
                "title"
            )
        )

        # ============================================
        # ITAG 18
        # ============================================

        video_format = (
            find_itag_18(
                info
            )
        )

        if video_format:
            print(
                "[FORMAT] itag=18"
            )

        else:
            print(
                "[FORMAT] itag 18 không có, fallback..."
            )

            video_format = (
                find_progressive_mp4(
                    info
                )
            )

        if not video_format:
            raise RuntimeError(
                "Không tìm thấy MP4 progressive "
                "có cả video và audio"
            )

        print(
            "[FORMAT ID]",
            video_format.get(
                "format_id"
            )
        )

        print(
            "[QUALITY]",
            video_format.get(
                "height"
            )
        )

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

    except Exception as e:
        output = {
            "status": False,

            "author": AUTHOR,

            "error":
                clean_error(
                    e
                )
        }

        save_output(
            output
        )

        return JSONResponse(
            status_code=500,
            content=output
        )