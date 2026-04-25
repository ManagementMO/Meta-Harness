                                                                                                                     
⏺ Yes, exactly. The time-travel operates on the evolution loop itself — the outer loop where Claude proposes harness  
  changes.                                                                                                          
                                                                                                                      
  Each checkpoint captures the full evolution state at that moment:                                                   
  - What harnesses have been tried so far
  - What scores they got                                                                                              
  - The raw traces (why they failed)                        
  - The current frontier (best agent so far)                                                                          
                                                                                                                      
  Forking means: "Go back to iteration 3's state, give Claude different guidance, and let it propose a different
  harness change from that point."                                                                                    
                                                            
  You're NOT building time-travel for individual coding agent runs (replaying a single task step-by-step). You're     
  building it for the search process — the sequence of decisions Claude makes about how to evolve the agent.
                                                                                                                      
  The thing being time-traveled:   Claude's harness evolution decisions                                               
  The thing being evolved:         The coding agent's scaffold                                                        
  The thing doing the work:        The coding agent solving tasks                                                     
                                                                                                                      
  So the demo story is: "Claude evolved the agent for 5 iterations and got to 55%. But at iteration 3, it went down a 
  dead-end path. We rewind, nudge it toward a different strategy, and it reaches 72% instead." 