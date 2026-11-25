"use client";
import { BookOpenCheck, Globe, History, ListChecks } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { useBot } from "@/components/shell";
import { Card, Empty, ErrorNote, Loading, Page, PageHeader, Tabs } from "@/components/ui";
import { cn } from "@/lib/utils";

type Item = { id: number; action: string; actor: string; summary: string; detail: { urls?: string[]; note?: string; article_id?: number }; created_at: string };
type Tab = "decisions" | "releases" | "pages" | "";
const GROUP = {
  decisions: { label: "Decisions", icon: ListChecks, color: "bg-amber-50 text-amber-700",
    actions: ["send_for_review", "publish", "send_back", "discard", "suggest_retire", "keep", "retire", "restore", "created", "flags", "bulk_publish", "bulk_send_back"] },
  releases: { label: "Releases", icon: BookOpenCheck, color: "bg-emerald-50 text-emerald-700", actions: ["published"] },
  pages: { label: "Web pages", icon: Globe, color: "bg-blue-50 text-blue-700", actions: ["link_added", "link_removed", "link_schedule", "link_check", "link_audit"] },
} as const;
const groupOf = (action: string) => Object.values(GROUP).find((g) => (g.actions as readonly string[]).includes(action));

export default function HistoryPage() {
  const bot = useBot();
  const [tab, setTab] = useState<Tab>("decisions");
  const [limit, setLimit] = useState(200);
  const filter = tab ? `&actions=${GROUP[tab].actions.join(",")}` : "";
  const { data, error } = useApi<{ actions: Record<string, number>; items: Item[] }>(`/api/chatbots/${bot}/activity?limit=${limit}${filter}`, 15000);
  const count = (actions: readonly string[]) => actions.reduce((n, a) => n + (data?.actions[a] ?? 0), 0);
  const days = useMemo(() => {
    const out: { day: string; items: Item[] }[] = [];
    data?.items.forEach((i) => {
      const day = new Date(i.created_at).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
      if (out.at(-1)?.day !== day) out.push({ day, items: [] });
      out.at(-1)!.items.push(i);
    });
    return out;
  }, [data]);

  return (
    <Page>
      <PageHeader title="History" description="Who did what, and when." />
      {error && <ErrorNote>{error}</ErrorNote>}
      <Tabs className="mb-5" value={tab} onChange={(v) => { setTab(v); setLimit(200); }} items={[
        ...(Object.keys(GROUP) as (keyof typeof GROUP)[]).map((k) => ({ value: k as Tab, label: GROUP[k].label, count: count(GROUP[k].actions) })),
        { value: "" as Tab, label: "Everything", count: Object.values(data?.actions ?? {}).reduce((a, b) => a + b, 0) },
      ]} />
      {!data ? <Loading /> : data.items.length === 0 ? (
        <Card><Empty icon={<History className="size-5" />} title="Nothing here yet">Actions show up here as people review, release and change web pages.</Empty></Card>
      ) : (
        <div className="space-y-6">
          {days.map((d) => (
            <div key={d.day}>
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-neutral-400">{d.day}</p>
              <Card className="divide-y divide-line">
                {d.items.map((i) => {
                  const G = groupOf(i.action);
                  const Icon = G?.icon ?? History;
                  return (
                    <div key={i.id} className="flex gap-3 px-4 py-3">
                      <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg", G?.color ?? "bg-neutral-100 text-neutral-600")}><Icon className="size-3.5" /></span>
                      <div className="min-w-0 flex-1">
                        {i.detail.article_id
                          ? <Link href={`/${bot}/servicenow/article/${i.detail.article_id}`} className="text-[13px] text-neutral-800 hover:underline">{i.summary}</Link>
                          : <p className="text-[13px] text-neutral-800">{i.summary}</p>}
                        {i.detail.note && <p className="mt-0.5 text-xs italic text-muted">“{i.detail.note}”</p>}
                        {i.detail.urls && i.detail.urls.length > 1 && (
                          <details className="mt-1 text-xs text-muted">
                            <summary className="cursor-pointer hover:text-ink">Show the {i.detail.urls.length} pages</summary>
                            <div className="mt-1 space-y-0.5 font-mono">{i.detail.urls.map((u) => <p key={u} className="truncate">{u}</p>)}</div>
                          </details>
                        )}
                        <p className="mt-0.5 text-xs text-muted">{i.actor} · {new Date(i.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</p>
                      </div>
                    </div>
                  );
                })}
              </Card>
            </div>
          ))}
          {data.items.length >= limit && <button onClick={() => setLimit((l) => l + 300)} className="w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show older activity</button>}
        </div>
      )}
    </Page>
  );
}
