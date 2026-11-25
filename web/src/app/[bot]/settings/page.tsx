"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, inputCls, Label, Page, PageHeader, useToast } from "@/components/ui";

function PasswordCard() {
  const toast = useToast();
  const [pw, setPw] = useState({ current: "", next: "", again: "" });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof pw) => (e: React.ChangeEvent<HTMLInputElement>) => setPw({ ...pw, [k]: e.target.value });
  const mismatch = pw.again.length > 0 && pw.again !== pw.next;
  const ready = pw.current && pw.next.length >= 8 && pw.next === pw.again;
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/api/me/password", { body: { current: pw.current, new: pw.next } });
      setPw({ current: "", next: "", again: "" });
      toast("Password changed. Other devices were signed out.");
    } catch (err) { toast((err as Error).message, true); } finally { setBusy(false); }
  };
  return (
    <Card className="max-w-md p-5">
      <h2 className="mb-1 text-sm font-semibold">Your password</h2>
      <p className="mb-4 text-[13px] text-muted">At least 8 characters. Changing it signs you out on your other devices.</p>
      <form onSubmit={save}>
        <Label>Current password</Label>
        <input type="password" autoComplete="current-password" className={inputCls} value={pw.current} onChange={set("current")} />
        <div className="h-3" />
        <Label>New password</Label>
        <input type="password" autoComplete="new-password" className={inputCls} value={pw.next} onChange={set("next")} />
        <div className="h-3" />
        <Label>New password again</Label>
        <input type="password" autoComplete="new-password" className={inputCls} value={pw.again} onChange={set("again")} />
        {mismatch && <p className="mt-2 text-sm text-red-600">The new passwords don&rsquo;t match.</p>}
        <Button type="submit" variant="primary" busy={busy} disabled={!ready} className="mt-4">Change password</Button>
      </form>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <Page>
      <PageHeader title="Settings" description="Your account." />
      <PasswordCard />
    </Page>
  );
}

