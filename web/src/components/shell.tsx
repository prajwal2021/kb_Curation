"use client";
import { BookOpenCheck, Check, ChevronDown, ChevronsUpDown, Globe, History, Info, ListChecks, LogOut, Plus, Settings, UserRound, Users } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, inputCls, Label, Modal, useToast } from "./ui";

type Bot = { key: string; name: string; description: string; waiting: number; sn_waiting?: number };

const NAV: { group?: string; items: { href: string; label: string; icon: typeof Globe; badge?: "web" | "sn"; exact?: boolean }[] }[] = [
  // Previous architecture, hidden for now:
  /*
  { items: [{ href: "", label: "Overview", icon: LayoutDashboard }] },
  { group: "Collect", items: [
    { href: "/sources", label: "Sources", icon: Globe },
    { href: "/pages", label: "Pages", icon: Files },
    { href: "/changes", label: "Changes", icon: GitCompareArrows },
  ] },
  { group: "Curate", items: [
    { href: "/scope", label: "Ryan's KB", icon: Target },
    { href: "/review", label: "Review", icon: ListChecks, badge: "web" },
    { href: "/publish", label: "Publish", icon: Rocket },
  ] },
  { group: "Deliver", items: [
    { href: "/kb", label: "Knowledge base", icon: BookOpenCheck },
    { href: "/document", label: "Document", icon: FileText },
  ] },
  */
  { items: [
    { href: "/servicenow", label: "To do", icon: ListChecks, badge: "sn", exact: true },
    { href: "/servicenow/kb", label: "Knowledge base", icon: BookOpenCheck },
    { href: "/servicenow/web-pages", label: "Web pages", icon: Globe },
    { href: "/history", label: "History", icon: History },
  ] },
];

export function useBot(): string {
  return useParams<{ bot: string }>().bot;
}

