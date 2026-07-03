export default function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded border border-dashed border-wire/30 px-6 py-14 text-center">
      <p className="font-mono text-xs tracking-[0.15em] text-wire">NO SIGNAL</p>
      <p className="mt-3 text-[15px] leading-relaxed text-paper/70">{children}</p>
    </div>
  );
}
