"use client";

import { DiffEditor, type MonacoDiffEditor } from "@monaco-editor/react";

type Monaco = Parameters<NonNullable<Parameters<typeof DiffEditor>[0]["beforeMount"]>>[0];

/** Monaco themed to the obsidian tokens exactly — never default vs-dark. */
function defineObsidianTheme(monaco: Monaco) {
  monaco.editor.defineTheme("obsidian", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "", foreground: "C9D2DD" },
      { token: "comment", foreground: "5A6473", fontStyle: "italic" },
      { token: "keyword", foreground: "8E99A8", fontStyle: "bold" },
      { token: "string", foreground: "8CA396" },
      { token: "number", foreground: "E9EDF2" },
      { token: "type", foreground: "9E9BB3" },
      { token: "function", foreground: "E9EDF2" },
      { token: "identifier", foreground: "C9D2DD" },
      { token: "delimiter", foreground: "5A6473" },
    ],
    colors: {
      "editor.background": "#080B10",
      "editor.foreground": "#C9D2DD",
      "editorLineNumber.foreground": "#39414D",
      "editorLineNumber.activeForeground": "#5A6473",
      "editor.lineHighlightBackground": "#FFFFFF06",
      "editor.selectionBackground": "#FFFFFF1C",
      "editorCursor.foreground": "#E8EEF5",
      "editorWidget.background": "#0C1016",
      "editorWidget.border": "#FFFFFF14",
      "diffEditor.insertedTextBackground": "#8CA39621",
      "diffEditor.removedTextBackground": "#B391991C",
      "diffEditor.insertedLineBackground": "#8CA39612",
      "diffEditor.removedLineBackground": "#B3919910",
      "diffEditorGutter.insertedLineBackground": "#8CA3961A",
      "diffEditorGutter.removedLineBackground": "#B3919917",
      "scrollbarSlider.background": "#FFFFFF14",
      "scrollbarSlider.hoverBackground": "#FFFFFF20",
      "scrollbarSlider.activeBackground": "#FFFFFF26",
      "editorOverviewRuler.border": "#00000000",
      "diffEditor.diagonalFill": "#FFFFFF08",
    },
  });
}

export function DiffViewer({ diff }: { diff: string }) {
  // Parse the unified diff to extract original and modified content
  const lines = diff.split("\n");
  const original: string[] = [];
  const modified: string[] = [];

  for (const line of lines) {
    if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) continue;
    if (line.startsWith("-")) {
      original.push(line.slice(1));
    } else if (line.startsWith("+")) {
      modified.push(line.slice(1));
    } else {
      original.push(line.startsWith(" ") ? line.slice(1) : line);
      modified.push(line.startsWith(" ") ? line.slice(1) : line);
    }
  }

  const lineCount = Math.max(original.length, modified.length, 8);
  const height = Math.min(Math.max(lineCount * 19 + 20, 200), 600);

  return (
    <div className="well rounded-[var(--radius-card)] overflow-hidden p-1">
      <DiffEditor
        height={`${height}px`}
        language="python"
        original={original.join("\n")}
        modified={modified.join("\n")}
        theme="obsidian"
        beforeMount={defineObsidianTheme}
        onMount={(editor: MonacoDiffEditor) => {
          void editor;
        }}
        loading={
          <div className="flex items-center justify-center h-[200px] font-mono text-[11px] text-ink-ghost">
            loading source view…
          </div>
        }
        options={{
          readOnly: true,
          renderSideBySide: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 11.5,
          fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
          lineNumbers: "on",
          renderOverviewRuler: false,
          overviewRulerBorder: false,
          scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
          padding: { top: 10, bottom: 10 },
          guides: { indentation: false },
          renderLineHighlight: "none",
          contextmenu: false,
        }}
      />
    </div>
  );
}
