export default function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="empty-state">
      <p className="font-mono text-sm font-semibold text-signal">Your queue is clear</p>
      <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink/65">{children}</p>
    </div>
  );
}
