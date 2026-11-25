# ruff: noqa: E501, S603, S607
"""Build the Falcon Lens hook film: logo sting, cold open, the Falcon's live steps, end card.

    uv run --no-project --with-requirements submission/build/hook_video/requirements.txt \\
        python submission/build/hook_video/build.py --out deliverables/hook_v2 \\
        --clips data/private/voice/clips/ar_ae --footage deliverables/media/hook.mp4

Outputs (never committed: the films carry the product's private voice clips and the owner's footage):
  intro_logo_{portrait,landscape}.mp4      the logo sting alone
  falcon_sequence_{portrait,landscape}.mp4 the animation alone (no footage needed)
  hook_final_{portrait,landscape}.mp4      the cut that opens on the footage (only with --footage)
  hook_final_*_keynote.mp4                 smaller copies for embedding in a deck
  storyboard.png                           contact sheet of the main cut

Needs ffmpeg and ffprobe on PATH and Chromium for Playwright
(`uv run --no-project --with playwright==1.65.2 python -m playwright install chromium`).
What it does and does not do: it only reads the clips, the earcon and the footage; it writes into --out and --work.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import align  # noqa: E402
import audio  # noqa: E402
import cues  # noqa: E402
import render  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
NAMES = {"intro": "intro_logo", "sequence": "falcon_sequence", "final": "hook_final"}
KEYNOTE = {"portrait": (720, 1280), "landscape": (1280, 720)}
STORY = (
    1.6,
    4.6,
    7.9,
    9.3,
    11.3,
    12.5,
    14.6,
    16.4,
    18.0,
    21.3,
    25.2,
    30.3,
    31.6,
    36.0,
    42.0,
    44.9,
)  # seconds in the main cut


def timeline_for(variant: str, clips_dir: Path, fps: int, use_align: bool, work: Path) -> dict[str, Any]:
    lengths = {ln.key: audio.clip_seconds(clips_dir / f"ar_ae.{ln.key}.mp3") for ln in cues.FALCON}
    words: dict[str, list[list[Any]]] = {}
    cache = work / "words.json"
    if use_align:
        if cache.exists():
            words = json.loads(cache.read_text())
        else:
            words = align.align_clips(
                {ln.key: (clips_dir / f"ar_ae.{ln.key}.mp3", ln.ar, lengths[ln.key]) for ln in cues.FALCON}
            )
            cache.write_text(json.dumps(words, ensure_ascii=False))
    return cues.build_timeline(variant, lengths, words or None, fps)


def check_clips(clips_dir: Path) -> list[str]:
    """The captions must be the words in the clips: compare the cue sheet with the clip manifest when there is one."""
    manifest = clips_dir / "manifest.json"
    if not manifest.exists():
        return []
    spoken = {c["id"].removeprefix("ar_ae."): c["text"] for c in json.loads(manifest.read_text())}
    return [
        f"{ln.key}: clip says {spoken.get(ln.key)!r}, caption says {ln.ar!r}"
        for ln in cues.FALCON
        if spoken.get(ln.key) != ln.ar
    ]


def build_variant(variant: str, args: argparse.Namespace, out: Path, work: Path) -> dict[str, Any]:
    vwork = work / variant
    vwork.mkdir(parents=True, exist_ok=True)
    tl = timeline_for(variant, args.clips, args.fps, not args.no_align, work)
    if tl["duration"] > cues.HARD_MAX:
        raise SystemExit(f"{variant}: {tl['duration']:.1f} s is over the {cues.HARD_MAX:.0f} s limit")
    footage = args.footage if variant == "final" else None
    sound = audio.build(tl, vwork, args.clips, args.sfx, footage)
    tl["env"] = sound["env"]
    (vwork / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False))
    live_dir = None
    if footage is not None:
        live_dir = vwork / "live"
        render.extract_live(footage, tl, live_dir)
    report: dict[str, Any] = {"seconds": tl["duration"], "audio": sound["reading"], "files": []}
    for fmt in args.formats:
        frames = vwork / f"frames_{fmt}"
        if frames.exists():
            shutil.rmtree(frames)
        render.render_frames(
            tl, cues.page_data(variant), fmt, frames, live_dir=live_dir, workers=args.workers, label=variant != "intro"
        )
        target = out / f"{NAMES[variant]}_{fmt}.mp4"
        render.encode(frames, args.fps, vwork / "master.wav", target, crf=args.crf)
        report["files"].append(target.name)
        if variant == args.main:
            small = out / f"{NAMES[variant]}_{fmt}_keynote.mp4"
            w, h = KEYNOTE[fmt]
            render.transcode(target, small, width=w, height=h, fps=30, max_mb=args.keynote_mb)
            report["files"].append(small.name)
            if fmt == args.formats[0]:
                picks = [min(tl["frames"] - 1, round(t / STORY[-1] * (tl["duration"] - 0.6) * args.fps)) for t in STORY]
                render.storyboard(
                    [frames / f"{i:05d}.png" for i in picks],
                    [i / args.fps for i in picks],
                    out / "storyboard.png",
                    portrait=fmt == "portrait",
                )
                report["files"].append("storyboard.png")
        if not args.keep_frames:
            shutil.rmtree(frames)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "deliverables" / "hook_v2")
    ap.add_argument("--work", type=Path, default=ROOT / "work" / "hook-video")
    ap.add_argument(
        "--clips",
        type=Path,
        default=ROOT / "data" / "private" / "voice" / "clips" / "ar_ae",
        help="the Falcon's Arabic clips (private)",
    )
    ap.add_argument("--sfx", type=Path, default=ROOT / "web" / "public" / "voice" / "sfx", help="the verdict earcons")
    ap.add_argument(
        "--footage", type=Path, default=None, help="the owner's dramatisation; without it only the animation is built"
    )
    ap.add_argument("--variants", default="intro,sequence,final")
    ap.add_argument("--formats", default="portrait,landscape")
    ap.add_argument("--fps", type=int, default=cues.FPS)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--crf", type=int, default=17)
    ap.add_argument("--keynote-mb", type=float, default=14.0)
    ap.add_argument("--no-align", action="store_true", help="skip the local word alignment of the clips")
    ap.add_argument("--keep-frames", action="store_true")
    args = ap.parse_args()
    args.formats = [f for f in args.formats.split(",") if f]
    variants = [v for v in args.variants.split(",") if v]
    if args.footage is None or not args.footage.exists():
        args.footage = None
        variants = [v for v in variants if v != "final"]
        print("no footage: building the logo sting and the animation only")
    args.main = "final" if "final" in variants else "sequence"
    problems = check_clips(args.clips)
    if problems:
        print("captions and clips disagree:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    summary = {v: build_variant(v, args, args.out, args.work) for v in variants}
    (args.out / "build_report.json").write_text(json.dumps(summary, indent=1))
    for v, rep in summary.items():
        print(f"{v}: {rep['seconds']:.2f} s  {rep['audio']}  {', '.join(rep['files'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
