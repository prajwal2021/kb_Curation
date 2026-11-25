"use client";
import { CheckCircle2, ChevronRight, Library } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useApi, type Change } from "@/lib/api";
import { KIND_LABEL, type SnArticle, type SnLink, type SnOverview } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Page, PageHeader, type Tone } from "@/components/ui";
import { shortUrl } from "@/lib/utils";

type Draft = { base_version: number | null; next_version: number; changes: Change[] };
const DAY = 24 * 3600 * 1000;

export default function SnTodoPage() {
  const bot = useBot();
  const [now] = useState(() => Date.now());
  const o = useApi<SnOverview>(`/api/chatbots/${bot}/servicenow/overview`, 15000);
  const queue = useApi<{ total: number; articles: SnArticle[] }>(`/api/chatbots/${bot}/servicenow/articles?status=queue&limit=500`, 15000);
  const draft = useApi<Draft>(`/api/chatbots/${bot}/servicenow/draft`, 15000);
  const links = useApi<SnLink[]>(`/api/chatbots/${bot}/servicenow/links`, 15000);
  const error = o.error || queue.error || draft.error || links.error;
  const ready = o.data && queue.data && draft.data && links.data;

  const rows = queue.data?.articles ?? [];
  const review = rows.filter((a) => a.status === "review" || a.p_stage === "review");
  const retire = rows.filter((a) => a.status === "pending_retirement");
  const broken = [...new Map((links.data ?? []).filter((l) => l.status === "error").map((l) => [l.url, l])).values()];
  const checked = new Set((links.data ?? []).filter((l) => l.last_checked_at && now - new Date(l.last_checked_at).getTime() < DAY).map((l) => l.url)).size;
  const changes = draft.data?.changes ?? [];
  const last = o.data?.published;
  const open = (a: SnArticle) => `/${bot}/servicenow/article/${a.id}?from=todo`;

  return (
    <Page>
      <PageHeader title="To do" description="Articles waiting for a reviewer." />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!ready ? (!error && <Loading />) : !o.data!.imported ? (
        <Card><Empty icon={<Library className="size-5" />} title="Nothing imported yet">The ServiceNow import runs on the server. Ask the person who manages it.</Empty></Card>
      ) : (
        <>
          {changes.length > 0 && (
            <div className="mb-6 flex items-center gap-4 rounded-2xl bg-ink px-5 py-4 text-white">
              <span className="size-2 shrink-0 rounded-full bg-emerald-400" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{draft.data!.base_version ? `${changes.length} ${changes.length === 1 ? "change" : "changes"} since version ${draft.data!.base_version}` : "Ready for the first release"}</p>
                <p className="truncate text-xs text-neutral-400">“{changes[0].title}”{changes.length > 1 && ` and ${changes.length - 1} more`}</p>
              </div>
              <Link href={`/${bot}/servicenow/publish`}><Button>Release version {draft.data!.next_version} →</Button></Link>
            </div>
          )}

          {review.length + retire.length === 0 ? (
            <Card className="mb-6"><Empty icon={<CheckCircle2 className="size-5" />} title="All caught up">Nothing in review or pending retirement. Every change is in the last release.</Empty></Card>
          ) : (
            <>
              <Section title="In review" items={review} render={(a) => {
                const k = a.kind ? KIND_LABEL[a.kind] : KIND_LABEL.import;
                return <Row key={a.id} href={open(a)} badge={k.label} tone={k.tone} title={a.title} line={a.reason || (a.reviewer ? `Written by ${a.reviewer}` : a.category) || ""} />;
              }} />
              <Section title="Pending retirement" items={retire} render={(a) => <Row key={a.id} href={open(a)} badge="Retire?" tone="red" title={a.title} line={a.reason || a.category || ""} />} />
            </>
          )}

          <Section title="Needs attention" items={broken} render={(l) => (
            <div key={l.url} className="flex items-center gap-3 px-5 py-3.5">
              <Badge tone="red">Can&apos;t read page</Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{l.title || shortUrl(l.url)}</p>
                <p className="truncate text-xs text-muted">{l.error}</p>
              </div>
              <Link href={`/${bot}/servicenow/web-pages`}><Button>Fix</Button></Link>
            </div>
          )} />

          <p className="mt-6 text-xs text-muted">
            {checked} web {checked === 1 ? "page" : "pages"} checked in the last 24 hours · Last release: {last ? `version ${last.number} (${new Date(last.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })})` : "none yet"}
          </p>
        </>
      )}
    </Page>
  );
}

function Section<T>({ title, items, render }: { title: string; items: T[]; render: (i: T) => React.ReactNode }) {
  if (!items.length) return null;
  return (
    <>
      <h2 className="mb-2 mt-6 flex items-center gap-2 text-sm font-semibold first:mt-0">{title} <span className="font-normal text-muted">{items.length}</span></h2>
      <Card className="divide-y divide-line">{items.map(render)}</Card>
    </>
  );
}

function Row({ href, badge, tone, title, line }: { href: string; badge: string; tone: Tone; title: string; line: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 px-5 py-3.5 hover:bg-subtle">
      <Badge tone={tone}>{badge}</Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium">{title}</p>
        {line && <p className="truncate text-xs text-muted">{line}</p>}
      </div>
      <ChevronRight className="size-4 shrink-0 text-neutral-300" />
    </Link>
  );
}
