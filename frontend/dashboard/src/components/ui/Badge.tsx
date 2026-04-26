type BadgeProps = { label: string; color: 'green' | 'red' | 'cyan' | 'purple' | 'amber' };

const colorMap = {
  green: 'text-green bg-green-bg',
  red: 'text-red bg-red-bg',
  cyan: 'text-cyan bg-cyan-bg',
  purple: 'text-purple bg-purple-bg',
  amber: 'text-amber bg-amber/10',
};

export function Badge({ label, color }: BadgeProps) {
  return (
    <span className={`px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide rounded ${colorMap[color]}`}>
      {label}
    </span>
  );
}
