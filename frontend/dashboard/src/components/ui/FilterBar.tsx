'use client';

type FilterBarProps = {
  filters: string[];
  active: string;
  onSelect: (f: string) => void;
};

export function FilterBar({ filters, active, onSelect }: FilterBarProps) {
  return (
    <div className="flex gap-1.5">
      {filters.map(f => (
        <button
          key={f}
          onClick={() => onSelect(f)}
          className={`px-2.5 py-1 text-[9px] font-semibold uppercase tracking-wide rounded transition-colors ${
            active === f
              ? 'bg-active text-text-hi'
              : 'bg-hover text-text-mid hover:text-text-hi'
          }`}
        >
          {f}
        </button>
      ))}
    </div>
  );
}
