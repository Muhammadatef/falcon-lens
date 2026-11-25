# ruff: noqa: E501, S603, S607
"""Frame-accurate render of the hook composition: step the page's clock, capture each frame, encode with ffmpeg.

The page (`composition/`) is a pure function of time, so there is nothing to record in real time: for frame `i`
this asks the page for `i / fps` seconds, waits until it says the frame is ready, and takes a lossless capture.
Slices of the film render in parallel, each in its own headless Chromium (Playwright, the version pinned for
`make submission`).
"""

from __future__ import annotations

import functools
import http.server
import json
import subprocess
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PAGE = "submission/build/hook_video/composition/index.html"
SIZES = {"portrait": (1080, 1920), "landscape": (1920, 1080)}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


class _Server(http.server.ThreadingHTTPServer):
    # Several browsers open many connections at once; the default backlog of 5 drops some of them.
    request_queue_size = 512
    daemon_threads = True


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Serve a folder on a free local port (the page loads its fonts and scripts over HTTP)."""
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _open(pw: Any, fmt: str, hook: dict[str, Any], base: str) -> tuple[Any, Any]:
    width, height = SIZES[fmt]
    browser = pw.chromium.launch(args=["--font-render-hinting=none", "--force-color-profile=srgb"])
    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
    page.add_init_script(f"window.__HOOK__ = {json.dumps(hook, ensure_ascii=False)};")
    problems: list[str] = []
    page.on("pageerror", lambda exc: problems.append(str(exc)))
    page.on("requestfailed", lambda req: problems.append(f"request failed: {req.url}"))
    page.goto(f"{base}/{PAGE}")
    try:
        # Poll on a timer: a headless page that is not animating produces no frames, so rAF polling can stall.
        page.wait_for_function("window.__ready === true || !!window.__error", timeout=45_000, polling=50)
    except Exception as exc:
        state = page.evaluate("[!!window.__HOOK__, document.fonts.status, document.fonts.size, location.href]")
        raise RuntimeError(f"composition did not become ready: {state} {problems[:5]}") from exc
    error = page.evaluate("window.__error || null")
    if error or problems:
        raise RuntimeError(f"composition failed to start: {error} {problems[:5]}")
    return browser, page


def _slice(args: tuple[str, dict[str, Any], str, list[int], int, str]) -> int:
    from playwright.sync_api import sync_playwright

    fmt, hook, base, frames, fps, out_dir = args
    with sync_playwright() as pw:
        browser, page = _open(pw, fmt, hook, base)
        for i in frames:
            page.evaluate("t => window.__seek(t)", i / fps)
            page.screenshot(path=f"{out_dir}/{i:05d}.png", type="png")
        browser.close()
    return len(frames)


def hook_payload(
    timeline: dict[str, Any], data: dict[str, Any], fmt: str, frames_url: str | None, label: bool
) -> dict[str, Any]:
    return {
        "timeline": timeline,
        "data": data,
        "format": fmt,
        "options": {"frames": frames_url, "label": label, "sourceFps": 30},
    }


def render_frames(
    timeline: dict[str, Any], data: dict[str, Any], fmt: str, out_dir: Path, *,
    live_dir: Path | None = None, workers: int = 6, label: bool = True, only: list[int] | None = None,
) -> int:  # fmt: skip
    """Write one PNG per frame into `out_dir` (or only the frames listed in `only`). Returns the frame count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    site, base = serve(ROOT)
    frames_url = None
    extra = None
    if live_dir is not None:
        extra, frames_url = serve(live_dir)
    hook = hook_payload(timeline, data, fmt, frames_url, label)
    fps = int(timeline["fps"])
    todo = only if only is not None else list(range(int(timeline["frames"])))
    workers = max(1, min(workers, len(todo)))
    # Contiguous slices: neighbouring frames share decoded footage frames and warm caches.
    size = -(-len(todo) // workers)
    jobs = [(fmt, hook, base, todo[k : k + size], fps, str(out_dir)) for k in range(0, len(todo), size)]
    try:
        if len(jobs) == 1:
            done = _slice(jobs[0])
        else:
            with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
                done = sum(pool.map(_slice, jobs))
    finally:
        site.shutdown()
        if extra is not None:
            extra.shutdown()
    return done


X264 = [
    "-c:v",
    "libx264",
    "-profile:v",
    "high",
    "-pix_fmt",
    "yuv420p",
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-color_range",
    "tv",
    "-movflags",
    "+faststart",
]
# RGB frames to BT.709 limited-range video, said explicitly so players and editors agree on the colours.
TO_709 = (
    "scale=in_range=full:out_range=limited:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p"
)


def encode(
    frames_dir: Path, fps: int, audio: Path | None, out: Path, *, crf: int = 16, grain: bool = True, level: str = "4.2"
) -> None:
    """PNG frames (+ a WAV) to H.264/AAC. A trace of grain keeps the dark gradients from banding."""
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = ("noise=alls=5:allf=t+u," if grain else "") + TO_709
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-framerate",
        str(fps),
        "-start_number",
        "0",
        "-i",
        str(frames_dir / "%05d.png"),
    ]
    if audio is not None:
        cmd += ["-i", str(audio)]
    cmd += ["-vf", vf, *X264, "-level:v", level, "-preset", "slow", "-crf", str(crf), "-r", str(fps)]
    if audio is not None:
        cmd += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-shortest"]
    subprocess.run([*cmd, str(out)], check=True)


