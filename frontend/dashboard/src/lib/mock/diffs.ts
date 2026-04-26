export const MOCK_DIFFS: Record<string, string> = {
  "retry-on-schema-drift": `--- a/agents/base.py
+++ b/agents/retry-on-schema-drift.py
@@ -45,6 +45,18 @@ class CodingAgentHarness:
     def execute_tool_call(self, tool_name: str, args: dict) -> str:
         result = super().execute_tool_call(tool_name, args)
-        return result
+        try:
+            parsed = json.loads(result)
+            return result
+        except json.JSONDecodeError:
+            # Schema drift detected - retry with relaxed parsing
+            self.log("warn", f"Schema drift on {tool_name}, retrying")
+            result = super().execute_tool_call(
+                tool_name, args, strict_schema=False
+            )
+            return result`,
  "stricter-tool-hashing": `--- a/agents/retry-on-schema-drift.py
+++ b/agents/stricter-tool-hashing.py
@@ -12,7 +12,9 @@ class CodingAgentHarness:
     def select_tool(self, context: str) -> str:
-        return self.tool_selector.best_match(context)
+        candidates = self.tool_selector.ranked_matches(context)
+        hashed = [self._hash_tool_sig(c) for c in candidates]
+        return candidates[0] if len(set(hashed)) == len(hashed) else candidates[1]`,
  "early-exit-on-auth": `--- a/agents/retry-on-schema-drift.py
+++ b/agents/early-exit-on-auth.py
@@ -30,6 +30,12 @@ class CodingAgentHarness:
     def pre_validate(self, patch: str) -> bool:
+        # Early exit: skip full validation if auth token expired
+        if self._check_auth_status() == "expired":
+            self.log("warn", "Auth expired, skipping validation")
+            return False
         return super().pre_validate(patch)`,
  "more-specific-descriptions": `--- a/agents/early-exit-on-auth.py
+++ b/agents/more-specific-descriptions.py
@@ -8,8 +8,14 @@ class CodingAgentHarness:
     TOOL_DESCRIPTIONS = {
-        "read_file": "Read a file from the workspace",
-        "write_file": "Write content to a file",
+        "read_file": "Read the full contents of a file at the given path. "
+                     "Returns the file as a UTF-8 string. Raises FileNotFoundError "
+                     "if the path does not exist.",
+        "write_file": "Write the given string content to the specified file path. "
+                      "Creates parent directories if needed. Overwrites existing "
+                      "content. Returns the number of bytes written.",
     }`,
  "rewrite-tool-descriptions": `--- a/agents/retry-on-schema-drift.py
+++ b/agents/rewrite-tool-descriptions.py
@@ -5,10 +5,16 @@ class CodingAgentHarness:
     def get_tool_descriptions(self) -> dict[str, str]:
-        return self.default_descriptions()
+        base = self.default_descriptions()
+        rewritten = {}
+        for name, desc in base.items():
+            rewritten[name] = self._rewrite_for_clarity(name, desc)
+        return rewritten
+
+    def _rewrite_for_clarity(self, name: str, desc: str) -> str:
+        prompt = f"Rewrite this tool description to be unambiguous: {desc}"
+        return self.llm.complete(prompt, max_tokens=100)`,
  "few-shot-demos": `--- a/agents/rewrite-tool-descriptions.py
+++ b/agents/few-shot-demos.py
@@ -15,6 +15,18 @@ class CodingAgentHarness:
     def get_demonstrations(self, query_type: str) -> list[dict]:
-        return []  # No demonstrations in base
+        # Dynamic cosine-similarity ranking
+        demos = DEMO_REGISTRY.get(query_type, [])[:3]
+        return demos
+
+    def format_prompt(self, context: str, query: str) -> str:
+        template = (
+            "## Examples\\n"
+            "{demos}\\n"
+            "## Context\\n{context}\\n"
+            "## Task\\n{query}"
+        )
+        demos = self.get_demonstrations(query_type=query)
+        return template.format(demos=demos, context=context, query=query)`,
};
