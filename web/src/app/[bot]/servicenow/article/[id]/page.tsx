"use client";
import { AlertTriangle, Archive, Check, ExternalLink, MoreHorizontal, Pencil, RotateCcw, Send, Trash2, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, useApi } from "@/lib/api";
import type { SnArticle, SnArticleDetail } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Rich } from "@/components/rich";
import { WordDiff } from "@/components/word-diff";
import { Badge, Button, Card, ErrorNote, inputCls, Loading, Page, SnStateBadge, Tabs, useToast } from "@/components/ui";
import { cn, dateTime, shortUrl } from "@/lib/utils";

type Action = "send_for_review" | "publish" | "send_back" | "discard" | "suggest_retire" | "keep" | "retire" | "restore";
type View = "changes" | "new" | "old" | "servicenow";
const LABEL: Record<Action, string> = {
  send_for_review: "Send for review", publish: "Publish", send_back: "Send back to draft", discard: "Discard draft",
  suggest_retire: "Suggest retiring", keep: "Keep published", retire: "Retire", restore: "Restore",
};
const DONE: Record<Action, string> = {
  send_for_review: "Sent for review", publish: "Published", send_back: "Sent back to draft", discard: "Discarded",
  suggest_retire: "Suggested retiring", keep: "Kept published", retire: "Retired", restore: "Restored as a draft",
};
// what each history action reads as; anything else reads as its name with spaces
const SAID: Record<string, string> = {
  imported: "Imported from ServiceNow", servicenow_changed: "Changed in ServiceNow", merged_copy: "Merged with a duplicate copy",
  created: "Created", edited: "Edited", flags_changed: "Flags changed", proposed_new: "Suggested by the AI",
  ai_update: "Update suggested by the AI", ai_remove: "Retirement suggested by the AI", published: "Published",
  sent_back: "Sent back to draft", sent_for_review: "Sent for review", discarded: "Draft discarded", kept_published: "Kept published",
  retired: "Retired", restored: "Restored as a draft", suggested_retire: "Retirement suggested",
};

