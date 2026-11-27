import React from "react";
import { registerRoot, Composition, AbsoluteFill, Sequence, Audio, Img, staticFile, useCurrentFrame, useVideoConfig, interpolate, Easing, spring } from "remotion";
import TL from "./timeline.json";
import BOXES from "./boxes.json";

const FPS = TL.fps;
const LEAD = 0.5;
const INK = "#0a0a0a", MUTED = "#737373", LINE = "#e5e5e5", ACCENT = "#7c3aed";
const FONT = 'Inter, -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif';
const ease = Easing.bezier(0.33, 0, 0.2, 1);
const sec = (f) => f / FPS;
const fade = (t, a, b, d = 0.35) => interpolate(t, [a, a + d, b - d, b], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
const appear = (t, a, d = 0.45) => interpolate(t, [a, a + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
const S = Object.fromEntries(TL.scenes.map((s) => [s.id, s]));
const cue = (id, name) => S[id].cues[name];

// ── screen geometry: screenshots are 1600×900 CSS px (captured at 2×) ─────────────────────────
const W = 1600, H = 900;
const WIN = { x: 150, y: 120, w: 1620, h: 911 + 40 };   // window incl. 40px title bar
const K = WIN.w / W;                                  // css px → video px

const box = (name, pad = 0) => { const b = BOXES[name]; return { x: b.x - pad, y: b.y - pad, w: b.width + pad * 2, h: b.height + pad * 2 }; };
const rect = (x, y, w, h) => ({ x, y, w, h });

function camAt(b, maxZoom = 1.9) {
  if (!b) return { z: 1, tx: 0, ty: 0 };
  const z = Math.max(1, Math.min(maxZoom, (W * 0.86) / b.w, (H * 0.8) / b.h));
  const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
  const tx = Math.min(0, Math.max(W - W * z, W / 2 - cx * z));
  const ty = Math.min(0, Math.max(H - H * z, H / 2 - cy * z));
  return { z, tx, ty };
}
// keys: [{t, box, zoom}] — camera moves to each key over `d` seconds starting at t
function camera(t, keys, d = 1.0) {
  let cur = camAt(null);
  for (const k of keys) {
    const target = camAt(k.box, k.zoom);
    const p = interpolate(t, [k.t, k.t + d], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
    if (p <= 0) break;
    cur = { z: cur.z + (target.z - cur.z) * p, tx: cur.tx + (target.tx - cur.tx) * p, ty: cur.ty + (target.ty - cur.ty) * p };
  }
  return cur;
}

function Ring({ t, b, from, to, spot = true, label }) {
  const o = fade(t, from, to, 0.3);
  if (o <= 0) return null;
  const pulse = 1 + 0.04 * Math.sin((t - from) * 5);
  return (
    <div style={{ position: "absolute", left: b.x - 6, top: b.y - 6, width: b.w + 12, height: b.h + 12, borderRadius: 12, opacity: o,
      border: `3px solid ${ACCENT}`, boxShadow: `0 0 0 ${6 * pulse}px rgba(124,58,237,.18)${spot ? ", 0 0 0 4000px rgba(15,15,20,.28)" : ""}` }}>
      {label && <div style={{ position: "absolute", left: -3, top: -34, background: ACCENT, color: "#fff", font: `600 15px ${FONT}`, padding: "5px 10px", borderRadius: 8, whiteSpace: "nowrap" }}>{label}</div>}
    </div>
  );
}

function Cursor({ t, path }) {
  // path: {t0, t1, from:[x,y], to:[x,y], click}
  const p = interpolate(t, [path.t0, path.t1], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const o = fade(t, path.t0 - 0.2, path.click + 0.9, 0.2);
  if (o <= 0) return null;
  const x = path.from[0] + (path.to[0] - path.from[0]) * p, y = path.from[1] + (path.to[1] - path.from[1]) * p;
  const c = t - path.click;
  const press = c > 0 && c < 0.25 ? 0.85 : 1;
  return (
    <>
      {c > 0 && c < 0.7 && <div style={{ position: "absolute", left: x - 30, top: y - 30, width: 60, height: 60, borderRadius: 30, border: `3px solid ${ACCENT}`,
        opacity: 1 - c / 0.7, transform: `scale(${0.4 + c * 1.6})` }} />}
      <svg width="30" height="36" viewBox="0 0 24 28" style={{ position: "absolute", left: x - 3, top: y - 2, opacity: o, transform: `scale(${press})`, transformOrigin: "3px 2px", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))" }}>
        <path d="M2 1 L2 22 L7.5 16.8 L11.2 25.5 L14.8 24 L11.2 15.5 L18.5 15.5 Z" fill="#111" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    </>
  );
}

// a screenshot inside the window, with camera, rings and cursor drawn in screenshot coordinates
function Screen({ t, shots, keys, rings = [], cursor, children }) {
  const cam = camera(t, keys);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#fff" }}>
      <div style={{ position: "absolute", width: W, height: H, transformOrigin: "0 0", transform: `scale(${K}) translate(${cam.tx}px, ${cam.ty}px) scale(${cam.z})` }}>
        {shots.map((s, i) => (
          <Img key={s.src} src={staticFile(s.src)} style={{ position: "absolute", width: W, height: H, opacity: i === 0 ? 1 : appear(t, s.at, 0.35) }} />
        ))}
        {rings.map((r, i) => <Ring key={i} t={t} {...r} />)}
        {cursor && <Cursor t={t} path={cursor} />}
      </div>
      {children}
    </AbsoluteFill>
  );
}

function Window({ children, url, opacity, lift }) {
  return (
    <div style={{ position: "absolute", left: WIN.x, top: WIN.y + lift, width: WIN.w, height: WIN.h, borderRadius: 16, overflow: "hidden", opacity,
      background: "#fff", boxShadow: "0 30px 80px rgba(0,0,0,.18), 0 0 0 1px rgba(0,0,0,.08)" }}>
      <div style={{ height: 40, background: "#f6f6f5", borderBottom: `1px solid ${LINE}`, display: "flex", alignItems: "center", padding: "0 16px", gap: 8 }}>
        {["#ff5f57", "#febc2e", "#28c840"].map((c) => <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />)}
        <div style={{ margin: "0 auto", background: "#fff", border: `1px solid ${LINE}`, borderRadius: 8, padding: "4px 18px", font: `500 14px ${FONT}`, color: MUTED, minWidth: 520, textAlign: "center" }}>{url}</div>
        <div style={{ width: 52 }} />
      </div>
      <div style={{ position: "absolute", left: 0, top: 40, width: WIN.w, height: WIN.h - 40 }}>{children}</div>
    </div>
  );
}

function StepTag({ t, n, title }) {
  const o = appear(t, 0.1, 0.5);
  return (
    <div style={{ position: "absolute", left: WIN.x, top: 44, display: "flex", alignItems: "center", gap: 14, opacity: o, transform: `translateY(${(1 - o) * 12}px)` }}>
      {n && <div style={{ width: 40, height: 40, borderRadius: 20, background: INK, color: "#fff", font: `700 19px ${FONT}`, display: "grid", placeItems: "center" }}>{n}</div>}
      <div style={{ font: `650 30px ${FONT}`, color: INK, letterSpacing: -0.4 }}>{title}</div>
    </div>
  );
}

const Chip = ({ children, bg, fg, style }) => <span style={{ background: bg, color: fg, borderRadius: 999, padding: "7px 16px", font: `600 20px ${FONT}`, whiteSpace: "nowrap", ...style }}>{children}</span>;

// ── scenes (t = seconds since the scene started) ──────────────────────────────────────────
const SCENES = {
  import: { n: 1, title: "Articles come in from ServiceNow", url: "kb-curation › TTU K-12 › Knowledge base",
    render: (t) => <Screen t={t} shots={[{ src: "kb.png" }]}
      keys={[{ t: cue("import", "tabs") - 0.4, box: box("kb.tabs", 30), zoom: 1.8 }, { t: cue("import", "internal") - 0.6, box: rect(560, 690, 860, 140), zoom: 1.7 }, { t: cue("import", "out") + 1.2, box: null }]}
      rings={[{ b: box("kb.tabs", 2), from: cue("import", "tabs"), to: cue("import", "internal") - 0.6, label: "Same states as ServiceNow" },
              { b: box("kb.internal", 3), from: cue("import", "internal") + 0.3, to: cue("import", "out") + 1.4, label: "Staff only" }]} /> },
  webpages: { n: 2, title: "Each category watches its TTU web pages", url: "kb-curation › TTU K-12 › Web pages",
    render: (t) => <Screen t={t} shots={[{ src: "webpages.png" }]}
      keys={[{ t: cue("webpages", "chips") - 0.5, box: rect(320, 225, 1060, 90), zoom: 1.6 }, { t: cue("webpages", "ok") - 0.5, box: box("wp.ok", 20), zoom: 1.5 }, { t: cue("webpages", "ai") - 0.4, box: null }]}
      rings={[{ b: rect(324, 230, 1052, 80), from: cue("webpages", "chips"), to: cue("webpages", "ok") - 0.5, label: "Page → the categories it keeps up to date" },
              { b: box("wp.ok", 0), from: cue("webpages", "ok"), to: cue("webpages", "ai") - 0.3, label: "Checked on a schedule" }]}>
      <AiCard t={t - cue("webpages", "ai")} />
    </Screen> },
  todo: { n: 3, title: "To do: everything that needs a person", url: "kb-curation › TTU K-12 › To do",
    render: (t) => <Screen t={t} shots={[{ src: "todo.png" }]}
      keys={[{ t: cue("todo", "row") - 0.3, box: box("todo.row", 40), zoom: 1.6 }]}
      rings={[{ b: box("todo.badge", 8), from: cue("todo", "badge") - 0.2, to: cue("todo", "row"), spot: false },
              { b: box("todo.row", 0), from: cue("todo", "row") + 0.2, to: 99, label: "Suggested by the AI" }]} /> },
  article: { n: 4, title: "A person reviews every change", url: "kb-curation › TTU K-12 › Article",
    render: (t) => {
      const click = cue("article", "click") + 0.6, pb = box("art.publish");
      return <Screen t={t} shots={[{ src: "article.png" }, { src: "article-published.png", at: click + 0.15 }]}
        keys={[{ t: cue("article", "reason") - 0.4, box: box("art.reason", 20), zoom: 1.5 }, { t: cue("article", "diff") - 0.4, box: rect(296, 538, 640, 40), zoom: 1.9 },
               { t: cue("article", "click") - 1.0, box: rect(820, 660, 460, 120), zoom: 1.6 }, { t: cue("article", "state") - 0.6, box: rect(1290, 60, 290, 120), zoom: 1.7 }]}
        rings={[{ b: box("art.reason", 2), from: cue("article", "reason"), to: cue("article", "diff") - 0.4, label: "Why, and which web page" },
                { b: rect(298, 541, 640, 34), from: cue("article", "diff"), to: cue("article", "click") - 1.0, label: "Exactly what changed" },
                { b: box("art.state2", 6), from: cue("article", "state"), to: 99, label: "Live the whole time" }]}
        cursor={{ t0: cue("article", "click") - 0.6, t1: click - 0.1, click, from: [900, 840], to: [pb.x + pb.w / 2 - 8, pb.y + pb.h / 2] }} />;
    } },
  release: { n: 5, title: "Release: what the chatbot reads", url: "kb-curation › TTU K-12 › Release",
    render: (t) => {
      const click = cue("release", "click") + 0.5, rb = box("rel.button");
      return <Screen t={t} shots={[{ src: "release.png" }, { src: "release-done.png", at: click + 0.15 }]}
        keys={[{ t: cue("release", "next") - 0.5, box: box("rel.next", 20), zoom: 1.6 }, { t: cue("release", "history") - 0.5, box: box("rel.history", 30), zoom: 1.6 }, { t: cue("release", "filter") - 0.2, box: null }]}
        rings={[{ b: box("rel.next", 2), from: cue("release", "next"), to: click, spot: false },
                { b: box("rel.history", 2), from: cue("release", "history"), to: cue("release", "filter") - 0.2, label: "Numbered versions" }]}
        cursor={{ t0: cue("release", "click") - 0.7, t1: click - 0.1, click, from: [1000, 700], to: [rb.x + rb.w / 2, rb.y + rb.h / 2] }}>
        <FilterCard t={t - cue("release", "filter")} />
      </Screen>;
    } },
  history: { n: null, title: "History and access", url: "kb-curation › TTU K-12 › History",
    render: (t) => <Screen t={t} shots={[{ src: "history.png" }, { src: "users.png", at: cue("history", "users") - 0.3 }]}
      keys={[{ t: cue("history", "list") - 0.6, box: box("hist.list", 40), zoom: 1.6 }, { t: cue("history", "users") - 0.4, box: box("users.table", 40), zoom: 1.5 }]}
      rings={[{ b: box("hist.list", 2), from: cue("history", "list"), to: cue("history", "users") - 0.4, label: "Who decided, and when" },
              { b: box("users.table", 2), from: cue("history", "users") + 0.4, to: 99, label: "Admins choose who opens each KB" }]} /> },
};

function AiCard({ t }) {
  if (t < 0) return null;
  const o = appear(t, 0, 0.5);
  const chips = [["A change, in review", "#fff7ed", "#c2410c"], ["A new article, in review", "#fff7ed", "#c2410c"], ["Pending retirement", "#fef2f2", "#b91c1c"]];
  return (
    <div style={{ position: "absolute", right: 60, bottom: 60, width: 760, background: "#fff", borderRadius: 20, padding: "28px 32px", opacity: o, transform: `translateY(${(1 - o) * 30}px)`,
      boxShadow: "0 24px 60px rgba(0,0,0,.22), 0 0 0 1px rgba(0,0,0,.06)", font: `400 20px ${FONT}`, color: INK }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
        <div style={{ width: 38, height: 38, borderRadius: 10, background: "#f3e8ff", color: ACCENT, display: "grid", placeItems: "center", font: `700 18px ${FONT}` }}>AI</div>
        <div style={{ font: `650 24px ${FONT}` }}>A page changed. The AI suggests one of:</div>
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {chips.map(([l, bg, fg], i) => <Chip key={l} bg={bg} fg={fg} style={{ opacity: appear(t, 0.5 + i * 0.35), transform: `scale(${0.9 + 0.1 * appear(t, 0.5 + i * 0.35)})` }}>{l}</Chip>)}
      </div>
      <div style={{ marginTop: 18, color: MUTED, fontSize: 18, opacity: appear(t, 1.8) }}>Every suggestion waits for a person in To do.</div>
    </div>
  );
}

function FilterCard({ t }) {
  if (t < 0) return null;
  const o = appear(t, 0, 0.5);
  const rows = [["Refund policy", ["Published"], true], ["District partnership FAQ", ["Published", "Internal only"], false], ["Blackboard login", ["Retired"], false], ["Office hours and contact", ["Published"], true]];
  const tone = { Published: ["#ecfdf5", "#047857"], "Internal only": ["#f5f3ff", "#6d28d9"], Retired: ["#f5f5f4", "#57534e"] };
  return (
    <div style={{ position: "absolute", inset: 0, background: `rgba(250,250,249,${0.92 * o})`, display: "grid", placeItems: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 40, opacity: o, transform: `scale(${0.96 + 0.04 * o})` }}>
        <div style={{ width: 620, background: "#fff", borderRadius: 20, padding: 26, boxShadow: "0 20px 50px rgba(0,0,0,.12), 0 0 0 1px rgba(0,0,0,.06)" }}>
          <div style={{ font: `650 22px ${FONT}`, color: INK, marginBottom: 16 }}>Release v2 · every article labeled</div>
          {rows.map(([title, labels, keep], i) => {
            const dim = interpolate(t, [3.2, 3.8], [1, keep ? 1 : 0.28], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
            return (
              <div key={title} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 4px", borderTop: i ? `1px solid ${LINE}` : "none", opacity: appear(t, 0.3 + i * 0.25) * dim }}>
                <span style={{ font: `500 21px ${FONT}`, color: INK }}>{title}</span>
                <span style={{ display: "flex", gap: 8 }}>{labels.map((l) => <Chip key={l} bg={tone[l][0]} fg={tone[l][1]} style={{ fontSize: 16, padding: "5px 12px" }}>{l}</Chip>)}</span>
              </div>
            );
          })}
        </div>
        <svg width="90" height="40" style={{ opacity: appear(t, 2.4) }}><path d="M4 20 H78 M62 6 L80 20 L62 34" stroke={INK} strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
        <div style={{ width: 380, background: INK, color: "#fff", borderRadius: 20, padding: 28, opacity: appear(t, 2.6), transform: `translateX(${(1 - appear(t, 2.6)) * 20}px)` }}>
          <div style={{ font: `650 24px ${FONT}`, marginBottom: 10 }}>Chatbot for students and parents</div>
          <div style={{ font: `400 19px ${FONT}`, color: "#d4d4d4", lineHeight: 1.45 }}>Uses <b style={{ color: "#fff" }}>Published</b> articles<br />without <b style={{ color: "#fff" }}>Internal only</b>.</div>
        </div>
      </div>
    </div>
  );
}

// ── intro and outro ──────────────────────────────────────────────────────────────────────
function Node({ title, sub, icon, o, highlight }) {
  return (
    <div style={{ width: 360, padding: "30px 28px", borderRadius: 22, background: highlight ? INK : "#fff", color: highlight ? "#fff" : INK, opacity: o, transform: `translateY(${(1 - o) * 24}px)`,
      boxShadow: "0 20px 50px rgba(0,0,0,.10), 0 0 0 1px rgba(0,0,0,.07)" }}>
      <div style={{ font: `700 34px ${FONT}`, marginBottom: 8 }}>{icon}</div>
      <div style={{ font: `650 30px ${FONT}`, letterSpacing: -0.4 }}>{title}</div>
      <div style={{ font: `400 20px ${FONT}`, color: highlight ? "#d4d4d4" : MUTED, marginTop: 6 }}>{sub}</div>
    </div>
  );
}
const Arrow = ({ o }) => <svg width="110" height="40" style={{ opacity: o }}><path d={`M6 20 H${6 + 90 * o} M84 6 L100 20 L84 34`} stroke="#a3a3a3" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>;

function Intro({ t }) {
  const title = fade(t, 0, cue("intro", "person") + 0.2, 0.5);
  const d = (x) => appear(t, x, 0.6);
  const diagramIn = cue("intro", "person");
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ position: "absolute", textAlign: "center", opacity: title, transform: `scale(${0.96 + 0.04 * appear(t, 0, 0.8)})` }}>
        <div style={{ font: `750 120px ${FONT}`, letterSpacing: -4, color: INK }}>KB Curation</div>
        <div style={{ font: `400 34px ${FONT}`, color: MUTED, marginTop: 10, opacity: appear(t, 1.6) }}>Accurate answers for our chatbots, approved by a person.</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 18, opacity: appear(t, diagramIn + 0.2) }}>
        <Node icon="▤" title="ServiceNow" sub="Help articles" o={d(diagramIn + 0.3)} />
        <Arrow o={d(diagramIn + 0.9)} />
        <Node icon="✓" title="KB Curation" sub="A person approves every change" o={d(diagramIn + 1.2)} highlight />
        <Arrow o={d(cue("intro", "bot") - 0.3)} />
        <Node icon="◉" title="Chatbot" sub="K-12 and TTU Online" o={d(cue("intro", "bot"))} />
      </div>
    </AbsoluteFill>
  );
}

function Outro({ t }) {
  const steps = ["Import", "Watch", "Suggest", "Review", "Release"];
  const end = cue("outro", "end");
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 60 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {steps.map((s, i) => {
          const o = appear(t, cue("outro", `s${i}`) - 0.1, 0.35);
          const on = s === "Review";
          return (
            <React.Fragment key={s}>
              {i > 0 && <div style={{ width: 40, height: 4, borderRadius: 2, background: "#d4d4d4", opacity: o }} />}
              <div style={{ padding: "18px 30px", borderRadius: 999, background: on ? INK : "#fff", color: on ? "#fff" : INK, font: `650 34px ${FONT}`, opacity: o, transform: `scale(${0.85 + 0.15 * o})`,
                boxShadow: "0 12px 30px rgba(0,0,0,.08), 0 0 0 1px rgba(0,0,0,.07)" }}>{s}</div>
            </React.Fragment>
          );
        })}
      </div>
      <div style={{ textAlign: "center", opacity: appear(t, end), transform: `translateY(${(1 - appear(t, end)) * 16}px)` }}>
        <div style={{ font: `750 84px ${FONT}`, letterSpacing: -3, color: INK }}>KB Curation</div>
        <div style={{ font: `400 28px ${FONT}`, color: MUTED, marginTop: 8 }}>The AI suggests. A person decides.</div>
      </div>
    </AbsoluteFill>
  );
}

