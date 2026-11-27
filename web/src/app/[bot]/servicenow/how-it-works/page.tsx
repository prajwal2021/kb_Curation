"use client";
import Link from "next/link";
import { Fragment, useRef, useState, type ReactNode } from "react";
import { Play, X } from "lucide-react";
import { useApi } from "@/lib/api";
import type { SnOverview, SnState } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Badge, Card, ErrorNote, Loading, Page, PageHeader, SnStateBadge, Tabs } from "@/components/ui";
import { cn } from "@/lib/utils";

type Step = { t: string; you?: boolean; who: string; d: ReactNode; see?: [string, string]; stat?: [ReactNode, string]; after?: ReactNode };
const day = (s: string) => new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const LIFE: { s: SnState; d: string; moves: string[]; by: string }[] = [
  { s: "draft", d: "Being written or edited. Not in To do, not in releases.", moves: ["Send for review →"], by: "Anyone who writes" },
  { s: "review", d: "Waiting for a reviewer in To do. AI suggestions start here.", moves: ["Publish →", "← Send back to draft"], by: "A reviewer" },
  { s: "published", d: "The approved article. Edit starts a new draft version; this one stays published meanwhile. Reaches the chatbot at the next release.", moves: ["Suggest retiring →"], by: "Anyone, or the AI" },
  { s: "pending_retirement", d: "Someone, or the AI, thinks it's out of date. Still published until a reviewer decides.", moves: ["Retire →", "← Keep published"], by: "A reviewer" },
  { s: "retired", d: "Out of use. Kept, and still in releases, labeled Retired.", moves: ["Restore (back to draft)"], by: "A reviewer" },
];

