import { cn } from "@/lib/cn";

export type BadgeTone = "moss" | "ember" | "sand" | "iris" | "frost" | "neutral";

const TONES: Record<BadgeTone, string> = {
  moss: "text-moss bg-moss/10 border-moss/25",
  ember: "text-ember bg-ember/10 border-ember/25",
  sand: "text-sand bg-sand/10 border-sand/25",
  iris: "text-iris bg-iris/10 border-iris/25",
  frost: "text-frost bg-frost/10 border-frost/30",
  neutral: "text-ink-mid bg-white/[0.04] border-white/10",
};

/** Whisper-toned status chip. Semantic hues stay quiet until they matter. */
export function Badge({
  label,
  tone = "neutral",
  className,
}: {
  label: string;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center h-[18px] px-1.5 rounded-[5px] border font-mono text-[10px] uppercase tracking-[0.08em] leading-none whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {label}
    </span>
  );
}