export function Shell({ children }: { children: ReactNode }) {
  const bot = useBot();
  const path = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { data: bots, reload } = useApi<Bot[]>("/api/chatbots", 8000);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [meOpen, setMeOpen] = useState(false);
  const meMenu = useRef<HTMLDivElement>(null);
  const { data: me } = useApi<{ name: string; is_admin: boolean }>("/api/me");
  const menu = useRef<HTMLDivElement>(null);
  const current = bots?.find((b) => b.key === bot);

  const logout = async () => {
    try { await api("/api/logout", { body: {} }); } catch { /* signed out already: still go to the login page */ }
    router.replace("/login");
  };
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false);
      if (meMenu.current && !meMenu.current.contains(e.target as Node)) setMeOpen(false);
    };
    window.addEventListener("mousedown", h);
    return () => window.removeEventListener("mousedown", h);
  }, []);

  return (
    <div className="flex h-full">
      <aside className="flex w-[244px] shrink-0 flex-col border-r border-line bg-[#fafafa]">
        <div className="flex items-center gap-2.5 px-4 pb-3 pt-4">
          <div className="flex size-7 items-center justify-center rounded-lg bg-ink text-white"><BookOpenCheck className="size-4" /></div>
          <span className="text-[15px] font-semibold tracking-tight">KB Curation</span>
        </div>

        <div className="relative px-3 pb-2" ref={menu}>
          <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-white px-2.5 py-2 text-left hover:border-neutral-300">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-neutral-100 text-xs font-semibold">{(current?.name ?? bot).replace(/^TTU /, "").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase()}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium">{current?.name ?? bot}</span>
              <span className="block text-[11px] text-muted">Chatbot</span>
            </span>
            <ChevronsUpDown className="size-3.5 text-neutral-400" />
          </button>
          {open && (
            <div className="rise absolute left-3 right-3 top-full z-30 mt-1 rounded-xl border border-line bg-white p-1 shadow-lg">
              {bots?.map((b) => (
                <button key={b.key} onClick={() => { setOpen(false); router.push(`/${b.key}/servicenow`); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-neutral-100">
                  <span className="flex-1 truncate font-medium">{b.name}</span>
                  {!!b.sn_waiting && <span className="text-xs tabular-nums text-muted">{b.sn_waiting}</span>}
                  {b.key === bot && <Check className="size-3.5" />}
                </button>
              ))}
              {me?.is_admin && <>
                <div className="my-1 border-t border-line" />
                <button onClick={() => { setOpen(false); setAdding(true); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-neutral-600 hover:bg-neutral-100">
                  <Plus className="size-3.5" /> New chatbot
                </button>
              </>}
            </div>
          )}
        </div>

        <nav className="scroll-thin flex-1 overflow-y-auto px-3 pb-3">
          {NAV.map((g, gi) => (
            <div key={gi} className="mt-3">
              {g.group && <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{g.group}</div>}
              {g.items.map((it) => {
                const href = `/${bot}${it.href}`;
                const active = it.href === "" || it.exact ? path === href : path.startsWith(href);
                const count = it.badge === "web" ? current?.waiting : it.badge === "sn" ? current?.sn_waiting : 0;
                return (
                  <Link key={it.href} href={href} className={cn("mb-0.5 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-colors", active ? "bg-neutral-200/70 text-ink" : "text-neutral-600 hover:bg-neutral-200/40 hover:text-ink")}>
                    <it.icon className="size-4" strokeWidth={1.8} />
                    <span className="flex-1">{it.label}</span>
                    {!!count && <span className="rounded-full bg-ink px-1.5 py-px text-[11px] font-medium tabular-nums text-white">{count > 999 ? "999+" : count}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
          {me?.is_admin && (
            <Link href={`/${bot}/users`} className={cn("mb-0.5 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-colors", path.startsWith(`/${bot}/users`) ? "bg-neutral-200/70 text-ink" : "text-neutral-600 hover:bg-neutral-200/40 hover:text-ink")}>
              <Users className="size-4" strokeWidth={1.8} /> Users
            </Link>
          )}
        </nav>

        <Link href={`/${bot}/servicenow/how-it-works`} className={cn("mx-3 mb-2 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium", path.endsWith("/how-it-works") ? "bg-neutral-200/70 text-ink" : "text-neutral-500 hover:bg-neutral-200/40 hover:text-ink")}>
          <Info className="size-4" strokeWidth={1.8} /> How it works
        </Link>

        <div className="relative border-t border-line p-3" ref={meMenu}>
          {meOpen && (
            <div className="rise absolute bottom-full left-3 right-3 z-30 mb-1 rounded-xl border border-line bg-white p-1 shadow-lg">
              <Link href={`/${bot}/settings`} onClick={() => setMeOpen(false)} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[13px] hover:bg-neutral-100">
                <Settings className="size-3.5" /> Settings
              </Link>
              <button onClick={logout} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-neutral-100">
                <LogOut className="size-3.5" /> Log out
              </button>
            </div>
          )}
          <button onClick={() => setMeOpen((o) => !o)} aria-expanded={meOpen} className={cn("flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] hover:bg-neutral-200/40", path.endsWith("/settings") && "bg-neutral-200/70")}>
            <span className="flex size-6 items-center justify-center rounded-full bg-neutral-200 text-neutral-600"><UserRound className="size-3.5" /></span>
            <span className="min-w-0 flex-1 truncate font-medium">{me?.name}</span>
            <ChevronDown className="size-3.5 text-neutral-400" />
          </button>
        </div>
      </aside>

      <main className="scroll-thin min-w-0 flex-1 overflow-y-auto">{children}</main>

      {adding && <NewBot onClose={() => setAdding(false)} onDone={(k) => { setAdding(false); reload(); router.push(`/${k}/servicenow`); toast("Chatbot created."); }} />}
    </div>
  );
}

function NewBot({ onClose, onDone }: { onClose: () => void; onDone: (key: string) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    try {
      const r = await api<{ key: string }>("/api/chatbots", { body: { name, urls: [] } });
      onDone(r.key);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="New chatbot" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!name.trim()} onClick={save}>Create chatbot</Button></>}>
      <p className="mb-4 text-sm text-muted">Each chatbot has its own ServiceNow knowledge base, review queue and published versions.</p>
      <Label>Name</Label>
      <input autoFocus className={inputCls} placeholder="e.g. TTU Graduate School" value={name} onChange={(e) => setName(e.target.value)} />
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
