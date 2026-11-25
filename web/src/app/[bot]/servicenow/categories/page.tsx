"use client";
import { AlertCircle, CheckCircle2, ChevronRight, CornerLeftUp, ExternalLink, FolderTree, Link2, Link2Off, Loader2, Plus, RefreshCw, Search, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import type { SnArticle, SnCategory, SnLink } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Badge, Button, Card, Drawer, Empty, ErrorNote, inputCls, Label, Loading, Modal, Page, PageHeader, Tabs, useToast, SnStateBadge } from "@/components/ui";
import { ago, cn, dateTime, plural, shortUrl } from "@/lib/utils";

type Cats = { categories: SnCategory[]; uncategorized: { total: number; waiting: number } };
const SCHEDULES: { value: string; label: string }[] = [
  { value: "6", label: "Every 6 hours" }, { value: "12", label: "Every 12 hours" }, { value: "24", label: "Daily" },
  { value: "168", label: "Weekly" }, { value: "", label: "Only when I check" },
];
const every = (h: number | null) => SCHEDULES.find((s) => s.value === String(h ?? ""))?.label ?? `Every ${h} hours`;

export default function SnCategoriesPage() {
  const bot = useBot();
  const [tab, setTab] = useState<"categories" | "links">("categories");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [hideEmpty, setHideEmpty] = useState(false);
  const [view, setView] = useState<"all" | "watched" | "missing">("all");
  const cats = useApi<Cats>(`/api/chatbots/${bot}/servicenow/categories`, 10000);
  const all = useMemo(() => cats.data?.categories ?? [], [cats.data]);
  const links = all.flatMap((c) => c.links);
  const { byId, cover } = useMemo(() => {
    const m = new Map(all.map((c) => [c.id, c]));
    return { byId: m, cover: coverage(all, m) };
  }, [all]);
  const withArticles = all.filter((c) => c.total > 0);
  const watched = withArticles.filter((c) => cover.get(c.id)?.kind !== "none").length;
  const errors = links.filter((l) => l.status === "error").length;

  // a category is shown when it, or anything below it, matches the search and the view
  const shown = useMemo(() => {
    const ql = q.toLowerCase().trim();
    const keep = new Set<number>();
    for (const c of all) {
      const k = cover.get(c.id)?.kind;
      const inView = view === "all" || (view === "watched" ? c.links.length > 0 || (c.total > 0 && k === "parent") : c.total > 0 && k === "none");
      const hit = inView && (!ql || c.path.toLowerCase().includes(ql)) && (!hideEmpty || c.total > 0 || c.links.length > 0);
      if (!hit) continue;
      for (let x: SnCategory | undefined = c; x; x = x.parent_id ? byId.get(x.parent_id) : undefined) keep.add(x.id);
    }
    return all.filter((c) => keep.has(c.id));
  }, [all, q, hideEmpty, byId, view, cover]);
  const current = open ? byId.get(open) : undefined;

  return (
    <Page>
      <PageHeader
        title="Categories & links"
        description="The categories exactly as they are in ServiceNow. Add the web pages each category's articles come from: when a page changes, the AI reads the change and proposes edits, new articles or removals for review."
      />
      {cats.error && <ErrorNote>{cats.error}</ErrorNote>}
      {cats.data && withArticles.length > 0 && (
        <div className="mb-5 grid grid-cols-3 gap-3">
          <Summary icon={<Link2 className="size-4" />} tone="violet" value={`${watched} of ${withArticles.length}`} label="categories with articles are watched by a link" />
          <Summary icon={<CheckCircle2 className="size-4" />} tone={errors ? "red" : "green"} value={String(links.length)} label={errors ? `links · ${errors} could not be read` : "links, all readable"} />
          <Summary icon={<Link2Off className="size-4" />} tone="amber" value={String(withArticles.length - watched)} label="categories with articles have no link yet" onClick={() => { setTab("categories"); setView("missing"); }} />
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={tab} onChange={setTab} items={[{ value: "categories", label: "Categories", count: all.length }, { value: "links", label: "All links", count: links.length }]} />
        {tab === "categories" && (
          <>
            <Tabs value={view} onChange={setView} items={[{ value: "all", label: "All" }, { value: "watched", label: "Watched", count: watched }, { value: "missing", label: "Needs a link", count: withArticles.length - watched }]} />
            <div className="relative w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
              <input className={cn(inputCls, "pl-9")} placeholder="Find a category" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-[13px] text-neutral-600"><input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} /> Hide empty categories</label>
          </>
        )}
      </div>

      {!cats.data ? (!cats.error && <Loading />) : all.length === 0 ? (
        <Card><Empty icon={<FolderTree className="size-5" />} title="No categories yet">Categories appear after the ServiceNow import.</Empty></Card>
      ) : tab === "links" ? (
        <LinkTable links={links} onOpen={(id) => { setOpen(id); }} />
      ) : (
        <Card className="divide-y divide-line overflow-hidden">
          {shown.map((c) => (
            <button key={c.id} onClick={() => setOpen(c.id)} className={cn("relative flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-subtle", c.links.length > 0 && "bg-violet-50/40")}>
              {c.links.length > 0 && <span className="absolute inset-y-0 left-0 w-[3px] bg-violet-500" aria-hidden />}
              <span style={{ width: c.depth * 20 }} className="shrink-0" />
              <FolderTree className={cn("size-4 shrink-0", c.total ? "text-neutral-500" : "text-neutral-300")} />
              <span className={cn("min-w-0 flex-1 truncate text-[13px]", c.total ? "font-medium" : "text-muted")}>{c.name}{!c.active && <span className="ml-2 text-xs text-muted">(inactive in ServiceNow)</span>}</span>
              <CoverageChip c={c} cover={cover.get(c.id)} />
              <span className="w-28 shrink-0 text-right text-xs tabular-nums text-muted">{c.total ? plural(c.total, "article") : "—"}</span>
              <span className="w-20 shrink-0 text-right">{c.waiting > 0 && <Badge tone="blue">{c.waiting} to do</Badge>}</span>
              <ChevronRight className="size-4 shrink-0 text-neutral-300" />
            </button>
          ))}
          {shown.length === 0 && <p className="px-5 py-8 text-center text-sm text-muted">No category matches.</p>}
        </Card>
      )}
      {current && <CategoryDrawer bot={bot} cat={current} inherited={cover.get(current.id)} onClose={() => setOpen(null)} onChanged={cats.reload} />}
    </Page>
  );
}

type Cover = { kind: "own" | "parent" | "none"; from?: SnCategory };

/** How each category is watched: its own links, a link on a parent (which covers everything below it), or nothing.
 *  Links pinned to one article only cover that article, so they don't count for the categories below. */
function coverage(all: SnCategory[], byId: Map<number, SnCategory>): Map<number, Cover> {
  const out = new Map<number, Cover>();
  for (const c of all) {
    if (c.links.length) { out.set(c.id, { kind: "own" }); continue; }
    let p = c.parent_id ? byId.get(c.parent_id) : undefined;
    while (p && !p.links.some((l) => !l.article_id)) p = p.parent_id ? byId.get(p.parent_id) : undefined;
    out.set(c.id, p ? { kind: "parent", from: p } : { kind: "none" });
  }
  return out;
}

function CoverageChip({ c, cover }: { c: SnCategory; cover?: Cover }) {
  if (c.links.length) {
    const bad = c.links.filter((l) => l.status === "error").length;
    const busy = c.links.some((l) => l.status === "checking" || l.status === "pending");
    const names = c.links.map((l) => `${l.label || l.title || shortUrl(l.url)}${l.status === "error" ? " (could not be read)" : ""}`).join("\n");
    return (
      <span title={names} className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", bad ? "bg-red-50 text-red-700 ring-1 ring-red-200" : "bg-violet-100 text-violet-800")}>
        {busy ? <Loader2 className="size-3 animate-spin" /> : bad ? <AlertCircle className="size-3" /> : <Link2 className="size-3" />}
        {plural(c.links.length, "link")}
        {!busy && <span className={cn("size-1.5 rounded-full", bad ? "bg-red-500" : "bg-emerald-500")} aria-label={bad ? "error" : "watching"} />}
      </span>
    );
  }
  if (cover?.kind === "parent" && cover.from && c.total > 0)
    return <span title={`Watched through the links on “${cover.from.path}”`} className="inline-flex shrink-0 items-center gap-1 rounded-full border border-violet-200 px-2 py-0.5 text-xs text-violet-700"><CornerLeftUp className="size-3" /> via {cover.from.name}</span>;
  if (c.total > 0) return <span title="These articles are not watched by any web page" className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-800"><Link2Off className="size-3" /> No link</span>;
  return null;
}

function Summary({ icon, tone, value, label, onClick }: { icon: React.ReactNode; tone: "violet" | "green" | "red" | "amber"; value: string; label: string; onClick?: () => void }) {
  const tones = { violet: "bg-violet-50 text-violet-700", green: "bg-emerald-50 text-emerald-700", red: "bg-red-50 text-red-700", amber: "bg-amber-50 text-amber-700" };
  const Tag = onClick ? "button" : "div";
  return (
    <Tag onClick={onClick} className={cn("flex items-center gap-3 rounded-2xl border border-line bg-white p-4 text-left", onClick && "hover:border-neutral-300")}>
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl", tones[tone])}>{icon}</span>
      <span className="min-w-0"><span className="block text-lg font-semibold tabular-nums leading-tight">{value}</span><span className="block text-xs text-muted">{label}</span></span>
    </Tag>
  );
}

function LinkStatus({ l }: { l: SnLink }) {
  if (l.status === "checking" || l.status === "pending") return <Badge tone="blue"><Loader2 className="size-3 animate-spin" /> Checking</Badge>;
  if (l.status === "error") return <Badge tone="red"><AlertCircle className="size-3" /> Error</Badge>;
  return <Badge tone="green"><CheckCircle2 className="size-3" /> Watching</Badge>;
}

function LinkTable({ links, onOpen }: { links: SnLink[]; onOpen: (categoryId: number) => void }) {
  if (!links.length) return <Card><Empty icon={<Link2 className="size-5" />} title="No links yet">Open a category and add the web pages its articles are based on.</Empty></Card>;
  return (
    <Card className="divide-y divide-line">
      {links.map((l) => (
        <button key={l.id} onClick={() => onOpen(l.category_id)} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-subtle">
          <LinkStatus l={l} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium">{l.label || l.title || shortUrl(l.url)}</p>
            <p className="truncate text-xs text-muted">{l.category} · {shortUrl(l.url)}</p>
          </div>
          <span className="shrink-0 text-xs text-muted">{l.last_checked_at ? `Checked ${ago(l.last_checked_at)}` : "Not checked yet"}</span>
        </button>
      ))}
    </Card>
  );
}

function CategoryDrawer({ bot, cat, inherited, onClose, onChanged }: { bot: string; cat: SnCategory; inherited?: Cover; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const arts = useApi<{ total: number; articles: SnArticle[] }>(`/api/chatbots/${bot}/servicenow/articles?status=draft,review,published,pending_retirement&category=${cat.id}&limit=500`);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState<SnLink | null>(null);

  const run = async (l: SnLink, audit: boolean) => {
    setBusy(l.id);
    try {
      await api(`/api/servicenow/links/${l.id}/check`, { body: { audit } });
      toast(audit ? "The AI is comparing the articles with the page. Proposals appear in Review." : "Checking the page now.");
      onChanged();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const schedule = async (l: SnLink, v: string) => {
    try {
      await api(`/api/servicenow/links/${l.id}`, { method: "PATCH", body: { set_schedule: true, schedule_hours: v ? Number(v) : null } });
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };
  const remove = async (l: SnLink) => {
    try {
      await api(`/api/servicenow/links/${l.id}`, { method: "DELETE" });
      toast("Link removed");
      setConfirmDel(null);
      onChanged();
    } catch (e) { toast((e as Error).message, true); }
  };
  const artTitle = (id: number | null) => arts.data?.articles.find((a) => a.id === id)?.title;

  return (
    <Drawer title={cat.name} subtitle={cat.path} onClose={onClose}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">Links <span className="font-normal text-muted">{cat.links.length}</span></h3>
        <Button size="sm" variant="primary" onClick={() => setAdding(true)}><Plus className="size-3.5" /> Add link</Button>
      </div>
      {inherited?.kind === "parent" && inherited.from && (
        <div className="mb-3 flex items-start gap-2 rounded-xl border border-violet-200 bg-violet-50/60 px-3 py-2.5 text-[13px] text-violet-900">
          <CornerLeftUp className="mt-0.5 size-3.5 shrink-0" />
          <span>Already watched through {plural(inherited.from.links.filter((l) => !l.article_id).length, "link")} on <b>{inherited.from.path}</b>, which also cover this category. Add a link here only for a page specific to these articles.</span>
        </div>
      )}
      <p className="mb-3 text-[13px] text-muted">Pages added here are compared with the articles in this category{cat.depth >= 0 ? " and the categories inside it" : ""}. The first read only records the page; from then on every change is sent to the AI.</p>
      {cat.links.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-[13px] text-muted">No links on this category yet.</div>
      ) : (
        <div className="space-y-2">
          {cat.links.map((l) => (
            <div key={l.id} className="rounded-xl border border-line p-3.5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <a href={l.url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-[13px] font-medium hover:underline">
                    <span className="truncate">{l.label || l.title || shortUrl(l.url)}</span><ExternalLink className="size-3 shrink-0 text-neutral-400" />
                  </a>
                  <p className="truncate text-xs text-muted">{shortUrl(l.url)}</p>
                  {l.article_id && <p className="mt-1 text-xs text-violet-700">Only for: {artTitle(l.article_id) ?? `article #${l.article_id}`}</p>}
                </div>
                <LinkStatus l={l} />
              </div>
              {l.error && <p className="mt-2 rounded-lg bg-red-50 px-2.5 py-1.5 text-xs text-red-700">{l.error}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <select className="h-8 rounded-lg border border-line bg-white px-2 text-xs" value={String(l.schedule_hours ?? "")} onChange={(e) => schedule(l, e.target.value)}>
                  {SCHEDULES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  {!SCHEDULES.some((s) => s.value === String(l.schedule_hours ?? "")) && <option value={String(l.schedule_hours)}>{every(l.schedule_hours)}</option>}
                </select>
                <Button size="sm" busy={busy === l.id} disabled={l.status === "checking" || l.status === "pending"} onClick={() => run(l, false)}><RefreshCw className="size-3.5" /> Check now</Button>
                <Button size="sm" disabled={!l.last_checked_at || l.status === "checking" || l.status === "pending"} onClick={() => run(l, true)} title="Read the whole page and propose fixes for anything the articles get wrong"><Sparkles className="size-3.5" /> Compare articles with page</Button>
                <span className="flex-1" />
                <button onClick={() => setConfirmDel(l)} className="rounded-lg p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600" aria-label="Remove link"><Trash2 className="size-3.5" /></button>
              </div>
              <p className="mt-2 text-xs text-muted">
                {l.last_checked_at ? `Checked ${ago(l.last_checked_at)}` : "Not read yet"}
                {l.last_changed_at && ` · last changed ${ago(l.last_changed_at)}`}
                {l.next_run_at && ` · next check ${ago(l.next_run_at)}`}
              </p>
            </div>
          ))}
        </div>
      )}

      <h3 className="mb-2 mt-8 font-semibold">Articles <span className="font-normal text-muted">{arts.data?.total ?? ""}</span></h3>
      {!arts.data ? <Loading /> : arts.data.articles.length === 0 ? <p className="text-[13px] text-muted">No articles in this category.</p> : (
        <div className="divide-y divide-line rounded-xl border border-line">
          {arts.data.articles.map((a) => (
            <Link key={a.id} href={`/${bot}/servicenow/article/${a.id}`} className="flex items-center gap-3 px-3.5 py-2.5 hover:bg-subtle">
              <span className="w-20 shrink-0 font-mono text-[11px] text-muted">{a.number ?? "new"}</span>
              <span className="min-w-0 flex-1 truncate text-[13px]">{a.title}</span>
              {a.category !== cat.path && <span className="max-w-40 shrink-0 truncate text-[11px] text-muted">{a.category?.split(" > ").at(-1)}</span>}
              <SnStateBadge status={a.status} />
            </Link>
          ))}
        </div>
      )}

      {adding && <AddLink bot={bot} cat={cat} articles={arts.data?.articles ?? []} onClose={() => setAdding(false)} onDone={() => { setAdding(false); onChanged(); toast("Link added. Reading the page now."); }} />}
      {confirmDel && (
        <Modal title="Remove this link?" onClose={() => setConfirmDel(null)} footer={<><Button onClick={() => setConfirmDel(null)}>Cancel</Button><Button variant="danger" onClick={() => remove(confirmDel)}>Remove link</Button></>}>
          <p className="text-sm text-muted">{shortUrl(confirmDel.url)} will no longer be checked. Articles and proposals already made from it stay as they are. Its change history is deleted.</p>
          <p className="mt-2 text-xs text-muted">Added by {confirmDel.created_by} on {dateTime(confirmDel.created_at)}</p>
        </Modal>
      )}
    </Drawer>
  );
}

function AddLink({ bot, cat, articles, onClose, onDone }: { bot: string; cat: SnCategory; articles: SnArticle[]; onClose: () => void; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [article, setArticle] = useState("");
  const [hours, setHours] = useState("24");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      await api(`/api/chatbots/${bot}/servicenow/links`, { body: { category_id: cat.id, url, label, article_id: article ? Number(article) : null, set_schedule: true, schedule_hours: hours ? Number(hours) : null } });
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Add a link to “${cat.name}”`} width="max-w-lg" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!url.trim()} onClick={save}>Add link</Button></>}>
      <Label>Web page</Label>
      <input autoFocus className={inputCls} placeholder="https://www.depts.ttu.edu/…" value={url} onChange={(e) => setUrl(e.target.value)} />
      <div className="h-3" />
      <Label>Name (optional)</Label>
      <input className={inputCls} placeholder="e.g. Tuition and fees page" value={label} onChange={(e) => setLabel(e.target.value)} />
      <div className="h-3" />
      <Label>Which articles does it update?</Label>
      <select className={inputCls} value={article} onChange={(e) => setArticle(e.target.value)}>
        <option value="">Every article in this category (the AI picks the ones a change affects)</option>
        {articles.map((a) => <option key={a.id} value={a.id}>Only: {a.title}</option>)}
      </select>
      <div className="h-3" />
      <Label>Check for changes</Label>
      <select className={inputCls} value={hours} onChange={(e) => setHours(e.target.value)}>
        {SCHEDULES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
