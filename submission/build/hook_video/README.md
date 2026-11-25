# Hook film builder

Builds the opening film of the pitch in code: a logo sting, a cold open, the Falcon answering step by step as it
does on `/voice`, and the end card. Portrait (1080 x 1920) and landscape (1920 x 1080), 60 fps, H.264 + AAC.

Nothing here is a product feature and nothing is shipped; it is a build-time tool like the deck builder.
The films are **not committed**: they carry the product's private Arabic clips and the owner's footage.

## Build

```bash
uv run --no-project --with playwright==1.65.2 python -m playwright install chromium   # once
uv run --no-project --with-requirements submission/build/hook_video/requirements.txt \
  python submission/build/hook_video/build.py --out deliverables/hook_v2 \
  --clips data/private/voice/clips/ar_ae --footage deliverables/media/hook.mp4
```

Needs `ffmpeg` and `ffprobe`. Without `--footage` only the logo sting and the animation are built.
`--variants`, `--formats`, `--fps`, `--workers` narrow or speed up a build; `--no-align` skips word alignment.

| Output | What |
|---|---|
| `intro_logo_{portrait,landscape}.mp4` | the logo sting alone |
| `falcon_sequence_{portrait,landscape}.mp4` | the animation alone, no footage needed |
| `hook_final_{portrait,landscape}.mp4` | the cut that opens on the footage |
| `hook_final_*_keynote.mp4` | 720p, 30 fps copies under 15 MB for embedding in a deck |
| `storyboard.png`, `build_report.json` | contact sheet; lengths and the loudness reading of each cut |

## How it works

| File | Role |
|---|---|
| `cues.py` | The cue sheet: every spoken line, the cut list of the footage, fixture text, scene lengths. One source of truth for picture and sound. |
| `audio.py` | Places the real clips and the real earcon; synthesises the music and effects (numpy, scipy: sine, noise and additive voices, no samples); limits and brings the master to the loudness target. |
| `align.py` | Optional word timings from a local recogniser, so caption words light up as they are spoken. |
| `composition/` | The page. Every pixel is a function of time: `window.__seek(t)` draws the frame for `t`. No CSS animation, no timers. |
| `render.py` | Steps the page frame by frame in headless Chromium (Playwright), in parallel slices, and encodes with ffmpeg. |

The lens is the product's own instrument (`web/components/Lens.tsx`): tick ring, four tier arcs that fill as the
checks T0 to T3 finish, aperture blades, and the verdict icon when it locks. Colours and type are
`web/design/tokens.css` and the fonts in `web/public/fonts`.

## Rules the builder enforces (tests: `scripts/tests/test_hook_video.py`)

- The Falcon's captions are the product's own spoken lines, and the build refuses to run if the clip manifest
  says a clip speaks other words.
- Only the invented "Falcon Demo Bank" and defanged `[.]test` hosts appear. No real brand, number or live address.
- The verdict is «خطِر». The word for "harmless" appears nowhere. No score and no statistic is shown.
- «تمثيل — Dramatisation» is on every frame of a film. The competition is named once, in small type on the end
  card, next to the words "independent project, ready to connect, not connected". No police logo or insignia.
- The findings shown at each step are the product's finding lines for the fixture (`url.combosquat`, the brand
  claim, the card fields, `message.scam_intent`). Dir linking three reports is what the product says when an
  incident links them; in the film it is part of the dramatisation.
