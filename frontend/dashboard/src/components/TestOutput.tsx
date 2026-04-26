'use client';

export function TestOutput({ output }: { output: string }) {
  const lines = output.split('\n');

  return (
    <pre className="overflow-auto text-[12px] leading-[1.7] font-mono">
      {lines.map((line, i) => {
        let color = 'text-text-mid';
        if (line.includes('PASSED')) color = 'text-green';
        else if (line.includes('FAILED') || line.includes('Error')) color = 'text-red';
        else if (line.includes('passed')) color = 'text-green';
        else if (line.includes('failed')) color = 'text-red';

        return <div key={i} className={color}>{line}</div>;
      })}
    </pre>
  );
}
