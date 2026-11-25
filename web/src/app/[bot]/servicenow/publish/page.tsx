"use client";
import { AlertTriangle, CheckCircle2, Rocket } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, useApi, type Change } from "@/lib/api";
import type { SnVersion } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { ChangeList } from "@/components/changes";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Page, PageHeader, Tabs, useToast } from "@/components/ui";
import { cn, dateTime, plural } from "@/lib/utils";

type Draft = { base_version: number | null; next_version: number; changes: Change[]; counts: { added: number; modified: number; removed: number }; total: number; waiting_review: number };
type Kind = "all" | "added" | "modified" | "removed";

export default function SnPublishPage() {
  const bot = useBot();
  const toast = useToast();
  const draft = useApi<Draft>(`/api/chatbots/${bot}/servicenow/draft`);
  const versions = useApi<SnVersion[]>(`/api/chatbots/${bot}/servicenow/versions`);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<Kind>("all");
  const [limit, setLimit] = useState(40);
  const d = draft.data;

  const publish = async () => {
    setBusy(true);
    try {
      const v = await api<SnVersion>(`/api/chatbots/${bot}/servicenow/publish`, { body: { note } });
      toast(`ServiceNow version ${v.number} is released`);
      setNote("");
      draft.reload();
      versions.reload();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const summary = d ? [[d.counts.added, "new"], [d.counts.modified, "changed"], [d.counts.removed, "removed"]].filter(([n]) => n).map(([n, w]) => `${n} ${w}`).join(", ") : "";
  const shown = d?.changes.filter((c) => kind === "all" || c.change === kind) ?? [];

  return (
    <Page>
      <PageHeader title="Release a version" description="Saves the whole knowledge base as a numbered version, with every article labeled." />
      {draft.error && <ErrorNote>{draft.error}</ErrorNote>}
      {!d ? (!draft.error && <Loading />) : (
        <div className="grid grid-cols-[1fr_320px] items-start gap-6">
          <div className="min-w-0">
            {d.changes.length === 0 ? (
              <Card>
                <Empty icon={<CheckCircle2 className="size-5" />} title={d.base_version ? `Everything published is in version ${d.base_version}` : "Nothing published yet"} action={d.waiting_review > 0 && <Link href={`/${bot}/servicenow`}><Button variant="primary">Open To do ({d.waiting_review})</Button></Link>}>
                  {d.base_version ? "Publish or retire articles in To do, then come back to release a new version." : "Publish articles in To do, then come back to release the first version."}
                </Empty>
              </Card>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <Tabs value={kind} onChange={(v) => { setKind(v); setLimit(40); }} items={[{ value: "all", label: "All changes", count: d.changes.length }, { value: "added", label: "Added", count: d.counts.added }, { value: "modified", label: "Modified", count: d.counts.modified }, { value: "removed", label: "Removed", count: d.counts.removed }]} />
                  <span className="text-xs text-muted">{d.base_version ? `Compared with version ${d.base_version}` : "First version"}</span>
                </div>
                <ChangeList changes={shown.slice(0, limit)} openFirst={d.changes.length > 12 ? 0 : 3} />
                {shown.length > limit && <button onClick={() => setLimit((l) => l + 100)} className="mt-3 w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({shown.length - limit} remaining)</button>}
              </>
            )}

            <h2 className="mb-3 mt-10 font-semibold">Version history</h2>
            <Card className="divide-y divide-line">
              {!versions.data?.length && <p className="px-5 py-8 text-center text-sm text-muted">No versions released yet.</p>}
              {versions.data?.map((v, i) => (
                <Link key={v.id} href={`/${bot}/servicenow/publish/${v.number}`} className="flex items-center gap-4 px-5 py-3.5 hover:bg-subtle">
                  <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold", i === 0 ? "bg-ink text-white" : "bg-neutral-100 text-neutral-600")}>v{v.number}</span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-[13px] font-medium">{v.note || `Version ${v.number}`} {i === 0 && <Badge tone="green" dot>Latest</Badge>}</p>
                    <p className="text-xs text-muted">{dateTime(v.created_at)} · {v.created_by} · {plural(v.stats.total ?? 0, "article")}</p>
                  </div>
                  <span className="flex gap-2 font-mono text-xs tabular-nums">
                    {!!v.stats.added && <span className="text-emerald-600">+{v.stats.added}</span>}
                    {!!v.stats.modified && <span className="text-amber-600">~{v.stats.modified}</span>}
                    {!!v.stats.removed && <span className="text-red-600">−{v.stats.removed}</span>}
                  </span>
                </Link>
              ))}
            </Card>
          </div>

          <Card className="sticky top-8 p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">Next version</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight">v{d.next_version}</p>
            <div className="mt-4 space-y-2 text-[13px]">
              <p className="text-neutral-700">{summary || "No changes"}</p>
              <div className="flex justify-between border-t border-line pt-2"><span className="text-muted">Total after release</span><b className="tabular-nums">{d.total.toLocaleString()}</b></div>
            </div>
            {d.waiting_review > 0 && (
              <div className="mt-4 flex gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
                <AlertTriangle className="mt-px size-3.5 shrink-0" />
                <span>{plural(d.waiting_review, "article is", "articles are")} still in <Link href={`/${bot}/servicenow`} className="font-medium underline">To do</Link> and aren&apos;t included.</span>
              </div>
            )}
            <textarea className="mt-4 h-20 w-full resize-none rounded-[10px] border border-line p-2.5 text-[13px] outline-none placeholder:text-neutral-400 focus:border-neutral-400" placeholder="What is in this version? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button variant="primary" className="mt-3 w-full" busy={busy} disabled={d.changes.length === 0} onClick={publish}>{d.changes.length === 0 ? (d.base_version ? `Nothing new since version ${d.base_version}` : "Nothing to release yet") : <><Rocket className="size-4" /> Release version {d.next_version}</>}</Button>
            <p className="mt-2.5 text-center text-xs text-muted">Creates a permanent, read-only version.</p>
          </Card>
        </div>
      )}
    </Page>
  );
}