export default function SnArticlePage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const id = Number(useParams<{ id: string }>().id);
  const fromTodo = useSearchParams().get("from") === "todo";
  const router = useRouter();
  const toast = useToast();
  const { data: a, error, setData } = useApi<SnArticleDetail>(`/api/servicenow/articles/${id}`);
  const queueUrl = `/api/chatbots/${bot}/servicenow/articles?status=queue&limit=500`;
  const queue = useApi<{ articles: SnArticle[] }>(fromTodo ? queueUrl : null);
  const flagList = useApi<string[]>(`/api/chatbots/${bot}/servicenow/flags`);
  const [view, setView] = useState<View>("changes");
  const [note, setNote] = useState("");
  const [noting, setNoting] = useState(false);
  const [newFlag, setNewFlag] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const ids = queue.data?.articles.map((x) => x.id) ?? [];
  const idx = ids.indexOf(id);

  // the next To do item after this one, read fresh so decided items are gone; none left → back to To do
  const next = async () => {
    try {
      const fresh = (await api<{ articles: SnArticle[] }>(queueUrl)).articles.map((x) => x.id);
      const pos = fresh.indexOf(id);
      const n = pos >= 0 ? fresh[pos + 1] : fresh.find((x) => ids.indexOf(x) > idx);
      if (n) return router.push(`/${bot}/servicenow/article/${n}?from=todo`);
      toast(fresh.some((x) => x !== id) ? "That was the last item in To do." : "All caught up");
      router.push(`/${bot}/servicenow`);
    } catch (e) { toast((e as Error).message, true); }
  };

  if (error) return <Page><ErrorNote>{error}</ErrorNote><Link href={`/${bot}/servicenow/kb`} className="text-sm underline">Back to Knowledge base</Link></Page>;
  if (!a) return <Page><Loading /></Page>;

  const act = async (action: Action) => {
    setBusy(action);
    try {
      const r = await api<SnArticleDetail | { deleted: true }>(`/api/servicenow/articles/${a.id}/${action}`, { body: { note } });
      toast(DONE[action]);
      setNote("");
      setNoting(false);
      if ("deleted" in r) return router.push(fromTodo ? `/${bot}/servicenow` : `/${bot}/servicenow/kb`);
      setData(r);
      if (fromTodo && action !== "suggest_retire") await next();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const saveFlags = async (flags: string[]) => {
    setBusy("flags");
    try { setData(await api<SnArticleDetail>(`/api/servicenow/articles/${a.id}`, { method: "PATCH", body: { flags } })); flagList.reload(); }
    catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const allFlags = [...new Set([...(flagList.data ?? []), ...a.flags])];
  const addFlag = () => {
    const f = newFlag.trim();
    const known = allFlags.find((x) => x.toLowerCase() === f.toLowerCase()) ?? f;   // "internal only" ticks "Internal only"
    setNewFlag("");
    if (f && !a.flags.includes(known)) saveFlags([...a.flags, known]);
  };

  // a new article's stage is its state; a published article's stage is that of its pending change
  const stage = a.status === "published" ? a.p_stage : a.status === "draft" || a.status === "review" ? a.status : null;
  const retiring = a.status === "pending_retirement";
  const oldText = a.diff_base === "servicenow" ? a.sn_content : a.approved?.content;
  const showOriginal = !!a.sn_content && !a.same_as_servicenow;
  const views = [
    ...(a.word_diff ? [{ value: "changes" as View, label: "Show changes" }, { value: "new" as View, label: "New text only" }, { value: "old" as View, label: "Old text only" }]
      : [{ value: "new" as View, label: "This text" }]),
    ...(showOriginal ? [{ value: "servicenow" as View, label: "ServiceNow original" }] : []),
  ];
  const shownView = views.some((v) => v.value === view) ? view : views[0].value;
  const text = shownView === "old" ? oldText : shownView === "servicenow" ? a.sn_content : retiring ? a.approved?.content : a.content;
  const btn = (action: Action, Icon: typeof Check, variant?: "primary" | "danger") => (
    <Button key={action} variant={variant} busy={busy === action} onClick={() => act(action)}><Icon className="size-3.5" /> {LABEL[action]}</Button>
  );
  const buttons = stage === "review" ? [btn("send_back", Undo2), btn("discard", Trash2), btn("publish", Check, "primary")]
    : stage === "draft" ? [btn("discard", Trash2), btn("send_for_review", Send, "primary")]
    : retiring ? [btn("keep", RotateCcw), btn("retire", Archive, "danger")]
    : a.status === "retired" ? [btn("restore", RotateCcw)] : [];

  return (
    <Page wide>
      <div className="mb-4 flex items-center gap-2 text-[13px] text-muted">
        {fromTodo ? <Link href={`/${bot}/servicenow`} className="hover:text-ink">← To do</Link> : (
          <span className="min-w-0 truncate">
            <Link href={`/${bot}/servicenow/kb`} className="hover:text-ink">Knowledge base</Link>
            {(a.category ?? "").split(" > ").filter(Boolean).map((c) => <span key={c}> / {c}</span>)}
            <span className="text-ink"> / {a.title}</span>
          </span>
        )}
        {fromTodo && idx >= 0 && (
          <span className="ml-auto flex items-center gap-3">{idx + 1} of {ids.length}<Button size="sm" onClick={next}>Next ›</Button></span>
        )}
      </div>

      <div className="grid grid-cols-[1fr_280px] items-start gap-6">
        <div className="min-w-0">
          <div className="flex items-start gap-3">
            <h1 className="flex-1 text-xl font-semibold tracking-tight">{a.title}</h1>
            {!retiring && a.status !== "retired" && <Link href={`/${bot}/servicenow/article/${a.id}/edit`}><Button><Pencil className="size-3.5" /> Edit</Button></Link>}
            {((a.status === "published" && !a.p_stage) || a.kb_url) && (
              <details className="relative">
                <summary aria-label="More" className="flex h-9 cursor-pointer list-none items-center rounded-[10px] border border-line bg-white px-2.5 hover:bg-subtle"><MoreHorizontal className="size-4" /></summary>
                <div className="absolute right-0 z-30 mt-1 w-52 rounded-xl border border-line bg-white p-1 text-[13px] shadow-lg">
                  {a.status === "published" && !a.p_stage && <button onClick={() => act("suggest_retire")} className="block w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-neutral-100">Suggest retiring</button>}
                  {a.kb_url && <a href={a.kb_url} target="_blank" rel="noreferrer" className="block rounded-lg px-2.5 py-1.5 hover:bg-neutral-100">Open in ServiceNow ↗</a>}
                </div>
              </details>
            )}
          </div>
          <p className="mt-1 text-[13px] text-muted">
            {a.number && (a.kb_url ? <a href={a.kb_url} target="_blank" rel="noreferrer" className="font-mono text-xs hover:text-ink">{a.number}</a> : <span className="font-mono text-xs">{a.number}</span>)}
            {a.number && " · "}Updated {dateTime(a.updated_at)}{a.reviewer && ` by ${a.reviewer}`}
          </p>

          {a.reason && (
            <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-[13px] text-violet-950">
              <p className="mb-1 font-medium">Why this was suggested</p>
              <p>{a.reason}</p>
              {a.link && (
                <p className="mt-1.5 flex flex-wrap gap-x-4 text-xs">
                  <a href={a.link.url} target="_blank" rel="noreferrer" className="underline">Open the web page ↗</a>
                  {a.event_id && <Link href={`/${bot}/servicenow/changes?event=${a.event_id}`} className="underline">See the page change</Link>}
                </p>
              )}
            </div>
          )}

          {retiring && (
            <div className="mt-4 flex gap-2 rounded-xl bg-red-50 px-4 py-3 text-[13px] text-red-900">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span>If you retire it, the next release labels it Retired, so the chatbot can leave it out. It stays in Knowledge base → Retired, and you can restore it.</span>
            </div>
          )}

          {views.length > 1 && <Tabs className="mt-5" value={shownView} onChange={setView} items={views} />}
          <Card className={cn("mt-3 px-6 py-5", retiring && "opacity-60")}>
            {shownView === "changes" && a.word_diff ? <WordDiff segs={a.word_diff} /> : <Rich content={text || "(empty)"} />}
          </Card>

          {buttons.length > 0 && (
            <div className="sticky bottom-0 mt-5 flex flex-wrap items-center gap-2 border-t border-line bg-white/95 py-4 backdrop-blur">
              {noting
                ? <input autoFocus className={cn(inputCls, "w-auto min-w-0 flex-1")} placeholder="Note for the history" value={note} onChange={(e) => setNote(e.target.value)} />
                : <><Button variant="ghost" onClick={() => setNoting(true)}>+ Add a note</Button><span className="flex-1" /></>}
              {buttons}
            </div>
          )}
        </div>

        <Card className="sticky top-8 space-y-4 p-5 text-[13px]">
          <Field label="State">
            <div className="flex flex-wrap gap-1.5"><SnStateBadge status={a.status} />{a.p_stage === "review" && <Badge tone="amber">Change in review</Badge>}{a.p_stage === "draft" && <Badge>Draft change</Badge>}</div>
          </Field>
          <Field label="Flags">
            <div className="space-y-1">
              {allFlags.map((f) => (
                <label key={f} className="flex items-center gap-2">
                  <input type="checkbox" disabled={busy === "flags"} checked={a.flags.includes(f)} onChange={() => saveFlags(a.flags.includes(f) ? a.flags.filter((x) => x !== f) : [...a.flags, f])} />{f}
                </label>
              ))}
            </div>
            <form className="mt-2 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); addFlag(); }}>
              <input className={cn(inputCls, "h-8 text-[13px]")} placeholder="Add a flag" maxLength={40} value={newFlag} onChange={(e) => setNewFlag(e.target.value)} />
              <Button size="sm" type="submit" disabled={!newFlag.trim()}>Add</Button>
            </form>
          </Field>
          <Field label="Release">{a.in_release ? `In the last release: version ${a.in_release}` : "Not in the last release"}</Field>
          <Field label="Category">{a.category ?? "No category"}</Field>
          <Field label="Kept up to date by">
            {a.pages.length ? a.pages.map((p) => (
              <a key={p.id} href={p.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 truncate hover:underline" title={p.url}>
                {p.status === "error" && <span className="size-1.5 shrink-0 rounded-full bg-red-500" aria-label="Can't read this page" />}
                <span className="truncate">{p.title || shortUrl(p.url)}</span><ExternalLink className="size-3 shrink-0 text-muted" />
              </a>
            )) : <p className="text-muted">No web page linked yet. <Link href={`/${bot}/servicenow/web-pages`} className="underline">Web pages</Link></p>}
          </Field>
          {a.history.length > 0 && (
            <Field label="History">
              <div className="space-y-1 text-xs text-neutral-600">
                {a.history.map((h) => (
                  <p key={h.id}>
                    {SAID[h.action] ?? h.action.replace(/_/g, " ")}{h.actor !== "system" && !["imported", "servicenow_changed"].includes(h.action) && ` by ${h.actor}`} on {dateTime(h.created_at)}
                    {typeof h.detail.note === "string" && h.detail.note && <span className="text-muted"> · “{h.detail.note}”</span>}
                  </p>
                ))}
              </div>
            </Field>
          )}
        </Card>
      </div>
    </Page>
  );
}

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div><p className="mb-1 text-xs text-neutral-400">{label}</p>{children}</div>
);
