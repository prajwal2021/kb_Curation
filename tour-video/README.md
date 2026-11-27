# Tour video (How it works)

The narrated two-minute tour that plays on **How it works**. The finished files are in
`web/public/how-it-works/` (`tour.mp4`, `tour.vtt` captions, `tour-poster.jpg`). This folder only rebuilds them, for
example after the screens change.

| File | What it does |
|---|---|
| `script.json` | The narration, one entry per scene. |
| `tts.py` | Reads each scene with ElevenLabs (voice Matilda) and saves the audio plus word timings. Needs `ELEVENLABS_API_KEY`. |
| `timeline.py` | Turns the timings into scene lengths, cue points (when a highlight or click happens) and the captions file. |
| `capture.mjs` | Signs in to a local copy of the app and screenshots each screen at 2× (and records where the buttons are). |
| `src/index.jsx` | The Remotion video: app window, camera moves, highlights, cursor clicks, intro and outro. |

## Rebuild

Record against a **local copy** of the app, never the live server: the capture clicks Publish and Release.

1. Run the app locally on a copy of the server database (`pg_dump` on the server, load it locally), API on 8010 and
   `next build && next start -p 3010` (a production build, so the dev badge isn't in the pictures).
2. In that copy, create a reviewer account and stage the example AI suggestion the article scene shows (article 647,
   K-12 contact page, office hours 8:00am – 5:00pm Central Time). Sign in once with Playwright and save the session
   to `build/state.json`.
3. Then:

```bash
cd tour-video && npm install && npx playwright install chromium
mkdir -p build public
node capture.mjs                                      # screenshots → public/, positions → src/boxes.json
ELEVENLABS_API_KEY=… python3 tts.py && cp build/audio/*.mp3 public/
python3 timeline.py                                   # src/timeline.json + build/tour.vtt
npx remotion still src/index.jsx Tour build/check.png --frame=1900   # spot-check a frame
npm run render
ffmpeg -i build/tour-raw.mp4 -c:v libx264 -preset slow -crf 25 -pix_fmt yuv420p -tune stillimage \
  -af loudnorm=I=-16:TP=-1.5:LRA=11 -c:a aac -b:a 128k -movflags +faststart ../web/public/how-it-works/tour.mp4
cp build/tour.vtt ../web/public/how-it-works/tour.vtt
ffmpeg -ss 64.2 -i ../web/public/how-it-works/tour.mp4 -frames:v 1 -vf scale=1280:-2 -q:v 3 ../web/public/how-it-works/tour-poster.jpg
```

Changing only the words: edit `script.json`, run `tts.py` and `timeline.py`, render. Cue phrases in `timeline.py` must
still appear in the narration.
