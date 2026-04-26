type Props = { phases: { propose: boolean; validate: boolean; benchmark: boolean; frontier: boolean } };

export function PhasePipeline({ phases }: Props) {
  const items = [
    { key: 'propose', done: phases.propose },
    { key: 'validate', done: phases.validate },
    { key: 'benchmark', done: phases.benchmark },
    { key: 'frontier', done: phases.frontier },
  ];
  return (
    <div className="flex items-center gap-1 text-[9px] text-text-mid uppercase tracking-wide">
      {items.map((item, i) => (
        <span key={item.key} className="flex items-center gap-1">
          {i > 0 && <span className="text-text-ghost">{'→'}</span>}
          <span className={item.done ? 'text-cyan' : ''}>
            {item.done ? '✓' : '○'} {item.key}
          </span>
        </span>
      ))}
    </div>
  );
}
