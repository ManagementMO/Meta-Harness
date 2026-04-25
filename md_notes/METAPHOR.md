Git → RELAY Mapping                                                                                     
                                                                                                          
  Git                          RELAY (Harness Version Control)                                            
  ─────────────────────────    ─────────────────────────────────                                          
  Repository                   One evolution run                                                          
  Commit                       One iteration (propose + eval)                                             
  Commit message               Proposer's hypothesis                                                      
  Diff                         The harness code change                                                    
  Branch                       A fork from a checkpoint                                                   
  HEAD                         frontier_val.json (current best)                                           
  git log                      evolution_summary.jsonl                                                    
  Build artifacts              Execution traces (the raw stdout/stderr)
  git checkout <sha>           Rewind to checkpoint                                                       
  git branch                   Fork with modified state                                                   
  git diff branch1 branch2     Compare two evolution branches                                             
                                                                                                          
  How Every Paper Artifact Maps                                                                           
                                                            
  Paper artifact               Role in "version control"                                                  
  ─────────────────────────    ─────────────────────────────────
  SKILL.md                     The commit policy — rules for what                                         
                               the proposer is allowed to change,                                         
                               how to structure proposals, what's                                         
                               out of scope. Like a CONTRIBUTING.md.                                      
                                                                                                          
  config.yaml                  The CI config — defines what gets                                          
                               tested (which datasets, which models,                                      
                               how many trials). The test matrix.                                         
                                                                                                          
  evolution_summary.jsonl      The git log — append-only record of                                        
                               every candidate ever tried, with                                           
                               scores, hypotheses, deltas.                                                
                                                                                                          
  frontier_val.json            HEAD — points to the current best
                               harness per task. What the proposer                                        
                               tries to beat next iteration.
                                                                                                          
  pending_eval.json            A pull request — proposer writes it,                                       
                               outer loop picks it up, validates,                                         
                               benchmarks, and "merges" (updates                                          
                               frontier) or "rejects" (score didn't
                               improve).                                                                  
                                                            
  traces (log.jsonl, stderr)   Build logs — the raw evidence of                                           
                               what went wrong. The paper proved
                               these are the #1 input. Without                                            
                               them, accuracy drops from 50% → 34%.                                       
                                                                                                          
  agents/*.py                  The actual source files being                                              
                               version-controlled. Each iteration                                         
                               produces a new file.                                                       
   
  claude_wrapper.py            The CI runner — executes the                                               
                               proposer, logs everything.   
                                                                                                          
  What Fork Means in This Framing                           
                                                                                                          
  evolution_summary.jsonl (the "git log"):                  
                                                                                                          
    iter1: baseline         → 40%                                                                         
    iter2: add_few_shot     → 48%                                                                         
    iter3: add_retries      → 52%   ← you fork HERE                                                       
    iter4: tune_retries     → 50%   (regression — dead end)                                               
    iter5: more_retries     → 51%   (still stuck)                                                         
                                                                                                          
  After fork:                                                                                             
                                                                                                          
    Branch A (original):                                                                                  
      iter3: add_retries    → 52%
      iter4: tune_retries   → 50%                                                                         
      iter5: more_retries   → 51%                           
                                                                                                          
    Branch B (fork):
      iter3': add_planning  → 54%   ← different SKILL.md constraint                                       
      iter4': add_self_test → 63%   ← builds on planning    
      iter5': refine_plan   → 68%   ← compounding divergence                                              
                                                                                                          
  The SKILL.md stays the same across branches (it's the commit policy). The config.yaml stays the same    
  (same test suite). What changes is the proposer's context — it sees different history, different traces,
   potentially a different nudge from the user — so it makes different decisions.                         
                                                            
  That's the whole product: git for the harness search process, where the "developer" is Claude and the   
  "code" is agent scaffolds.
                                   