def transcode(src: Path, out: Path, *, width: int, height: int, fps: int, max_mb: float, audio_kbps: int = 160) -> None:
    """A smaller copy for embedding (Keynote): two-pass H.264 High at a bitrate that fits `max_mb`."""
    seconds = float(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(src)],
            capture_output=True, text=True, check=True,
        ).stdout
    )  # fmt: skip
    video_kbps = int(max_mb * 8192 * 0.94 / seconds - audio_kbps)
    vf = f"scale={width}:{height}:flags=lanczos,fps={fps},format=yuv420p"
    common = [
        "-vf",
        vf,
        *X264,
        "-level:v",
        "4.0",
        "-preset",
        "slow",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{int(video_kbps * 1.6)}k",
        "-bufsize",
        f"{video_kbps * 3}k",
    ]
    log = str(out.with_suffix(".2pass"))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            *common,
            "-pass",
            "1",
            "-passlogfile",
            log,
            "-an",
            "-f",
            "mp4",
            "/dev/null",
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(src),
            *common,
            "-pass",
            "2",
            "-passlogfile",
            log,
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_kbps}k",
            "-ar",
            "48000",
            str(out),
        ],
        check=True,
    )
    for leftover in out.parent.glob(out.with_suffix(".2pass").name + "*"):
        leftover.unlink()


def extract_live(footage: Path, timeline: dict[str, Any], out_dir: Path, source_fps: int = 30) -> int:
    """Pull the footage frames the cut needs, named by their frame number in the source."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for pic in timeline.get("live_pic", []):
        lo = max(0, int(pic["src0"] * source_fps) - 1)
        hi = int(pic["src1"] * source_fps) + 2
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(footage), "-vf", f"select='between(n\\,{lo}\\,{hi})'", "-fps_mode", "passthrough",
             "-start_number", str(lo), "-q:v", "1", "-pix_fmt", "yuvj444p", str(out_dir / "%05d.jpg")],
            check=True,
        )  # fmt: skip
        count += hi - lo + 1
    return count


def storyboard(frames: list[Path], times: list[float], out: Path, *, portrait: bool) -> None:
    """A contact sheet of the chosen frames with their times, drawn by the browser (ffmpeg here has no text filter)."""
    from playwright.sync_api import sync_playwright

    site, base = serve(frames[0].parent)
    cols = 8 if portrait else 4
    cell = 300 if portrait else 600
    tiles = "".join(
        f'<figure><img src="{base}/{f.name}"><figcaption>{t // 60:.0f}:{t % 60:04.1f}</figcaption></figure>'
        for f, t in zip(frames, times, strict=True)
    )
    html = (
        "<!doctype html><meta charset=utf-8><style>body{margin:0;padding:28px;background:#070b14;color:#aeb8cc;font:600 22px ui-monospace,Menlo,monospace}"
        f"main{{display:grid;grid-template-columns:repeat({cols},{cell}px);gap:18px}}figure{{margin:0}}img{{width:{cell}px;display:block;border-radius:10px;border:1px solid #2a3757}}"
        "figcaption{padding:8px 2px 0}h1{font:650 30px system-ui;color:#f2eee6;margin:0 0 20px}</style>"
        f"<h1>Falcon Lens hook v2: storyboard</h1><main>{tiles}</main>"
    )
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": cols * (cell + 18) + 40, "height": 800})
            page.set_content(html, wait_until="load")
            page.wait_for_function("[...document.images].every((i) => i.complete && i.naturalWidth > 0)", polling=50)
            page.screenshot(path=str(out), full_page=True, type="png")
            browser.close()
    finally:
        site.shutdown()