// ── main ─────────────────────────────────────────────────────────────────────────────────
function Tour() {
  const frame = useCurrentFrame();
  const T = sec(frame);
  const winStart = S.import.from, winEnd = S.outro.from;
  const winO = fade(T, winStart - 0.1, winEnd + 0.3, 0.55);
  const lift = (1 - appear(T, winStart - 0.1, 0.7)) * 40;
  const active = TL.scenes.find((s) => T >= s.from && T < s.from + s.dur) || TL.scenes[TL.scenes.length - 1];
  return (
    <AbsoluteFill style={{ background: "radial-gradient(1200px 700px at 50% 30%, #ffffff 0%, #f4f4f2 60%, #ecebe8 100%)", fontFamily: FONT }}>
      {TL.scenes.map((s) => (
        <Sequence key={s.id} from={Math.round((s.from + LEAD) * FPS)} durationInFrames={Math.round((s.dur - LEAD) * FPS)}>
          <Audio src={staticFile(s.audio)} />
        </Sequence>
      ))}
      <Sequence from={0} durationInFrames={Math.round(S.intro.dur * FPS) + 10}><IntroWrap /></Sequence>
      {winO > 0 && (
        <Window url={SCENES[active.id]?.url || SCENES.history.url} opacity={winO} lift={lift}>
          {TL.scenes.filter((s) => SCENES[s.id]).map((s) => (
            <Sequence key={s.id} from={Math.round(s.from * FPS)} durationInFrames={Math.round(s.dur * FPS) + 12} layout="none">
              <SceneLayer id={s.id} />
            </Sequence>
          ))}
        </Window>
      )}
      {TL.scenes.filter((s) => SCENES[s.id]).map((s) => (
        <Sequence key={"tag" + s.id} from={Math.round(s.from * FPS)} durationInFrames={Math.round(s.dur * FPS)}>
          <TagWrap id={s.id} />
        </Sequence>
      ))}
      <Sequence from={Math.round(S.outro.from * FPS)}><OutroWrap /></Sequence>
    </AbsoluteFill>
  );
}
const IntroWrap = () => { const f = useCurrentFrame(); const t = sec(f); return <AbsoluteFill style={{ opacity: 1 - appear(t, S.intro.dur - 0.4, 0.5) }}><Intro t={t} /></AbsoluteFill>; };
const OutroWrap = () => { const t = sec(useCurrentFrame()); return <AbsoluteFill style={{ opacity: appear(t, 0.1, 0.5) }}><Outro t={t} /></AbsoluteFill>; };
const TagWrap = ({ id }) => { const t = sec(useCurrentFrame()); const sc = SCENES[id]; const out = 1 - appear(t, S[id].dur - 0.35, 0.3); return <div style={{ opacity: out }}><StepTag t={t} n={sc.n} title={sc.title} /></div>; };
const SceneLayer = ({ id }) => {
  const t = sec(useCurrentFrame());
  const o = appear(t, 0, 0.4);
  return <AbsoluteFill style={{ opacity: o }}>{SCENES[id].render(t)}</AbsoluteFill>;
};

const Root = () => (
  <Composition id="Tour" component={Tour} durationInFrames={Math.ceil(TL.total * FPS)} fps={FPS} width={1920} height={1080} />
);
registerRoot(Root);
