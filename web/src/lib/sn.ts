import type { Tone } from "@/components/ui";
import type { Change, DiffLine } from "./api";

/** Types for the ServiceNow curation section. */
export type SnState = "draft" | "review" | "published" | "pending_retirement" | "retired";
export type SnKind = "import" | "update" | "new" | "remove" | "servicenow" | "written" | "edit";
export type SnLinkStatus = "pending" | "ok" | "error" | "checking";
export type WordSeg = { t: "=" | "-" | "+"; s: string };

export type SnArticle = {
  id: number; status: SnState; p_stage: "draft" | "review" | null; flags: string[]; title: string; excerpt?: string; content?: string; category_id: number | null; category: string | null;
  number: string | null; sn_state: string | null; kb_url: string | null; kind: SnKind | null; reason: string | null;
  has_approved: boolean; edited: boolean; reviewer: string | null; reviewed_at: string | null; detected_at: string; updated_at: string;
  revision: number; link_id: number | null; event_id: number | null;
};
export type SnArticleDetail = SnArticle & {
  content: string; approved: { title: string; content: string; category_id: number | null } | null; sn_content: string | null;
  valid_to: string | null; template: string | null; sn_updated: string | null;
  diff?: DiffLine[]; added?: number; removed?: number; diff_base: "approved" | "servicenow" | null;
  link: { id: number; url: string; title: string | null } | null;
  word_diff: WordSeg[] | null; same_as_servicenow: boolean; in_release: number | null;
  pages: { id: number; url: string; title: string | null; status: SnLinkStatus }[];
  history: { id: number; action: string; actor: string; detail: Record<string, unknown>; created_at: string }[];
};
export type SnLink = {
  id: number; url: string; label: string; title: string | null; category_id: number; category: string | null; article_id: number | null;
  schedule_hours: number | null; next_run_at: string | null; last_checked_at: string | null; last_changed_at: string | null;
  status: SnLinkStatus; error: string | null; created_by: string; created_at: string;
};
export type SnCategory = {
  id: number; name: string; path: string; parent_id: number | null; active: boolean; depth: number;
  total: number; waiting: number; published: number; links: SnLink[];
};
export type SnDecision = { action: "update" | "remove" | "new" | "none"; article_id?: number; title: string; reason: string; result?: string };
export type SnEvent = {
  id: number; kind: "baseline" | "changed" | "audit" | "error"; trigger: string; actor: string; added: number; removed: number;
  summary: string; error: string | null; created_at: string; proposals: number;
  link: { id: number; url: string; title: string | null; category: string | null };
  diff?: DiffLine[]; decisions?: SnDecision[];
};
export type SnVersion = {
  id: number; number: number; note: string; created_by: string; created_at: string;
  stats: { added?: number; modified?: number; removed?: number; total?: number };
  items?: { entry_id: number; title: string; content: string; category: string; labels: string[]; number: string | null; source_url: string | null }[];
  changes?: Change[];
};
export type SnOverview = {
  imported: boolean; import: { at: string; by: string; articles: number; categories?: number } | null;
  articles: Record<SnState, number>; waiting: number; waiting_by_kind: Record<string, number>; live: number; categories: number;
  links: { total: number; error: number; checking: number };
  published: SnVersion | null; unpublished: { added: number; modified: number; removed: number }; unpublished_total: number;
  recent: SnEvent[]; ai: boolean; model: string;
};

export const SN_STATE: Record<SnState, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  review: { label: "In review", tone: "amber" },
  published: { label: "Published", tone: "green" },
  pending_retirement: { label: "Pending retirement", tone: "red" },
  retired: { label: "Retired", tone: "neutral" },
};

export const KIND_LABEL: Record<SnKind, { label: string; tone: "blue" | "amber" | "violet" | "red" }> = {
  import: { label: "From ServiceNow", tone: "blue" },
  update: { label: "AI update", tone: "amber" },
  new: { label: "New from link", tone: "violet" },
  remove: { label: "Retirement suggested", tone: "red" },   // by the AI, a person or ServiceNow
  servicenow: { label: "Changed in ServiceNow", tone: "blue" },
  written: { label: "Written here", tone: "violet" },
  edit: { label: "Edit", tone: "amber" },
};
