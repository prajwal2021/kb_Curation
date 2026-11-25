"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import type { SnArticleDetail, SnCategory } from "@/lib/sn";
import { Badge, Button, Card, inputCls, Label, useToast } from "./ui";
import { cn } from "@/lib/utils";

/** Create (no `article`) or edit an article: title, category, text and flags. */
export function ArticleForm({ bot, article, category }: { bot: string; article?: SnArticleDetail; category?: number | null }) {
  const router = useRouter();
  const toast = useToast();
  const cats = useApi<{ categories: SnCategory[] }>(`/api/chatbots/${bot}/servicenow/categories`);
  const flagList = useApi<string[]>(`/api/chatbots/${bot}/servicenow/flags`);
  const start = { title: article?.title ?? "", content: article?.content ?? "", category_id: String(article?.category_id ?? category ?? ""), flags: article?.flags ?? [] };
  const [f, setF] = useState(start);
  const [newFlag, setNewFlag] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const allFlags = [...new Set([...(flagList.data ?? []), ...f.flags])];
  const published = article?.status === "published";
  // a draft article, or a published one whose change would be (or is) a draft, can be sent for review straight away
  const canSend = !!article && (article.status === "draft" || (published && article.p_stage !== "review"));
  const back = article ? `/${bot}/servicenow/article/${article.id}` : `/${bot}/servicenow/kb`;

  const addFlag = () => {
    const n = newFlag.trim();
    const known = allFlags.find((x) => x.toLowerCase() === n.toLowerCase()) ?? n;   // "internal only" ticks "Internal only"
    if (n && !f.flags.includes(known)) setF({ ...f, flags: [...f.flags, known] });
    setNewFlag("");
  };
  const create = async (review: boolean) => {
    setBusy(review ? "review" : "draft");
    try {
      const a = await api<SnArticleDetail>(`/api/chatbots/${bot}/servicenow/articles`, {
        body: { title: f.title, content: f.content, category_id: f.category_id ? Number(f.category_id) : null, flags: f.flags, review },
      });
      toast(review ? "Sent for review" : "Saved as a draft");
      router.push(`/${bot}/servicenow/article/${a.id}`);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const save = async (send: boolean) => {
    if (!article) return;
    // send only what changed: ticking a flag on a published article must not open a draft change
    const body: Record<string, unknown> = {};
    if (f.title !== start.title) body.title = f.title;
    if (f.content !== start.content) body.content = f.content;
    if (f.category_id !== start.category_id) body.category_id = f.category_id ? Number(f.category_id) : null;
    if (f.flags.join("\n") !== start.flags.join("\n")) body.flags = f.flags;
    setBusy(send ? "send" : "save");
    try {
      let a = Object.keys(body).length ? await api<SnArticleDetail>(`/api/servicenow/articles/${article.id}`, { method: "PATCH", body }) : article;
      if (send && (a.status === "draft" || a.p_stage === "draft")) a = await api<SnArticleDetail>(`/api/servicenow/articles/${article.id}/send_for_review`, { body: { note: "" } });
      toast(send ? "Saved and sent for review" : "Saved");
      router.push(`/${bot}/servicenow/article/${a.id}`);
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };

  return (
    <div className="grid grid-cols-[1fr_280px] items-start gap-6">
      <div className="min-w-0 space-y-4">
        <div><Label>Question or title</Label><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></div>
        <div>
          <Label>Category</Label>
          <select className={inputCls} value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}>
            <option value="">No category</option>
            {cats.data?.categories.map((c) => <option key={c.id} value={c.id}>{c.path}</option>)}
          </select>
        </div>
        <div>
          <Label>Article</Label>
          <textarea className="h-[360px] w-full rounded-[10px] border border-line p-3 font-mono text-[12.5px] leading-relaxed outline-none focus:border-neutral-400" value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} />
          <p className="mt-1 text-xs text-muted">One item per line: “## ” headings, “- ” bullets, “1. ” steps, “a | b” table rows, [text](url) links. Keep image lines as they are.</p>
        </div>
        <div>
          <Label>Flags <span className="font-normal text-muted">(optional)</span></Label>
          <Card className="px-4 py-3">
            <div className="flex flex-wrap gap-x-5 gap-y-1.5">
              {allFlags.map((x) => (
                <label key={x} className="flex items-center gap-1.5 text-[13px]">
                  <input type="checkbox" checked={f.flags.includes(x)} onChange={() => setF({ ...f, flags: f.flags.includes(x) ? f.flags.filter((y) => y !== x) : [...f.flags, x] })} />{x}
                </label>
              ))}
            </div>
            <form className="mt-2.5 flex gap-2" onSubmit={(e) => { e.preventDefault(); addFlag(); }}>
              <input className={cn(inputCls, "h-8 max-w-64 text-[13px]")} placeholder="New flag, e.g. “Expired”" maxLength={40} value={newFlag} onChange={(e) => setNewFlag(e.target.value)} />
              <Button size="sm" type="submit" disabled={!newFlag.trim()}>Add to the list</Button>
            </form>
          </Card>
          <p className="mt-1 text-xs text-muted">A flag you add joins the checklist for every article.</p>
        </div>
        <div className="flex justify-end gap-2 border-t border-line pt-4">
          <Link href={back}><Button>Cancel</Button></Link>
          {article ? <>
            <Button variant={canSend ? "secondary" : "primary"} busy={busy === "save"} onClick={() => save(false)}>Save</Button>
            {canSend && <Button variant="primary" busy={busy === "send"} onClick={() => save(true)}>Save and send for review</Button>}
          </> : <>
            <Button busy={busy === "draft"} onClick={() => create(false)}>Save as draft</Button>
            <Button variant="primary" busy={busy === "review"} onClick={() => create(true)}>Send for review</Button>
          </>}
        </div>
      </div>
      <Card className="sticky top-8 p-5 text-[13px]">
        <p className="mb-2 font-semibold">What happens next</p>
        {published ? <p className="text-neutral-700">The published text stays live until this change is published.</p> : (
          <ol className="list-decimal space-y-2 pl-4 text-neutral-700">
            <li><Badge>Draft</Badge> until you send it for review.</li>
            <li><Badge tone="amber">In review</Badge> A reviewer publishes it or sends it back.</li>
            <li><Badge tone="green">Published</Badge> It&apos;s in the next release, labeled Published.</li>
          </ol>
        )}
      </Card>
    </div>
  );
}
