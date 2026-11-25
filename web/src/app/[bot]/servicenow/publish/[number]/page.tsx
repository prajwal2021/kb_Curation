"use client";
import { Download, ExternalLink, Search } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { API, useApi } from "@/lib/api";
import type { SnVersion } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { ChangeList } from "@/components/changes";
import { Rich } from "@/components/rich";
import { Badge, Card, Empty, inputCls, Loading, Page, PageHeader, Tabs } from "@/components/ui";
import { cn, dateTime, plural } from "@/lib/utils";

export default function SnVersionPage() {
  const bot = useBot();
  const router = useRouter();
  const number = Number(useParams<{ number: string }>().number);
  const versions = useApi<SnVersion[]>(`/api/chatbots/${bot}/servicenow/versions`);
  const latest = versions.data?.[0]?.number;
  const { data: v, error } = useApi<SnVersion>(`/api/chatbots/${bot}/servicenow/versions/${number}`);
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"content" | "changes">("content");
  const [limit, setLimit] = useState(30);

  const groups = useMemo(() => {
    const m = new Map<string, number>();
    v?.items?.forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1));
    return [...m.entries()];
  }, [v]);
  const items = useMemo(() => {
    const ql = q.toLowerCase().trim();
    return (v?.items ?? []).filter((i) => (!cat || i.category === cat) && (!ql || `${i.title} ${i.content} ${i.number ?? ""}`.toLowerCase().includes(ql)));
  }, [v, cat, q]);

  if (error) return <Page><PageHeader title={`Version ${number}`} /><Card><Empty title="This version could not be loaded">{error}</Empty></Card></Page>;
  if (!v) return <Page><Loading /></Page>;
  const exp = (f: string) => `${API}/api/chatbots/${bot}/servicenow/export?format=${f}&version=${v.number}`;

  return (
    <Page wide>
      <PageHeader
        title={`Version ${v.number}`}
        description="The released articles exactly as the chatbot receives them."
        actions={
          <>
            <a href={exp("json")} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-white px-3.5 text-sm font-medium hover:bg-subtle"><Download className="size-4" /> JSON for the chatbot</a>
            <a href={exp("md")} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-line bg-white px-3.5 text-sm font-medium hover:bg-subtle"><Download className="size-4" /> Markdown</a>
            <select className="h-9 rounded-[10px] border border-line bg-white px-3 text-sm font-medium" value={v.number} onChange={(e) => router.replace(`/${bot}/servicenow/publish/${e.target.value}`)}>
              {versions.data?.map((x) => <option key={x.id} value={x.number}>Version {x.number}{x.number === latest ? " (latest)" : ""}</option>)}
            </select>
          </>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-line bg-subtle px-4 py-3 text-[13px]">
        {v.number === latest ? <Badge tone="green" dot>Latest</Badge> : <Badge>Older version</Badge>}
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
              <input className={cn(inputCls, "pl-9")} placeholder="Search this release" value={q} onChange={(e) => { setQ(e.target.value); setLimit(30); }} />
            </div>
            <div className="space-y-3">
              {items.slice(0, limit).map((i) => (
                <Card key={i.entry_id} className="p-5">
                  <p className="text-xs text-muted">{i.category}</p>
                  <h3 className="mt-0.5 font-semibold">{i.title}</h3>
                  {i.number && i.source_url && <a href={i.source_url} target="_blank" rel="noreferrer" className="mt-0.5 inline-flex items-center gap-1 font-mono text-xs text-muted hover:text-ink">{i.number} <ExternalLink className="size-3" /></a>}
                  <Rich className="mt-3" content={i.content} />
                </Card>
              ))}
              {items.length === 0 && <p className="py-10 text-center text-sm text-muted">No articles match.</p>}
              {items.length > limit && <button onClick={() => setLimit((l) => l + 50)} className="w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({items.length - limit} remaining)</button>}
            </div>
          </div>
        </div>
      )}
    </Page>
  );
}
