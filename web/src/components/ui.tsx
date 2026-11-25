"use client";
import { Loader2, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn, DOT } from "@/lib/utils";
import type { Category, EntryStatus } from "@/lib/api";
import { SN_STATE, type SnState } from "@/lib/sn";

// ── Button ───────────────────────────────────────────────────────────────────
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; busy?: boolean };
export function Button({ variant = "secondary", size = "md", busy, className, children, disabled, ...p }: BtnProps) {
  return (
    <button
      {...p}
      disabled={disabled || busy}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[10px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-ink text-white hover:bg-neutral-800",
        variant === "secondary" && "border border-line bg-white text-ink hover:bg-subtle",
        variant === "ghost" && "text-neutral-600 hover:bg-neutral-100 hover:text-ink",
        variant === "danger" && "border border-red-200 bg-white text-red-600 hover:bg-red-50",
        className,
      )}
    >
      {busy && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

// ── Badge ────────────────────────────────────────────────────────────────────
const TONES = {
  neutral: "bg-neutral-100 text-neutral-700",
  green: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  red: "bg-red-50 text-red-700",
  blue: "bg-blue-50 text-blue-700",
  violet: "bg-violet-50 text-violet-700",
  outline: "border border-line text-neutral-600",
} as const;
export type Tone = keyof typeof TONES;
export function Badge({ tone = "neutral", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-xs font-medium whitespace-nowrap", TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current opacity-70" />}
      {children}
    </span>
  );
}

export const STATUS: Record<EntryStatus, { label: string; tone: Tone }> = {
  new: { label: "New", tone: "blue" },
  changed: { label: "Changed on site", tone: "amber" },
  removal: { label: "Removed from site", tone: "red" },
  approved: { label: "Approved", tone: "green" },
  rejected: { label: "Rejected", tone: "neutral" },
  removed: { label: "Removed", tone: "neutral" },
};
export const StatusBadge = ({ status }: { status: EntryStatus }) => <Badge tone={STATUS[status].tone} dot>{STATUS[status].label}</Badge>;
export const SnStateBadge = ({ status }: { status: SnState }) => <Badge tone={SN_STATE[status].tone} dot>{SN_STATE[status].label}</Badge>;

export const KIND: Record<string, { label: string; tone: Tone }> = {
  new: { label: "New page", tone: "blue" },
  changed: { label: "Updated", tone: "amber" },
  removed: { label: "Removed", tone: "red" },
  restored: { label: "Restored", tone: "green" },
  added: { label: "Added", tone: "green" },
  modified: { label: "Modified", tone: "amber" },
};
export const KindBadge = ({ kind }: { kind: string }) => <Badge tone={KIND[kind]?.tone ?? "neutral"}>{KIND[kind]?.label ?? kind}</Badge>;

export function CategoryChip({ cat, muted }: { cat?: Pick<Category, "name" | "color"> | null; muted?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap", muted ? "text-neutral-500" : "text-neutral-700")}>
      <span className={cn("size-2 rounded-full", cat ? DOT[cat.color] ?? DOT.slate : "border border-dashed border-neutral-400")} />
      {cat?.name ?? "Uncategorized"}
    </span>
  );
}

export function Stat({ added, removed }: { added: number; removed: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs tabular-nums">
      {added > 0 && <span className="text-emerald-600">+{added}</span>}
      {removed > 0 && <span className="text-red-600">−{removed}</span>}
    </span>
  );
}

// ── Layout pieces ────────────────────────────────────────────────────────────
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-2xl border border-line bg-white", className)}>{children}</div>;
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 pb-6">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={cn("mx-auto w-full px-8 py-8", wide ? "max-w-[1400px]" : "max-w-[1120px]")}>{children}</div>;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && <div className="mb-4 flex size-11 items-center justify-center rounded-xl border border-line bg-subtle text-neutral-500">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{children}</div>;
}

export function Tabs<T extends string>({ value, onChange, items, className }: { value: T; onChange: (v: T) => void; items: { value: T; label: ReactNode; count?: number }[]; className?: string }) {
  return (
    <div className={cn("inline-flex rounded-[10px] bg-neutral-100 p-0.5", className)}>
      {items.map((i) => (
        <button
          key={i.value}
          onClick={() => onChange(i.value)}
          className={cn("flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-[13px] font-medium transition-colors", value === i.value ? "bg-white text-ink shadow-sm" : "text-neutral-500 hover:text-ink")}
        >
          {i.label}
          {i.count !== undefined && <span className={cn("tabular-nums", value === i.value ? "text-neutral-500" : "text-neutral-400")}>{i.count.toLocaleString()}</span>}
        </button>
      ))}
    </div>
  );
}

export const inputCls = "h-9 w-full rounded-[10px] border border-line bg-white px-3 text-sm outline-none placeholder:text-neutral-400 focus:border-neutral-400 focus:ring-2 focus:ring-neutral-100";
export const Label = ({ children }: { children: ReactNode }) => <label className="mb-1.5 block text-[13px] font-medium text-neutral-700">{children}</label>;

// ── Modal and drawer ─────────────────────────────────────────────────────────
function useEscape(onClose: () => void) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
}

export function Modal({ title, children, onClose, footer, width = "max-w-md" }: { title: string; children: ReactNode; onClose: () => void; footer?: ReactNode; width?: string }) {
  useEscape(onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-modal className={cn("rise w-full rounded-2xl bg-white shadow-xl", width)} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-5">
          <h2 className="text-base font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-neutral-500 hover:bg-neutral-100"><X className="size-4" /></button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ title, subtitle, children, onClose }: { title: ReactNode; subtitle?: ReactNode; children: ReactNode; onClose: () => void }) {
  useEscape(onClose);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onMouseDown={onClose}>
      <div className="slidein flex h-full w-full max-w-[720px] flex-col border-l border-line bg-white shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {subtitle && <div className="mt-0.5 truncate text-[13px] text-muted">{subtitle}</div>}
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100"><X className="size-4" /></button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

// ── Toasts ───────────────────────────────────────────────────────────────────
type Toast = { id: number; text: string; bad?: boolean };
const ToastCtx = createContext<(text: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([]);
  const push = useCallback((text: string, bad?: boolean) => {
    const id = Date.now() + Math.random();
    setList((l) => [...l, { id, text, bad }]);
    setTimeout(() => setList((l) => l.filter((t) => t.id !== id)), bad ? 6000 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {list.map((t) => (
          <div key={t.id} className={cn("rise pointer-events-auto max-w-md rounded-xl px-4 py-2.5 text-sm font-medium shadow-lg", t.bad ? "bg-red-600 text-white" : "bg-ink text-white")}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
