"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi } from "@/lib/api";
import type { SnArticleDetail } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { ArticleForm } from "@/components/article-form";
import { ErrorNote, Loading, Page, PageHeader } from "@/components/ui";

export default function EditArticlePage() {
  const bot = useBot();
  const id = Number(useParams<{ id: string }>().id);
  const { data: a, error } = useApi<SnArticleDetail>(`/api/servicenow/articles/${id}`);
  if (error) return <Page><ErrorNote>{error}</ErrorNote></Page>;
  if (!a) return <Page><Loading /></Page>;
  return (
    <Page wide>
      <p className="mb-4 text-[13px] text-muted"><Link href={`/${bot}/servicenow/article/${a.id}`} className="hover:text-ink">← {a.title}</Link></p>
      <PageHeader title="Edit the article" description={a.status === "published" ? "Your change is saved as a draft next to the published text." : "Change the text, category or flags."} />
      <ArticleForm bot={bot} article={a} />
    </Page>
  );
}
