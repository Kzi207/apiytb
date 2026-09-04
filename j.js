const { execFile } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");

const execFileAsync = promisify(execFile);

const VIDEO_URL =
  process.argv[2] ||
  "https://www.youtube.com/watch?v=81EY8f25Clo";

async function getInfo(url) {
  const { stdout } = await execFileAsync(
    "yt-dlp",
    [
      "--cookies",
      "cookies.txt",

      "--js-runtimes",
      "node",

      "--remote-components",
      "ejs:github",

      "--extractor-args",
      "youtube:player_client=default,web_embedded",

      "--dump-single-json",

      "--skip-download",

      url
    ],
    {
      maxBuffer: 100 * 1024 * 1024
    }
  );

  return JSON.parse(stdout);
}

async function main() {
  console.log("Đang lấy thông tin video...");

  const info = await getInfo(VIDEO_URL);

  const mp4 = info.formats?.find(
    f =>
      String(f.format_id) === "18" &&
      f.url
  );

  if (!mp4) {
    throw new Error(
      "Không tìm thấy format itag 18"
    );
  }

  const output = {
    status: true,

    author: "dungkon",

    video: {
      id: info.id || null,

      title: info.title || null,

      duration:
        Math.round(
          Number(info.duration) || 0
        ),

      channel:
        info.channel ||
        info.uploader ||
        null,

      viewCount:
        String(info.view_count ?? 0)
    },

    download: {
      mp4: mp4.url
    }
  };

  fs.writeFileSync(
    "output.json",
    JSON.stringify(output, null, 2),
    "utf8"
  );

  console.log("✅ Thành công");
  console.log("Format:", mp4.format_id);
  console.log("Quality:", mp4.height + "p");
  console.log("Đã lưu: output.json");
}

main().catch(error => {
  console.error(
    "❌ Lỗi:",
    error.stderr || error.message
  );
});