# RegKnot video ads

The 45-second main ad and the two 15-second towing cuts ("First trip", "Audit coming"), built from
real screen captures of the live app plus motion graphics. Script: `docs/marketing/video-script-2026-09-27.md`
(the shared copy for Karynn is the Claude Doc "RegKnot video script").

Code lives here; the raw captures, prepared assets and renders live in `data/video/` (gitignored:
`raw/`, `assets/`, `out/`; `REGKNOT_VIDEO_DATA` overrides the location).

Every frame is a pure function of time. `stage/stage.html` lays out the scenes and `window.seek(t)` poses
them; `render.js` drives system Chrome through puppeteer-core, one screenshot per frame, into ffmpeg.
The score and sound effects are synthesized in `audio.py` from the event log the stage writes, so
cuts, taps and typing stay in sync when timings change.

## Files

| file | role |
|---|---|
| `prep.py` | Crops the raw 488x1055 captures to the 464x1003 app area, paints out the desktop scrollbar, stitches scroll positions into continuous strips, saves 2x assets. Leaves out the personal home-screen suggestions and the dossier's credentials. |
| `gen_data.py` | Picks real section titles from a read-only corpus sample for the "wall of regulations" shot (`stage/data.js`). |
| `stage/` | `stage.html`, `stage.css`, `stage.js` (all scenes, cuts and timings), `wide.html` (16:9 side panels). |
| `render.js` | `node render.js <cut> stills 1.2,3.6` for review PNGs, `events` for the audio event log, `video` for the silent MP4. |
| `audio.py` | Original score (D minor, 100 BPM main / 94 BPM cuts) plus UI sound effects, synced to the event log. |
| `finish.py` | Two-pass loudnorm to -14 LUFS, muxes the audio, builds the 16:9 versions and covers. |
| `wide.js`, `sheet.py`, `analyze_audio.py` | 16:9 background render, contact sheets, level and spectrum check. |

Cuts: `main` (45 s), `cutA` (15 s, first trip), `cutB` (15 s, audit).

## Run

Needs Node 22, Google Chrome, uv, and ffmpeg (`uv run --with imageio-ffmpeg python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"` prints a bundled one).

```bash
cd scripts/video
npm install
export FFMPEG=/path/to/ffmpeg
python prep.py                       # raw captures -> assets (once)
node render.js main events
uv run --with numpy --with scipy python audio.py main
node render.js main video
python finish.py main
```

## Adding Karynn's voice-over

Her lines are already on screen as captions, timed to the script. When her memo arrives:

1. Pick the best take of each line and trim it (`ffmpeg -ss … -to …`).
2. Clean it: `highpass=f=80, afftdn=nf=-25, acompressor=threshold=-20dB:ratio=3, loudnorm=I=-16`.
3. Place each line at its caption start in `stage.js` (the `caption(a, b, text)` calls) and nudge a caption if a read runs long.
4. Mix: music ducked about 8 dB under the voice with `sidechaincompress`, then the normal `finish.py` pass.

Her voice is only ever her own recording. No voice clone, no avatar.

## Rules the edit follows

- Every answer on screen is a real, unedited RegKnot answer recorded from the live app (M/V Bay Pioneer demo profile).
  Streaming is sped up, and the footage carries a "Real answer · sped up" label.
- Claims on screen were checked against the eCFR: 46 CFR 140.410 (orientation before first trip, ten topics,
  four log elements), 140.515(c) (training within 5 days), 140.915(a) (ten TVR items).
- The company-documents scene is an illustration of the shipped feature, not a screen capture.
