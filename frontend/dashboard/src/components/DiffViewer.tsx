'use client';

export function DiffViewer({ diff }: { diff: string }) {
  const lines = diff.split('\n');

  return (
    <div className="overflow-auto text-[12px] leading-[1.7] font-mono">
      {lines.map((line, i) => {
        let bg = '';
        let prefix = '';
        if (line.startsWith('+') && !line.startsWith('+++')) {
          bg = 'bg-green-bg';
          prefix = 'text-green';
        } else if (line.startsWith('-') && !line.startsWith('---')) {
          bg = 'bg-red-bg';
          prefix = 'text-red';
        } else if (line.startsWith('@@')) {
          bg = 'bg-hover';
          prefix = 'text-purple';
        }

        const isHeader = line.startsWith('---') || line.startsWith('+++');

        return (
          <div key={i} className={`flex ${bg} ${isHeader ? 'text-text-mid font-semibold' : ''}`}>
            <span className="w-10 shrink-0 text-right pr-3 text-text-ghost select-none">{i + 1}</span>
            <span className={prefix ? prefix : 'text-text-mid'}>{line}</span>
          </div>
        );
      })}
    </div>
  );
}
