"use client";
import { AlertCircle, Globe, Loader2, MoreHorizontal, Plus, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import type { SnCategory, SnLink } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Button, Card, Empty, ErrorNote, inputCls, Label, Loading, Modal, Page, PageHeader, useToast } from "@/components/ui";
import { cn, plural, shortUrl } from "@/lib/utils";

const DAY = 24 * 3600 * 1000;
const SCHEDULES = [{ value: "6", label: "6 hours" }, { value: "12", label: "12 hours" }, { value: "24", label: "Day" }, { value: "168", label: "Week" }, { value: "", label: "Only when I check" }];
type Group = { url: string; links: SnLink[] };   // one web page = every link with its address, lowest id first
const title = (g: Group) => g.links.find((l) => l.label)?.label || g.links[0].title || shortUrl(g.url);
const busy = (g: Group) => g.links.some((l) => l.status === "checking" || l.status === "pending");

export default function SnWebPagesPage() {
  const bot = useBot();
  const toast = useToast();
  const [now] = useState(() => Date.now());
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState<Group | "new" | null>(null);   // a group = add categories to that page
  const [moving, setMoving] = useState<Group | null>(null);
  const [removing, setRemoving] = useState<Group | null>(null);
  const links = useApi<SnLink[]>(`/api/chatbots/${bot}/servicenow/links`, 10000);
  const cats = useApi<{ categories: SnCategory[] }>(`/api/chatbots/${bot}/servicenow/categories`);
  const error = links.error || cats.error;

  const groups = useMemo(() => {
    const m = new Map<string, SnLink[]>();
    for (const l of [...(links.data ?? [])].sort((a, b) => a.id - b.id)) m.set(l.url, [...(m.get(l.url) ?? []), l]);
    return [...m].map(([url, ls]) => ({ url, links: ls }));
  }, [links.data]);
  const problems = groups.filter((g) => g.links.some((l) => l.error));   // the error stays set while a re-check runs
  const healthy = groups.filter((g) => !problems.includes(g));
  const checked = healthy.filter((g) => g.links.some((l) => l.last_checked_at && now - new Date(l.last_checked_at).getTime() < DAY)).length;
  const ql = q.toLowerCase().trim();
  const shown = healthy.filter((g) => !ql || [title(g), g.url, ...g.links.map((l) => l.category ?? "")].some((s) => s.toLowerCase().includes(ql)));

  const call = async (fn: () => Promise<unknown>, done?: string) => {
    try {
      await fn();
      if (done) toast(done);
    } catch (e) { toast((e as Error).message, true); } finally { links.reload(); }
  };
  const del = (ids: number[]) => Promise.all(ids.map((id) => api(`/api/servicenow/links/${id}`, { method: "DELETE" })));
  const row = (g: Group) => <Row key={g.url} g={g} call={call} del={del} onAdd={() => setAdding(g)} onRemove={() => setRemoving(g)} />;

  return (
    <Page>
      <PageHeader title="Web pages" description="When one of these pages changes, the AI suggests updates to the articles in its categories."
        actions={cats.data?.categories.length ? <Button variant="primary" onClick={() => setAdding("new")}><Plus className="size-3.5" /> Add a web page</Button> : null} />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!links.data || !cats.data ? (!error && <Loading />) : cats.data.categories.length === 0 ? (
        <Card><Empty icon={<Globe className="size-5" />} title="Nothing imported yet">Web pages can be added once the knowledge base is imported.</Empty></Card>
      ) : groups.length === 0 ? (
        <Card><Empty icon={<Globe className="size-5" />} title="No web pages yet" action={<Button variant="primary" onClick={() => setAdding("new")}><Plus className="size-3.5" /> Add a web page</Button>}>Add the pages your articles are based on.</Empty></Card>
      ) : (
        <>
          {problems.map((g) => (
            <div key={g.url} className="mb-3 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
              <AlertCircle className="mt-0.5 size-5 shrink-0 text-red-600" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">{title(g)} can&apos;t be read</p>
                <p className="truncate text-xs text-muted">{shortUrl(g.url)}</p>
                <p className="mt-1 text-[13px] text-red-700">{g.links.find((l) => l.error)?.error}</p>
                <Chips g={g} call={call} del={del} onAdd={() => setAdding(g)} />
              </div>
              <a href={g.url} target="_blank" rel="noreferrer"><Button>Open page ↗</Button></a>
              <Button onClick={() => setMoving(g)}>Change address</Button>
              <Menu g={g} call={call} onRemove={() => setRemoving(g)} />
            </div>
          ))}
          {checked > 0 && <p className="mb-4 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-[13px] text-green-800">✓ <b>{plural(checked, "page")}</b> checked in the last 24 hours. All fine.</p>}
          {healthy.length > 0 && (
            <>
              <div className="relative mb-3 w-72">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
                <input className={cn(inputCls, "pl-9")} placeholder="Find a page or category" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <Card className="divide-y divide-line">
                {shown.map(row)}
                {shown.length === 0 && <p className="px-5 py-8 text-center text-sm text-muted">No page matches.</p>}
              </Card>
            </>
          )}
        </>
      )}
      {adding && <AddPage bot={bot} cats={cats.data?.categories ?? []} group={adding === "new" ? null : adding} onClose={() => setAdding(null)} onDone={() => { setAdding(null); links.reload(); }} />}
      {moving && <ChangeAddress bot={bot} g={moving} del={del} onClose={() => setMoving(null)} onDone={() => { setMoving(null); links.reload(); }} />}
      {removing && (
        <Modal title="Remove this web page?" onClose={() => setRemoving(null)} footer={<><Button onClick={() => setRemoving(null)}>Cancel</Button><Button variant="danger" onClick={() => { const g = removing; setRemoving(null); call(() => del(g.links.map((l) => l.id)), "Web page removed"); }}>Remove</Button></>}>
          <p className="text-sm text-muted">{shortUrl(removing.url)} will no longer be checked for {plural(removing.links.length, "category", "categories")}. Articles already made from it stay as they are.</p>
        </Modal>
      )}
    </Page>
  );
}

