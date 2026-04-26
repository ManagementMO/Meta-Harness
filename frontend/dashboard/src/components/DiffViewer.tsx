'use client';
import { DiffEditor } from '@monaco-editor/react';

export function DiffViewer({ diff }: { diff: string }) {
  // Parse the unified diff to extract original and modified content
  const lines = diff.split('\n');
  const original: string[] = [];
  const modified: string[] = [];

  for (const line of lines) {
    if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) continue;
    if (line.startsWith('-')) {
      original.push(line.slice(1));
    } else if (line.startsWith('+')) {
      modified.push(line.slice(1));
    } else {
      original.push(line.startsWith(' ') ? line.slice(1) : line);
      modified.push(line.startsWith(' ') ? line.slice(1) : line);
    }
  }

  return (
    <DiffEditor
      height="100%"
      language="python"
      original={original.join('\n')}
      modified={modified.join('\n')}
      theme="vs-dark"
      options={{
        readOnly: true,
        renderSideBySide: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        fontSize: 12,
        fontFamily: "'JetBrains Mono', monospace",
        lineNumbers: 'on',
        renderOverviewRuler: false,
        overviewRulerBorder: false,
        scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
      }}
    />
  );
}
