"use client";
import { ExternalLink, GitCompareArrows, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useApi } from "@/lib/api";
import type { SnEvent } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { DiffView } from "@/components/diff";
import { Badge, Card, Empty, ErrorNote, Loading, Page, PageHeader, Stat, Tabs } from "@/components/ui";
import { ago, cn, dateTime, shortUrl } from "@/lib/utils";

type Filter = "all" | "proposals" | "errors";
const ACTION = { update: { label: "Update", tone: "amber" }, new: { label: "New article", tone: "violet" }, remove: { label: "Remove", tone: "red" }, none: { label: "No change", tone: "neutral" } } as const;

export default function SnChangesPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const router = useRouter();
  const params = useSearchParams();
  const eventId = Number(params.get("event")) || null;
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(100);
  const list = useApi<SnEvent[]>(`/api/chatbots/${bot}/servicenow/events?limit=${limit}`, 20000);
  const rows = (list.data ?? []).filter((e) => filter === "all" || (filter === "proposals" ? e.proposals > 0 : e.kind === "error"));
  const open = eventId ?? rows[0]?.id ?? null;

  return (
    <Page wide>
      <PageHeader title="Changes" description="Every time a linked page changed (or was compared on request), what changed on the page and what the AI decided for each affected article. Proposals wait in Review." />
      {list.error && <ErrorNote>{list.error}</ErrorNote>}
      {!list.data ? (!list.error && <Loading />) : list.data.length === 0 ? (
        <Card><Empty icon={<GitCompareArrows className="size-5" />} title="No page changes yet">Linked pages are read on their schedule. The first read only records the page; changes after that show up here.</Empty></Card>
      ) : (
        <div className="grid grid-cols-[380px_1fr] items-start gap-5">
          <div>
            <Tabs className="mb-3" value={filter} onChange={setFilter} items={[
              { value: "all", label: "All", count: list.data.length },
              { value: "proposals", label: "With proposals", count: list.data.filter((e) => e.proposals > 0).length },
              { value: "errors", label: "Errors", count: list.data.filter((e) => e.kind === "error").length },
            ]} />
            <Card className="divide-y divide-line overflow-hidden">
              {rows.map((e) => (
                <button key={e.id} onClick={() => router.replace(`/${bot}/servicenow/changes?event=${e.id}`, { scroll: false })} className={cn("block w-full px-4 py-3 text-left", e.id === open ? "bg-neutral-100" : "hover:bg-subtle")}>
                  <div className="flex items-center gap-2">
                    <Badge tone={e.kind === "error" ? "red" : e.proposals ? "amber" : "neutral"}>{e.kind === "error" ? "Error" : e.kind === "audit" ? "Comparison" : "Changed"}</Badge>
                    {e.kind === "changed" && <Stat added={e.added} removed={e.removed} />}
                    <span className="flex-1" />
                    <span className="text-xs text-muted">{ago(e.created_at)}</span>
                  </div>
                  <p className="mt-1 truncate text-[13px] font-medium">{e.link.title || shortUrl(e.link.url)}</p>
                  <p className="truncate text-xs text-muted">{e.link.category}</p>
                </button>
              ))}
              {rows.length === 0 && <p className="px-4 py-6 text-center text-[13px] text-muted">Nothing here.</p>}
            </Card>
            {list.data.length >= limit && <button onClick={() => setLimit((l) => l + 200)} className="mt-3 w-full rounded-xl border border-line py-2 text-[13px] text-neutral-600 hover:bg-subtle">Show older</button>}
          </div>
          {open ? <EventDetail key={open} id={open} bot={bot} /> : null}
        </div>
      )}
    </Page>
  );
}

function EventDetail({ id, bot }: { id: number; bot: string }) {
  const { data: e, error } = useApi<SnEvent>(`/api/servicenow/events/${id}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!e) return <Loading />;
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <a href={e.link.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-semibold hover:underline">{e.link.title || shortUrl(e.link.url)} <ExternalLink className="size-3.5 text-neutral-400" /></a>
        <p className="text-[13px] text-muted">{e.link.category} · {dateTime(e.created_at)} · {e.trigger === "schedule" ? "scheduled check" : `checked by ${e.actor}`}</p>
        <p className="mt-3 text-[13px]">{e.summary}</p>
        {e.error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{e.error}</p>}
      </Card>

      {!!e.decisions?.length && (
        <Card>
          <h3 className="flex items-center gap-1.5 border-b border-line px-5 py-3 font-semibold"><Sparkles className="size-4 text-violet-600" /> What the AI decided</h3>
          <div className="divide-y divide-line">
            {e.decisions.map((d, i) => {
              const A = ACTION[d.action];
              return (
                <div key={i} className="flex gap-3 px-5 py-3">
                  <Badge tone={A.tone}>{A.label}</Badge>
                  <div className="min-w-0 flex-1 text-[13px]">
                    {d.article_id && d.result === "proposed"
                      ? <Link href={`/${bot}/servicenow/article/${d.article_id}`} className="font-medium hover:underline">{d.title}</Link>
                      : <p className="font-medium">{d.title}</p>}
                    {d.reason && <p className="mt-0.5 text-muted">{d.reason}</p>}
                    {d.result && d.result !== "proposed" && d.action !== "none" && <p className="mt-0.5 text-xs text-amber-700">Not applied: {d.result}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {e.kind !== "audit" && (
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3"><h3 className="font-semibold">What changed on the page</h3>{e.diff && <Stat added={e.added} removed={e.removed} />}</div>
          {e.diff?.length ? <DiffView lines={e.diff} className="py-2" /> : <p className="px-5 py-4 text-[13px] text-muted">No text diff for this check.</p>}
        </Card>
      )}
    </div>
  );
}
