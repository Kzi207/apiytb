import os
import sys
import json
import base64
import asyncio
import subprocess
import tempfile

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pathlib import Path
from urllib.parse import urlparse
from threading import Lock
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG FROM ENV
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

AUTHOR = os.getenv(
    "AUTHOR",
    "khanhduy"
)

PORT = int(
    os.getenv(
        "PORT",
        "3000"
    )
)

YT_TIMEOUT = int(
    os.getenv(
        "YT_TIMEOUT",
        "120"
    )
)

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

COOKIE_FILE = BASE_DIR / "cookies_runtime.txt"

OUTPUT_FILE = BASE_DIR / "output.json"

output_lock = Lock()


# ============================================================
# COOKIE FROM ENV
# ============================================================

def create_cookie_file():
    """
    Decode cookie Base64 từ ENV:
    YOUTUBE_COOKIES_B64
    """

    cookie_b64 = os.getenv(
        "YOUTUBE_COOKIES_B64",
        ""
    ).strip()

    if not cookie_b64:
        print(
            "[COOKIE] Không có YOUTUBE_COOKIES_B64"
        )

        return False

    try:
        # Xóa spaces / newline trong ENV
        cookie_b64 = "".join(
            cookie_b64.split()
        )

        # Fix padding base64
        remainder = len(
            cookie_b64
        ) % 4

        if remainder:
            cookie_b64 += (
                "=" * (4 - remainder)
            )

        cookie_bytes = (
            base64.b64decode(
                cookie_b64
            )
        )

        cookie_text = (
            cookie_bytes.decode(
                "utf-8",
                errors="replace"
            )
        )

        # Chuẩn hóa newline Linux
        cookie_text = (
            cookie_text
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )

        # Check Netscape format
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
            f.write(
                cookie_text
            )

        try:
            os.chmod(
                COOKIE_FILE,
                0o600
            )
        except Exception:
            pass

        print(
            f"[COOKIE] READY ({len(cookie_text)} bytes)"
        )

        return True

    except Exception as e:
        print(
            "[COOKIE ERROR]",
            str(e)
        )

        return False


# ============================================================
# NODE VERSION
# ============================================================

def get_node_version():
    try:
        result = subprocess.run(
            [
                "node",
                "-v"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            return (
                result.stdout
                .strip()
            )

    except Exception:
        pass

    return None


def node_22_or_newer():
    version = get_node_version()

    if not version:
        return False

    try:
        major = int(
            version
            .lower()
            .replace("v", "")
            .split(".")[0]
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
            return (
                result.stdout
                .strip()
            )

    except Exception:
        pass

    return None


# ============================================================
# ERROR CLEANER
# ============================================================

def clean_error(
    error,
    limit=4000
):
    text = str(
        error or "Unknown error"
    )

    proxy = os.getenv(
        "YOUTUBE_PROXY",
        ""
    ).strip()

    # Không leak user/pass proxy
    if proxy:
        text = text.replace(
            proxy,
            "***PROXY***"
        )

    if len(text) > limit:
        text = (
            text[:limit]
            + "..."
        )

    return text


# ============================================================
# SAVE OUTPUT
# ============================================================

def save_output(data):
    """
    Lưu response cuối cùng vào output.json
    """

    with output_lock:
        temp_name = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(
                    BASE_DIR
                ),
                delete=False,
                suffix=".json"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

                temp_name = (
                    f.name
                )

            os.replace(
                temp_name,
                OUTPUT_FILE
            )

        except Exception as e:
            print(
                "[OUTPUT ERROR]",
                str(e)
            )

            if (
                temp_name
                and os.path.exists(
                    temp_name
                )
            ):
                try:
                    os.remove(
                        temp_name
                    )
                except Exception:
                    pass


# ============================================================
# VALIDATE YOUTUBE URL
# ============================================================

def valid_youtube_url(url):
    try:
        parsed = urlparse(
            url
        )

        if parsed.scheme not in (
            "http",
            "https"
        ):
            return False

        host = (
            parsed.hostname
            or ""
        ).lower()

        allowed_hosts = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be"
        }

        return (
            host in allowed_hosts
        )

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

    # =============================================
    # COOKIE
    # =============================================

    if COOKIE_FILE.exists():
        command.extend([
            "--cookies",
            str(
                COOKIE_FILE
            )
        ])

    # =============================================
    # USER AGENT
    # =============================================

    user_agent = os.getenv(
        "YOUTUBE_USER_AGENT",
        ""
    ).strip()

    if user_agent:
        command.extend([
            "--user-agent",
            user_agent
        ])

    # =============================================
    # PROXY
    # =============================================

    proxy = os.getenv(
        "YOUTUBE_PROXY",
        ""
    ).strip()

    if proxy:
        command.extend([
            "--proxy",
            proxy
        ])

    # =============================================
    # JS CHALLENGE
    # =============================================

    if node_22_or_newer():
        command.extend([
            "--js-runtimes",
            "node",

            "--remote-components",
            "ejs:github"
        ])

    # =============================================
    # YOUTUBE CLIENT
    # =============================================

    command.extend([
        "--extractor-args",
        "youtube:player_client=default,web_embedded"
    ])

    command.append(
        video_url
    )

    return command


# ============================================================
# RUN YT-DLP
# ============================================================

def run_ytdlp(video_url):
    # Nếu file cookie mất
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
        "===================================="
    )

    print(
        "[YT-DLP URL]",
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
        "===================================="
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

    except json.JSONDecodeError:
        raise RuntimeError(
            "Không đọc được JSON từ yt-dlp"
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
# FALLBACK MP4
# ============================================================

def find_progressive_mp4(info):
    """
    MP4 có cả audio + video
    """

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

        valid.append(
            fmt
        )

    if not valid:
        return None

    valid.sort(
        key=lambda x: (
            x.get("height")
            or 0,

            x.get("tbr")
            or 0
        ),
        reverse=True
    )

    return valid[0]


# ============================================================
# BUILD RESPONSE JSON
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
# FASTAPI LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("")
    print(
        "======================================"
    )
    print(
        " YouTube Direct MP4 API"
    )
    print(
        "======================================"
    )

    create_cookie_file()

    print(
        "Author:",
        AUTHOR
    )

    print(
        "Port:",
        PORT
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
        "YES"
        if YOUTUBE_USER_AGENT
        else "NO"
    )

    print(
        "Proxy:",
        "YES"
        if YOUTUBE_PROXY
        else "DIRECT"
    )

    print(
        "======================================"
    )
    print("")

    yield

    # Xóa cookie runtime khi shutdown
    try:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()

    except Exception:
        pass


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="YouTube Direct MP4 API",
    version="3.0.0",
    lifespan=lifespan
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=[
        "GET",
        "OPTIONS"
    ],
    allow_headers=["*"]
)


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

    # ============================================
    # VALIDATE
    # ============================================

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
        # ========================================
        # YT-DLP
        # ========================================

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

        # ========================================
        # ITAG 18
        # ========================================

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
                "[FORMAT] itag 18 unavailable"
            )

            # ====================================
            # FALLBACK
            # ====================================

            video_format = (
                find_progressive_mp4(
                    info
                )
            )

        if not video_format:
            raise RuntimeError(
                "Không tìm thấy MP4 có cả video và audio"
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

        # ========================================
        # OUTPUT
        # ========================================

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


# ============================================================
# RUN LOCAL / RENDER
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT
    )