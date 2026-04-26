'use client';

type FilterBarProps<T extends string> = {
  filters: readonly T[];
  active: T;
  onSelect: (f: T) => void;
};

export function FilterBar<T extends string>({ filters, active, onSelect }: FilterBarProps<T>) {
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