// A narrated two-minute tour (with captions). Files live in web/public/how-it-works.
const TOUR = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/how-it-works`;

function VideoTour() {
  const [open, setOpen] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="group mb-5 flex w-full items-center gap-4 rounded-2xl border border-line bg-white p-2.5 pr-5 text-left transition hover:border-neutral-300 hover:shadow-sm">
        <span className="relative block aspect-video w-44 shrink-0 overflow-hidden rounded-xl bg-neutral-100">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`${TOUR}/tour-poster.jpg`} alt="" className="size-full object-cover" />
          <span className="absolute inset-0 flex items-center justify-center bg-black/10 transition group-hover:bg-black/20">
            <span className="flex size-10 items-center justify-center rounded-full bg-white/95 shadow"><Play className="ml-0.5 size-4 fill-ink text-ink" /></span>
          </span>
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-ink">Watch the 2-minute tour</span>
          <span className="mt-0.5 block text-[13px] text-muted">From ServiceNow to the chatbot: web pages, AI suggestions, review and release. Narrated, with captions.</span>
        </span>
        <span className="ml-auto hidden shrink-0 text-xs font-medium text-ink sm:block">Play ▸</span>
      </button>
    );
  }
  return (
    <div className="mb-5 overflow-hidden rounded-2xl border border-line bg-black">
      <video ref={video} controls autoPlay playsInline preload="auto" poster={`${TOUR}/tour-poster.jpg`} className="aspect-video w-full"
        onLoadedMetadata={() => { const t = video.current?.textTracks[0]; if (t) t.mode = "showing"; }}>
        <source src={`${TOUR}/tour.mp4`} type="video/mp4" />
        <track kind="captions" src={`${TOUR}/tour.vtt`} srcLang="en" label="English" default />
      </video>
      <div className="flex items-center justify-between bg-white px-4 py-2 text-xs text-muted">
        <span>How KB Curation works · 2 min · captions on (turn them off in the player)</span>
        <button type="button" onClick={() => setOpen(false)} className="flex items-center gap-1 rounded-md px-2 py-1 font-medium text-ink hover:bg-neutral-100">
          <X className="size-3.5" /> Close
        </button>
      </div>
    </div>
  );
}

export default function SnHowItWorksPage() {
  const bot = useBot();
  const [tab, setTab] = useState<"big" | "life">("big");
  const o = useApi<SnOverview>(`/api/chatbots/${bot}/servicenow/overview`);
  const d = o.data;

  const steps: Step[] = d ? [
    { t: "ServiceNow articles", who: "Import, can run again", see: ["See them in Knowledge base", "/servicenow/kb"],
      d: "The help articles come from ServiceNow with their categories, state (draft, in review, published…) and flags (Internal only when there's no \"Public view\"). On a new import: changed only in ServiceNow, ServiceNow wins; changed only here, this app wins; changed in both, ServiceNow's version waits for a reviewer.",
      stat: d.import ? [d.import.articles, `imported ${day(d.import.at)}`] : ["—", "not imported yet"] },
    { t: "Link web pages", you: true, who: "You", see: ["See them in Web pages", "/servicenow/web-pages"],
      d: "Each category is linked to the TTU web pages its articles are based on.", stat: [d.links.total, "links watched"] },
    { t: "Scheduled check", who: "Automatic", d: "Each page is read again on its own schedule (set in Web pages, or checked by hand) and compared with the last time.",
      after: <p className="ml-11 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700">If a page can&apos;t be read, it shows in To do → Needs attention</p> },
    { t: "AI suggests a change", who: "Automatic",
      d: <>When a page changed, the AI reads what changed and suggests one of:
        <span className="mt-2 flex flex-wrap gap-1.5"><Badge tone="amber">A change, in review</Badge><Badge tone="amber">A new article, in review</Badge><Badge tone="red">Pending retirement</Badge></span></>,
      after: <p className="ml-11 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs text-indigo-700">Or a person writes or edits one in Knowledge base and sends it for review. It joins here.</p> },
    { t: "Review", you: true, who: "You", see: ["Happens in To do", "/servicenow"], stat: [d.waiting, "waiting now"],
      d: "Publish it or send it back to draft. For a retirement: retire it or keep it published. Nothing changes without this step." },
    { t: "Release", you: true, who: "You", see: ["Happens in Release", "/servicenow/publish"],
      stat: d.published ? [`v${d.published.number}`, `since ${day(d.published.created_at)}`] : ["—", "none yet"],
      d: "Saves a numbered version of the whole knowledge base, every article labeled with its state and flags. A published article reaches the chatbot only in the next release; until then it is \"Published, not released yet\"." },
    { t: "Chatbot answers", who: "Automatic",
      d: <>The chatbot reads the latest release and filters by label: for students and parents, only Published articles without Internal only. Or it takes <b>everything right now</b> (Knowledge base → More), each article labeled with its stage: Draft, In review, Published, not released yet, Released in vN, Pending retirement or Retired.</> },
  ] : [];

  return (
    <Page>
      <PageHeader title="How it works" description={tab === "big" ? "How an answer gets from ServiceNow to the chatbot, and where a person steps in." : "The same states as ServiceNow. Every article is in exactly one."} />
      <VideoTour />
      <Tabs className="mb-5" value={tab} onChange={setTab} items={[{ value: "big", label: "The big picture" }, { value: "life", label: "An article's life" }]} />
      {o.error && <ErrorNote>{o.error}</ErrorNote>}
      {tab === "big" ? (!d ? (!o.error && <Loading />) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
          <div>
            {steps.map((s, i) => (
              <Fragment key={s.t}>
                {i > 0 && <p className="ml-11 py-1 text-neutral-300">↓</p>}
                <Card className={cn("flex gap-3 p-4", s.you ? "border-ink" : "text-neutral-500")}>
                  <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold", s.you ? "bg-ink text-white" : "bg-neutral-100 text-neutral-500")}>{i + 1}</span>
                  <div className="min-w-0 flex-1 text-[13px]">
                    <p className={cn("font-semibold", s.you && "text-ink")}>{s.t} <span className="ml-1 text-xs font-normal text-muted">{s.who}</span></p>
                    <div className="mt-0.5">{s.d}</div>
                    {s.see && <Link href={`/${bot}${s.see[1]}`} className="mt-1.5 inline-block text-xs font-medium text-ink underline">{s.see[0]} →</Link>}
                  </div>
                  {s.stat && <div className="shrink-0 text-right"><p className="text-xl font-semibold tabular-nums text-ink">{s.stat[0]}</p><p className="text-xs text-muted">{s.stat[1]}</p></div>}
                </Card>
                {s.after && <div className="mt-2">{s.after}</div>}
              </Fragment>
            ))}
          </div>
          <div className="space-y-4 text-[13px]">
            <Card className="p-4">
              <p className="mb-2 font-semibold">Who does what</p>
              <p className="flex items-center gap-2"><span className="size-4 rounded-full bg-ink" /> A person does this step</p>
              <p className="mt-1 flex items-center gap-2"><span className="size-4 rounded-full bg-neutral-200" /> Happens on its own</p>
            </Card>
            <Card className="p-4">
              <p className="mb-1 font-semibold">Everything is recorded</p>
              Every step above, including who decided and why, is kept in <Link href={`/${bot}/history`} className="font-medium underline">History →</Link>
            </Card>
            <Card className="p-4">
              <p className="mb-1 font-semibold">Safe by design</p>
              The AI only suggests. Nothing changes until a person publishes it <b>and</b> releases a version. Every article is labeled, so the chatbot can leave out what students shouldn&apos;t see.
            </Card>
          </div>
        </div>
      )) : (
        <>
          <div className="grid gap-3 md:grid-cols-5">
            {LIFE.map((x) => (
              <Card key={x.s} className={cn("flex flex-col gap-2 p-3.5 text-[13px]", (x.s === "published" || x.s === "pending_retirement") && "border-green-300")}>
                <span><SnStateBadge status={x.s} /></span>
                <p className="flex-1">{x.d}</p>
                <div className="flex flex-col gap-1">{x.moves.map((m) => <span key={m} className="rounded-md bg-neutral-100 px-2 py-1 text-xs font-medium">{m}</span>)}</div>
                <p className="text-xs text-muted">{x.by}</p>
              </Card>
            ))}
            <p className="rounded-lg bg-green-50 px-3 py-2 text-center text-[13px] text-green-800 md:col-span-3 md:col-start-3">⬆ In every <b>Release</b>, labeled with state and flags. Draft and In review stay out.</p>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Card className="p-4 text-[13px] leading-relaxed">
              <p className="mb-1.5 text-sm font-semibold">Flags</p>
              <p><Badge tone="violet">Internal only</Badge> For staff, not students or parents. Set on import when ServiceNow has no &quot;Public view&quot; (for example K12 Agents only). A reviewer can change it.</p>
              <p className="mt-1.5">Only one flag today. Anyone can add a new one from an article&apos;s Flags checklist, and it&apos;s then there for every article. Flags go into every release after the state.</p>
            </Card>
            <Card className="p-4 text-[13px] leading-relaxed">
              <p className="mb-1.5 text-sm font-semibold">One article, many versions</p>
              <p>ServiceNow keeps each version as its own record. Here, one article keeps one KB number instead, which stops the duplicates.</p>
              <p className="mt-2 text-muted">The import keeps the newest published version as the article. A newer draft or in-review version waits on it as a change, like an edit made here. After that, every Release keeps a full copy of each article.</p>
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}