type Call = (fn: () => Promise<unknown>, done?: string) => Promise<void>;

function Row({ g, call, del, onAdd, onRemove }: { g: Group; call: Call; del: (ids: number[]) => Promise<unknown>; onAdd: () => void; onRemove: () => void }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 truncate text-[13px] font-medium">{busy(g) && <Loader2 className="size-3.5 animate-spin text-blue-600" />}{title(g)}</p>
        <p className="truncate text-xs text-muted">{shortUrl(g.url)}</p>
        <Chips g={g} call={call} del={del} onAdd={onAdd} />
      </div>
      <Menu g={g} call={call} onRemove={onRemove} />
    </div>
  );
}

function Chips({ g, call, del, onAdd }: { g: Group; call: Call; del: (ids: number[]) => Promise<unknown>; onAdd: () => void }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {g.links.map((l) => (
        <span key={l.id} className="inline-flex items-center gap-1 rounded-full bg-neutral-100 py-0.5 pl-2.5 pr-1 text-xs">
          {l.category?.split(" > ").slice(-2).join(" › ") ?? "?"}
          {/* the last category is removed with Remove, which asks first */}
          {g.links.length > 1 && <button aria-label={`Remove ${l.category}`} onClick={() => call(() => del([l.id]), "Category removed")} className="rounded-full p-0.5 text-neutral-400 hover:bg-neutral-200 hover:text-ink"><X className="size-3" /></button>}
        </span>
      ))}
      <button onClick={onAdd} className="rounded-full border border-dashed border-line px-2.5 py-0.5 text-xs text-muted hover:text-ink">+ Category</button>
    </div>
  );
}

