"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useBot } from "@/components/shell";
import { ArticleForm } from "@/components/article-form";
import { Page, PageHeader } from "@/components/ui";

export default function NewArticlePage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const category = Number(useSearchParams().get("category")) || null;
  return (
    <Page wide>
      <p className="mb-4 text-[13px] text-muted"><Link href={`/${bot}/servicenow/kb`} className="hover:text-ink">Knowledge base</Link> / <span className="text-ink">Create an article</span></p>
      <PageHeader title="Create an article" description="Write it the way a student or parent would ask it." />
      <ArticleForm bot={bot} category={category} />
    </Page>
  );
}
