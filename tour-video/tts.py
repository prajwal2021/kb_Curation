"""Narration: one MP3 per scene + character timings, from ElevenLabs. Needs ELEVENLABS_API_KEY.
python3 tts.py   →  build/audio/<scene>.mp3 and <scene>.align.json"""
import json, base64, os, urllib.request
key = os.environ["ELEVENLABS_API_KEY"]
VOICE = "XrExE9yKIg1WjnnlVkGX"  # Matilda (knowledgeable, professional)
out = "build/audio"; os.makedirs(out, exist_ok=True)
scenes = json.load(open("script.json"))
for i, s in enumerate(scenes):
    body = {"text": s["text"], "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15, "use_speaker_boost": True, "speed": 1.0},
            "previous_text": scenes[i-1]["text"] if i else None, "next_text": scenes[i+1]["text"] if i + 1 < len(scenes) else None}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps?output_format=mp3_44100_192",
                                 data=json.dumps(body).encode(), headers={"xi-api-key": key, "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=120))
    open(f"{out}/{s['id']}.mp3", "wb").write(base64.b64decode(d["audio_base64"]))
    json.dump(d["normalized_alignment"] or d["alignment"], open(f"{out}/{s['id']}.align.json", "w"))
    print(s["id"], round(d["alignment"]["character_end_times_seconds"][-1], 2), "s")
