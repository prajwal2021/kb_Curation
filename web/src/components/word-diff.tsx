import type { WordSeg } from "@/lib/sn";

/** The text with removed words struck through in red and added words in green. */
export function WordDiff({ segs }: { segs: WordSeg[] }) {
  return (
    <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-neutral-800">
      {segs.map((x, i) => x.t === "=" ? <span key={i}>{x.s}</span>
        : x.t === "-" ? <del key={i} className="mx-px rounded bg-red-100 px-0.5 text-red-800">{x.s}</del>
        : <ins key={i} className="mx-px rounded bg-emerald-100 px-0.5 text-emerald-900 no-underline">{x.s}</ins>)}
    </div>
  );
}
