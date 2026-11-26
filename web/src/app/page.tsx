"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useApi } from "@/lib/api";
import { Empty, ErrorNote, Loading } from "@/components/ui";

export default function Home() {
  const router = useRouter();
  const { data, error } = useApi<{ key: string }[]>("/api/chatbots");
  useEffect(() => {
    if (data?.length) router.replace(`/${data[0].key}/servicenow`);
  }, [data, router]);
  return (
    <div className="mx-auto max-w-md pt-32">
      {error ? <ErrorNote>{error}</ErrorNote> : data?.length === 0
        ? <Empty title="No knowledge base yet">You don&rsquo;t have access to any knowledge base yet. Ask an admin.</Empty>
        : <Loading />}
    </div>
  );
}