// Previous architecture, hidden for now: categories of the website crawl (its pages are hidden in the sidebar too).
// To bring it back, restore these imports:
//   import { Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
//   import { useApi, type Category } from "@/lib/api";
//   import { useBot } from "@/components/shell";
//   ErrorNote, Loading, Modal from "@/components/ui";   import { cn, DOT } from "@/lib/utils";
/*
type Cats = { categories: Category[]; uncategorized: { total: number; waiting: number }; ai: boolean };

function CategorySettings() {
  const bot = useBot();
  const toast = useToast();
  const { data, error, reload } = useApi<Cats>(`/api/chatbots/${bot}/categories`);
  const [edit, setEdit] = useState<Partial<Category> | null>(null);
  const [busy, setBusy] = useState(false);
  const refile = async () => {
    if (!confirm("Ask the AI to re-file every entry that is still waiting as New?\n\nEntries a reviewer has already edited or approved are not touched. This can take a minute or two.")) return;
    setBusy(true);
    try {
      const r = await api<{ entries: number; moved: number }>(`/api/chatbots/${bot}/recategorize`, { body: {} });
      toast(`${r.entries.toLocaleString()} entries checked, ${r.moved.toLocaleString()} moved to a better category`);
      reload();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };

  const remove = async (c: Category) => {
    if (!confirm(`Delete the category “${c.name}”?`)) return;
    try { await api(`/api/categories/${c.id}`, { method: "DELETE" }); reload(); } catch (e) { toast((e as Error).message, true); }
  };

  return (
    <Page>
      <PageHeader title="Settings" description="Categories group content for review and the knowledge base." actions={<><Button busy={busy} onClick={refile}>{!busy && <Sparkles className="size-4" />} Re-file waiting entries with AI</Button><Button variant="primary" onClick={() => setEdit({ name: "", description: "", keywords: [], color: "blue" })}><Plus className="size-4" /> New category</Button></>} />
      {data && <p className="-mt-2 mb-4 text-[13px] text-muted">{data.ai ? "AI filing is on: new content is filed by an AI model using each category's description. Keywords are the fallback." : "AI filing is off: new content is filed by keywords only."}</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
      {!data ? <Loading /> : (
        <Card className="overflow-hidden">
          <table className="w-full text-left text-[13px]">
            <thead className="border-b border-line bg-subtle text-xs text-muted">
              <tr><th className="py-2.5 pl-5 pr-3 font-medium">Category</th><th className="px-3 font-medium">Keywords used for automatic filing</th><th className="w-24 px-3 font-medium">Entries</th><th className="w-24 px-3 font-medium">To review</th><th className="w-20" /></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.categories.map((c) => (
                <tr key={c.id} className="align-top hover:bg-subtle">
                  <td className="py-3 pl-5 pr-3">
                    <p className="flex items-center gap-2 font-medium"><span className={cn("size-2.5 rounded-full", DOT[c.color])} />{c.name}</p>
                    <p className="mt-0.5 pl-[18px] text-xs text-muted">{c.description}</p>
                  </td>
                  <td className="px-3 py-3"><div className="flex flex-wrap gap-1">{c.keywords.slice(0, 9).map((k) => <span key={k} className="rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-600">{k}</span>)}{c.keywords.length > 9 && <span className="text-[11px] text-neutral-400">+{c.keywords.length - 9}</span>}</div></td>
                  <td className="px-3 py-3 tabular-nums">{c.total}{c.also > 0 && <span className="text-neutral-400"> +{c.also}</span>}</td>
                  <td className="px-3 py-3 tabular-nums">{c.waiting || <span className="text-neutral-300">0</span>}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex justify-end gap-1 pr-2">
                      <button aria-label="Edit" onClick={() => setEdit(c)} className="rounded-lg p-1.5 text-neutral-400 hover:bg-neutral-100 hover:text-ink"><Pencil className="size-3.5" /></button>
                      <button aria-label="Delete" onClick={() => remove(c)} className="rounded-lg p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.uncategorized.total > 0 && <p className="border-t border-line bg-amber-50 px-5 py-2.5 text-xs text-amber-900">{data.uncategorized.total} entries have no category yet. Open Review → Uncategorized to file them.</p>}
        </Card>
      )}
      <PasswordCard />
      {edit && <EditCategory bot={bot} cat={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </Page>
  );
}

function EditCategory({ bot, cat, onClose, onDone }: { bot: string; cat: Partial<Category>; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(cat.name ?? "");
  const [description, setDescription] = useState(cat.description ?? "");
  const [keywords, setKeywords] = useState((cat.keywords ?? []).join(", "));
  const [color, setColor] = useState(cat.color ?? "blue");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const body = { name, description, color, keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean) };
    try {
      await api(cat.id ? `/api/categories/${cat.id}` : `/api/chatbots/${bot}/categories`, { method: cat.id ? "PATCH" : "POST", body });
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title={cat.id ? "Edit category" : "New category"} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!name.trim()} onClick={save}>Save</Button></>}>
      <Label>Name</Label>
      <input autoFocus className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Financial Aid" />
      <div className="h-3" />
      <Label>What belongs here</Label>
      <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="One line that tells reviewers what to file here" />
      <div className="h-3" />
      <Label>Keywords (comma separated)</Label>
      <textarea className="h-20 w-full resize-none rounded-[10px] border border-line p-2.5 text-sm outline-none focus:border-neutral-400" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="scholarship, fafsa, grant" />
      <div className="h-3" />
      <Label>Colour</Label>
      <div className="flex gap-2">{Object.keys(DOT).map((c) => <button key={c} aria-label={c} onClick={() => setColor(c)} className={cn("size-6 rounded-full ring-offset-2", DOT[c], color === c && "ring-2 ring-ink")} />)}</div>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
*/
