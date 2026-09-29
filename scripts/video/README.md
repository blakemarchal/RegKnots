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
| `finish.py` | Two-pass loudnorm to -14 LUFS, muxes the audio, builds the 16:9 versions, covers and small share copies (`out/share/`). `--vo <voice>` for the voiced versions. |
| `vo.py`, `vo_tts_remote.py`, `mix_vo.py` | Temp AI narration: generate the lines, split them at Whisper word times onto the caption timeline, duck the music under them (next section). |
| `wide.js`, `sheet.py`, `analyze_audio.py`, `motion.py` | 16:9 background render, contact sheets, level and spectrum check, one-frame glitch scan. |

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

## Temp AI narration (until Karynn records)

A stock OpenAI voice (`gpt-4o-mini-tts`: `marin` female, `cedar` male), never Karynn's. Her line 6 is read
in the third person ("Built by Captain Karynn Marchal…") so the synthetic voice never claims to be her, and
the end card says "Narration: AI voice". The 15 s cuts read their on-screen text.

```bash
python vo.py requests                                # lines not yet in data/video/vo/cache/
# where a working OPENAI_API_KEY lives (the local .env key is stale; prod's works):
python vo_tts_remote.py requests.json OUT ENV        # TTS + a Whisper transcript of each line
python vo_tts_remote.py --words WAV_DIR words.json ENV   # word times, for exact splits
# copy the wavs into data/video/vo/cache/ and words.json into data/video/vo/, then per cut and voice:
python vo.py build main marin                        # VO track + caption timings (data/video/vo/main_marin.js)
node render.js main events --vo marin
uv run --with numpy --with scipy python audio.py main marin    # effects on consonants soften under the voice
uv run --with numpy --with scipy python mix_vo.py main marin   # music ducks 10 dB, voice 10 dB over the bed
node render.js main video --vo marin
python finish.py main --vo marin
```

Each line is generated whole, split between words (only audio that is actually silent is removed), and
each piece starts at its caption's time; captions are retimed to the speech. Check the result by
transcribing the finished mix with Whisper: every line should come back word for word over the music.
Cost for all 34 lines in both voices plus the checks: about $0.05.

## Adding Karynn's voice-over

Her lines are already on screen as captions, timed to the script. When her memo arrives:

1. Pick the best take of each line and trim it (`ffmpeg -ss … -to …`).
2. Clean it: `highpass=f=80, afftdn=nf=-25, acompressor=threshold=-20dB:ratio=3, loudnorm=I=-16`.
3. Drop each line into `data/video/vo/cache/` in place of the AI take (or build the track with the same
   `vo.py build` placement), restore line 6 to her first-person read, and drop the "Narration: AI voice" note.
4. Mix with `mix_vo.py`, then the normal `finish.py --vo` pass.

Her voice is only ever her own recording. No voice clone, no avatar.

## Rules the edit follows

- Every answer on screen is a real, unedited RegKnot answer recorded from the live app (M/V Bay Pioneer demo profile).
  Streaming is sped up, and the footage carries a "Real answer · sped up" label.
- Claims on screen were checked against the eCFR: 46 CFR 140.410 (orientation before first trip, ten topics,
  four log elements), 140.515(c) (training within 5 days), 140.915(a) (ten TVR items).
- The company-documents scene is an illustration of the shipped feature, not a screen capture.