function Menu({ g, call, onRemove }: { g: Group; call: Call; onRemove: () => void }) {
  const first = g.links[0];
  const item = "block w-full rounded-lg px-2.5 py-1.5 text-left hover:bg-neutral-100 disabled:opacity-40";
  const check = (audit: boolean) => call(() => api(`/api/servicenow/links/${first.id}/check`, { body: { audit } }),
    audit ? "The AI is comparing the articles with the page. Its suggestions appear in To do." : "Checking the page now.");
  return (
    <details className="relative">
      <summary aria-label="More" className="flex h-8 cursor-pointer list-none items-center rounded-[10px] px-2 hover:bg-neutral-100"><MoreHorizontal className="size-4" /></summary>
      <div className="absolute right-0 z-30 mt-1 w-60 rounded-xl border border-line bg-white p-1 text-[13px] shadow-lg">
        <button disabled={busy(g)} onClick={() => check(false)} className={item}>Check now</button>
        <button disabled={busy(g) || !first.last_checked_at} onClick={() => check(true)} className={item}>Compare with the articles</button>
        <label className="flex items-center gap-2 whitespace-nowrap px-2.5 py-1.5">Check every
          <select className="h-7 flex-1 rounded-lg border border-line bg-white px-1 text-xs" value={String(first.schedule_hours ?? "")}
            onChange={(e) => { const v = e.target.value; call(() => Promise.all(g.links.map((l) => api(`/api/servicenow/links/${l.id}`, { method: "PATCH", body: { set_schedule: true, schedule_hours: v ? Number(v) : null } }))), "Schedule saved"); }}>
            {SCHEDULES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            {!SCHEDULES.some((s) => s.value === String(first.schedule_hours ?? "")) && <option value={String(first.schedule_hours)}>{first.schedule_hours} hours</option>}
          </select>
        </label>
        <a href={g.url} target="_blank" rel="noreferrer" className={item}>Open page ↗</a>
        <button onClick={onRemove} className={cn(item, "text-red-600")}>Remove</button>
      </div>
    </details>
  );
}

/** Adds one link per ticked category: for a new page (group = null) or for more categories of an existing one. */
function AddPage({ bot, cats, group, onClose, onDone }: { bot: string; cats: SnCategory[]; group: Group | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState(group?.url ?? "");
  const [q, setQ] = useState("");
  const [showEmpty, setShowEmpty] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const have = new Set(group?.links.map((l) => l.category_id));
  const ql = q.toLowerCase().trim();
  const list = cats.filter((c) => !have.has(c.id) && (showEmpty || c.total > 0 || picked.includes(c.id)) && (!ql || c.path.toLowerCase().includes(ql)));
  const save = async () => {
    setBusy(true);
    setErr("");
    let n = 0;
    try {
      for (const id of picked) {
        await api(`/api/chatbots/${bot}/servicenow/links`, { body: { category_id: id, url } });
        n++;
      }
      toast(group ? "Category added" : "Web page added. Reading it now.");
      onDone();
    } catch (e) {
      setErr(`${(e as Error).message}${n ? ` (${plural(n, "category", "categories")} added before this)` : ""}`);
      setPicked(picked.slice(n));
    } finally { setBusy(false); }
  };
  return (
    <Modal title={group ? `Add categories to ${shortUrl(group.url)}` : "Add a web page"} width="max-w-lg" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!url.trim() || !picked.length} onClick={save}>Add</Button></>}>
      {!group && (
        <>
          <Label>Web address</Label>
          <input autoFocus className={inputCls} placeholder="https://www.depts.ttu.edu/…" value={url} onChange={(e) => setUrl(e.target.value)} />
          <div className="h-3" />
        </>
      )}
      <Label>Categories it keeps up to date</Label>
      <input autoFocus={!!group} className={inputCls} placeholder="Find a category" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="mt-2 max-h-64 overflow-y-auto rounded-xl border border-line">
        {list.map((c) => (
          <label key={c.id} className="flex items-center gap-2 px-3 py-1.5 text-[13px] hover:bg-subtle">
            <input type="checkbox" checked={picked.includes(c.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} />
            <span className="min-w-0 flex-1 truncate">{c.path}</span>
            <span className="text-xs text-muted">{c.total || ""}</span>
          </label>
        ))}
        {list.length === 0 && <p className="px-3 py-4 text-center text-[13px] text-muted">No category matches.</p>}
      </div>
      <label className="mt-2 flex items-center gap-2 text-[13px] text-neutral-600"><input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} /> Show empty categories</label>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}

/** A new address = add it to the same categories, then remove the old links. */
function ChangeAddress({ bot, g, del, onClose, onDone }: { bot: string; g: Group; del: (ids: number[]) => Promise<unknown>; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState(g.url);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      for (const l of g.links) await api(`/api/chatbots/${bot}/servicenow/links`, { body: { category_id: l.category_id, url, article_id: l.article_id, label: l.label, set_schedule: true, schedule_hours: l.schedule_hours } });
      await del(g.links.map((l) => l.id));   // only once every new link exists, so a failure loses nothing
      toast("Address changed. Reading the page now.");
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Change the address" width="max-w-lg" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!url.trim() || url.trim() === g.url} onClick={save}>Save</Button></>}>
      <Label>New web address</Label>
      <input autoFocus className={inputCls} value={url} onChange={(e) => setUrl(e.target.value)} />
      <p className="mt-2 text-xs text-muted">The page stays on its {plural(g.links.length, "category", "categories")}. The first read only records the new page.</p>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
