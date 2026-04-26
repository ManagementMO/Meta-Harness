import { DashboardProvider } from "@/lib/state";
import { TopBar } from "@/components/TopBar";
import { StatusBar } from "@/components/StatusBar";
import { TrajectoryTree } from "@/components/TrajectoryTree";
import { DecisionLog } from "@/components/DecisionLog";
import { ContextPanel } from "@/components/ContextPanel";

type Params = Promise<{ run_id: string }>;

export default async function RunPage({ params }: { params: Params }) {
  const { run_id } = await params;
  return (
    <DashboardProvider initial={{ run: { runId: run_id, threadId: run_id, branches: 2, checkpointId: "ckpt_4af9e21c", bestScore: 0.85, status: "running", iteration: 4 } }}>
      <div className="flex flex-col h-screen bg-bg text-text-hi">
        <TopBar />
        <main className="flex-1 grid grid-cols-[420px_minmax(0,1fr)] grid-rows-[1fr_minmax(0,1fr)] gap-3 p-3 min-h-0">
          <section className="row-span-2 bg-panel rounded overflow-hidden flex flex-col min-h-0">
            <TrajectoryTree />
          </section>
          <section className="bg-panel rounded overflow-hidden flex flex-col min-h-0">
            <DecisionLog />
          </section>
          <section className="bg-panel rounded overflow-hidden flex flex-col min-h-0">
            <ContextPanel />
          </section>
        </main>
        <StatusBar />
      </div>
    </DashboardProvider>
  );
}
