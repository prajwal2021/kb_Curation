import json, re
A = "build/audio"
FPS = 30
LEAD, TAIL = 0.5, 0.7          # silence before/after each scene's narration
scenes = json.load(open("script.json"))
cues = {   # phrase -> cue name, per scene
 "import": {"its state": "tabs", "Internal only": "internal", "students or parents": "out"},
 "webpages": {"linked to the TTU": "chips", "checked on a schedule": "ok", "the AI reads": "ai"},
 "todo": {"lands in To do": "badge", "changes waiting": "row"},
 "article": {"why it was suggested": "reason", "exactly what changed": "diff", "publishes it": "click", "never takes it offline": "state"},
 "release": {"release a version": "next", "numbered snapshot": "click", "labeled with": "history", "The chatbot reads": "filter"},
 "history": {"kept in History": "list", "admins choose": "users"},
 "outro": {"Import.": "s0", "Watch.": "s1", "Suggest.": "s2", "Review.": "s3", "Release.": "s4", "That's": "end"},
 "intro": {"ServiceNow": "sn", "to the chatbot": "bot", "a person approves": "person"},
}
out, vtt, t0 = [], ["WEBVTT", ""], 0.0
def ts(s): h=int(s//3600); m=int(s%3600//60); return f"{h:02d}:{m:02d}:{s%60:06.3f}"
for s in scenes:
    al = json.load(open(f"{A}/{s['id']}.align.json"))
    chars, st, en = al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]
    text = "".join(chars)
    dur = en[-1] + LEAD + TAIL
    c = {}
    for phrase, name in cues.get(s["id"], {}).items():
        i = text.find(phrase); assert i >= 0, (s["id"], phrase)
        c[name] = round(LEAD + st[i], 3)
    out.append({"id": s["id"], "audio": f"{s['id']}.mp3", "from": round(t0, 3), "dur": round(dur, 3), "cues": c})
    # captions: split into sentence-ish chunks of <= 70 chars (two lines of ~35)
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    chunk = []
    def flush():
        if not chunk: return
        a, b = chunk[0][0], chunk[-1][1]
        vtt.extend([f"{ts(t0+LEAD+st[a])} --> {ts(t0+LEAD+en[b-1]+0.25)}", text[a:b], ""]); chunk.clear()
    for w in words:
        cand = text[(chunk[0][0] if chunk else w[0]):w[1]]
        if chunk and len(cand) > 70: flush()
        chunk.append(w)
        if text[w[1]-1] in ".:?" or (text[w[1]-1] == "," and len(text[chunk[0][0]:w[1]]) > 40): flush()
    flush()
    t0 += dur
json.dump({"fps": FPS, "total": round(t0, 3), "scenes": out}, open("src/timeline.json", "w"), indent=1)
open("build/tour.vtt", "w").write("\n".join(vtt))
print("total", round(t0, 1), "s"); [print(x["id"], x["from"], x["dur"], x["cues"]) for x in out]

# captions must not overlap: end each cue just before the next one starts
L = open("build/tour.vtt").read().split("\n")
sec = lambda s: (lambda h, m, x: int(h) * 3600 + int(m) * 60 + float(x))(*s.split(":"))
idx = [i for i, l in enumerate(L) if "-->" in l]
for a, b in zip(idx, idx[1:]):
    s1, e1 = L[a].split(" --> "); s2 = L[b].split(" --> ")[0]
    if sec(e1) > sec(s2) - 0.04: L[a] = f"{s1} --> {ts(sec(s2) - 0.04)}"
open("build/tour.vtt", "w").write("\n".join(L))
