"use client";
import { ChevronDown, ChevronRight, MoreHorizontal, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { API, useApi } from "@/lib/api";
import { SN_STATE, type SnArticle, type SnCategory, type SnState, type SnVersion } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorNote, inputCls, Loading, Page, PageHeader, Tabs } from "@/components/ui";
import { ago, cn } from "@/lib/utils";

type Summary = { status: Record<SnState, number>; flags: [string, number][] };
const STATES: SnState[] = ["published", "review", "draft", "pending_retirement", "retired"];

export default function SnKbPage() {
  const bot = useBot();
  const [state, setState] = useState<SnState>("published");
  const [cat, setCat] = useState<number | null>(null);
  const [flag, setFlag] = useState("");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(50);
  const cats = useApi<{ categories: SnCategory[] }>(`/api/chatbots/${bot}/servicenow/categories`);
  const sum = useApi<Summary>(`/api/chatbots/${bot}/servicenow/review-summary`);
  const versions = useApi<SnVersion[]>(`/api/chatbots/${bot}/servicenow/versions`);
  const qs = new URLSearchParams({ status: state, limit: String(limit), ...(cat ? { category: String(cat), sub: "true" } : {}), ...(flag ? { flag } : {}), ...(q.trim() ? { q: q.trim() } : {}) });
  const list = useApi<{ total: number; articles: SnArticle[] }>(`/api/chatbots/${bot}/servicenow/articles?${qs}`);
  const reset = () => setLimit(50);
  const exp = (f: string) => `${API}/api/chatbots/${bot}/servicenow/export?format=${f}`;

  return (
    <Page wide>
      <PageHeader title="Knowledge base" description="Every article, in every state."
        actions={<Link href={`/${bot}/servicenow/article/new${cat ? `?category=${cat}` : ""}`}><Button variant="primary"><Plus className="size-4" /> Create an article</Button></Link>} />
      {(list.error || cats.error) && <ErrorNote>{list.error || cats.error}</ErrorNote>}

      <div className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
          <input className={cn(inputCls, "pl-9")} placeholder="Search title, text or KB number" value={q} onChange={(e) => { setQ(e.target.value); reset(); }} />
        </div>
        <select aria-label="Flags" className="h-9 rounded-[10px] border border-line bg-white px-3 text-sm" value={flag} onChange={(e) => { setFlag(e.target.value); reset(); }}>
          <option value="">Flags: Any</option>
          {sum.data?.flags.map(([f, n]) => <option key={f} value={f}>{f} ({n})</option>)}
        </select>
        <details className="relative">
          <summary aria-label="More" className="flex h-9 cursor-pointer list-none items-center rounded-[10px] border border-line bg-white px-2.5 hover:bg-subtle"><MoreHorizontal className="size-4" /></summary>
          <div className="absolute right-0 z-30 mt-1 w-64 rounded-xl border border-line bg-white p-1 text-[13px] shadow-lg">
            {versions.data?.length ? (
              <>
                <a href={exp("json")} className="block rounded-lg px-2.5 py-1.5 hover:bg-neutral-100">Download latest release (JSON)</a>
                <a href={exp("md")} className="block rounded-lg px-2.5 py-1.5 hover:bg-neutral-100">Download latest release (Markdown)</a>
              </>
            ) : <p className="px-2.5 py-1.5 text-muted">No release yet</p>}
            <a href={`${exp("json")}&scope=everything`} title="Every article right now, labelled Draft, In review, Published, not released yet, Released in vN, Pending retirement or Retired" className="block rounded-lg px-2.5 py-1.5 hover:bg-neutral-100">Download everything right now (JSON)</a>
            <Link href={`/${bot}/servicenow/publish`} className="block rounded-lg px-2.5 py-1.5 hover:bg-neutral-100">Past releases</Link>
          </div>
        </details>
      </div>

      <Tabs className="mb-5" value={state} onChange={(v) => { setState(v); reset(); }}
        items={STATES.map((s) => ({ value: s, label: SN_STATE[s].label, count: sum.data?.status[s] ?? 0 }))} />

      <div className="grid grid-cols-[260px_1fr] items-start gap-6">
        <Tree cats={cats.data?.categories} selected={cat} onSelect={(id) => { setCat(id); reset(); }} />
        <div className="min-w-0">
          {!list.data ? (!list.error && <Loading />) : list.data.articles.length === 0 ? (
            <Card><Empty title={cats.data?.categories.length ? "No articles here" : "Nothing imported yet"}>
              {cats.data?.categories.length ? "Try another state, category or flag." : "The ServiceNow import runs on the server. Ask the person who manages it."}
            </Empty></Card>
          ) : (
            <>
              <Card className="divide-y divide-line">
                {list.data.articles.map((a) => <Row key={a.id} bot={bot} a={a} />)}
              </Card>
              {list.data.total > list.data.articles.length && (
                <button onClick={() => setLimit((l) => l + 100)} className="mt-3 w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">
                  Show more ({list.data.total - list.data.articles.length} remaining)
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </Page>
  );
}

function Row({ bot, a }: { bot: string; a: SnArticle }) {
  return (
    <div className="relative px-5 py-3.5 hover:bg-subtle">
      <div className="flex flex-wrap items-center gap-1.5">
        {/* stretched link: the whole row opens the article, the KB number link sits above it */}
        <Link href={`/${bot}/servicenow/article/${a.id}`} className="text-[13px] font-medium after:absolute after:inset-0">{a.title}</Link>
        {a.p_stage === "review" && <Badge tone="amber">Change in review</Badge>}
        {a.p_stage === "draft" && <Badge>Draft change</Badge>}
        {a.flags.map((f) => <Badge key={f} tone={f === "Internal only" ? "violet" : "neutral"}>{f}</Badge>)}
      </div>
      <p className="mt-0.5 text-xs text-muted">{a.category ?? "No category"} · Updated {ago(a.updated_at)}{a.reviewer && ` by ${a.reviewer}`}</p>
      {a.excerpt && <p className="mt-1 line-clamp-2 text-[13px] text-neutral-600">{a.excerpt}</p>}
      {a.number && (a.kb_url
        ? <a href={a.kb_url} target="_blank" rel="noreferrer" className="relative z-10 mt-1 inline-block font-mono text-[11px] text-neutral-400 hover:text-ink">{a.number}</a>
        : <p className="mt-1 font-mono text-[11px] text-neutral-400">{a.number}</p>)}
    </div>
  );
}

function Tree({ cats, selected, onSelect }: { cats?: SnCategory[]; selected: number | null; onSelect: (id: number | null) => void }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const { kids, sizes } = useMemo(() => {
    const kids = new Map<number | null, SnCategory[]>();
    cats?.forEach((c) => kids.set(c.parent_id, [...(kids.get(c.parent_id) ?? []), c]));
    const sizes = new Map<number, number>();
    const size = (c: SnCategory): number => {
      const n = c.total + (kids.get(c.id) ?? []).reduce((s, k) => s + size(k), 0);
      sizes.set(c.id, n);
      return n;
    };
    kids.get(null)?.forEach(size);
    return { kids, sizes };
  }, [cats]);
  const item = (c: SnCategory, depth: number, label = c.name) => {
    const children = (kids.get(c.id) ?? []).filter((k) => sizes.get(k.id));
    const isOpen = open.has(c.id);
    return (
      <div key={c.id}>
        <div className={cn("flex items-center rounded-lg text-[13px]", selected === c.id ? "bg-ink text-white" : "hover:bg-subtle")} style={{ paddingLeft: depth * 14 }}>
          {children.length ? (
            <button aria-label={`${isOpen ? "Collapse" : "Expand"} ${c.name}`} onClick={() => setOpen((s) => { const n = new Set(s); if (isOpen) n.delete(c.id); else n.add(c.id); return n; })} className="flex size-6 shrink-0 items-center justify-center">
              {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
          ) : <span className="size-6 shrink-0" />}
          <button onClick={() => onSelect(c.id)} className="flex min-w-0 flex-1 justify-between gap-2 py-1.5 pr-2.5 text-left">
            <span className="truncate" title={c.path}>{label}</span><span className={selected === c.id ? "text-neutral-300" : "text-muted"}>{sizes.get(c.id)}</span>
          </button>
        </div>
        {isOpen && children.map((k) => item(k, depth + 1))}
      </div>
    );
  };
  const fl = filter.toLowerCase().trim();
  return (
    <Card className="sticky top-8 max-h-[calc(100vh-6rem)] overflow-y-auto p-2">
      <input className={cn(inputCls, "mb-2")} placeholder="Filter categories" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <button onClick={() => onSelect(null)} className={cn("flex w-full rounded-lg px-2.5 py-1.5 text-left text-[13px]", selected === null ? "bg-ink text-white" : "hover:bg-subtle")}>All</button>
      {!cats ? <Loading /> : fl
        ? cats.filter((c) => sizes.get(c.id) && c.path.toLowerCase().includes(fl)).map((c) => item(c, 0, c.path))
        : (kids.get(null) ?? []).filter((c) => sizes.get(c.id)).map((c) => item(c, 0))}
    </Card>
  );
}

/* Previous architecture: the old single-release KB page (now publish/[number]) with upstream's label colours
   for the old labels. Kept for reference; not used.

      <PageHeader
        title="ServiceNow knowledge base"
        description="The published articles exactly as the chatbot receives them. Change them in Review and publish a new version."
        actions={
          <>
            <a href={exp("json")} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-white px-3.5 text-sm font-medium hover:bg-subtle"><Download className="size-4" /> JSON for the chatbot</a>
            <a href={exp("md")} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-white px-3.5 text-sm font-medium hover:bg-subtle"><Download className="size-4" /> Markdown</a>
            <a href={`${API}/api/chatbots/${bot}/servicenow/export?format=json&scope=everything`} title="Approved articles plus those not reviewed yet, each labelled with its ServiceNow state and review status"
              className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-white px-3.5 text-sm font-medium hover:bg-subtle"><Download className="size-4" /> Everything (JSON)</a>
            <select className="h-9 rounded-[10px] border border-line bg-white px-3 text-sm font-medium" value={v.number} onChange={(e) => router.replace(`/${bot}/servicenow/kb?version=${e.target.value}`)}>
              {versions.data?.map((x) => <option key={x.id} value={x.number}>Version {x.number}{x.number === latest ? " (live)" : ""}</option>)}
            </select>
          </>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-line bg-subtle px-4 py-3 text-[13px]">
        {v.number === latest ? <Badge tone="green" dot>Live</Badge> : <Badge>Older version</Badge>}
        <span>Version {v.number}{v.note && ` — ${v.note}`}</span>
        <span className="text-muted">{dateTime(v.created_at)} · {v.created_by} · {plural(v.stats.total ?? 0, "article")}</span>
      </div>
      <Tabs className="mb-4" value={tab} onChange={setTab} items={[{ value: "content", label: "Articles", count: v.items?.length }, { value: "changes", label: "Changed in this version", count: v.changes?.length }]} />
      {tab === "changes" ? <ChangeList changes={v.changes ?? []} openFirst={0} /> : (
        <div className="grid grid-cols-[260px_1fr] items-start gap-6">
          <Card className="sticky top-8 max-h-[calc(100vh-6rem)] overflow-y-auto p-2">
            <button onClick={() => setCat("")} className={cn("flex w-full justify-between rounded-lg px-2.5 py-1.5 text-left text-[13px]", !cat ? "bg-neutral-100 font-medium" : "hover:bg-subtle")}>All <span className="text-muted">{v.items?.length}</span></button>
            {groups.map(([g, n]) => (
              <button key={g} onClick={() => { setCat(g); setLimit(30); }} className={cn("flex w-full gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px]", cat === g ? "bg-neutral-100 font-medium" : "hover:bg-subtle")}>
                <span className="min-w-0 flex-1 truncate" title={g}>{g.split(" > ").at(-1)}</span><span className="text-muted">{n}</span>
              </button>
            ))}
          </Card>
          <div className="min-w-0">
            <div className="relative mb-4">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
              <input className={cn(inputCls, "pl-9")} placeholder="Search the published articles" value={q} onChange={(e) => { setQ(e.target.value); setLimit(30); }} />
            </div>
            <div className="space-y-3">
              {items.slice(0, limit).map((i) => (
                <Card key={i.entry_id} className="p-5">
                  <p className="text-xs text-muted">{i.category}</p>
                  <h3 className="mt-0.5 font-semibold">{i.title}</h3>
                  {i.number && i.source_url && <a href={i.source_url} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 font-mono text-xs text-muted hover:text-ink">{i.number} <ExternalLink className="size-3" /></a>}
                  {i.labels.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{i.labels.map((l) => <Badge key={l} tone={labelTone(l)}>{l}</Badge>)}</div>}
                  <Rich className="mt-3" content={i.content} />
                </Card>
              ))}
              {items.length === 0 && <p className="py-10 text-center text-sm text-muted">No articles match.</p>}
              {items.length > limit && <button onClick={() => setLimit((l) => l + 50)} className="w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({items.length - limit} remaining)</button>}
            </div>
          </div>

/** Status labels in colour, so filters like "published and reviewed" are easy to spot. * /
function labelTone(l: string): "green" | "amber" | "red" | "blue" | "outline" {
  if (l === "Published in ServiceNow" || l === "Reviewed in KB Curation") return "green";
  if (l === "Expired in ServiceNow" || l === "Internal only" || l.startsWith("Pending retirement")) return "red";
  if (l.endsWith("in ServiceNow") || l === "Not reviewed in KB Curation") return "amber";
  if (l.startsWith("Not in ServiceNow")) return "blue";
  return "outline";
}
*/
