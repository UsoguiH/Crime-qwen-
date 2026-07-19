import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

/** Subscribes to a run's SSE stream while it is active and keeps the
 *  run/steps query cache fresh. Falls back gracefully: on error the
 *  browser's EventSource auto-reconnects; queries also refetch on events. */
export function useRunEvents(runId: string | null, active: boolean,
                             onEvent?: (e: Record<string, unknown>) => void) {
  const qc = useQueryClient();

  useEffect(() => {
    if (!runId || !active) return;
    const es = new EventSource(`/api/runs/${runId}/events`);
    const invalidate = () => {
      qc.invalidateQueries({ queryKey: ["run", runId] });
    };
    const handler = (ev: MessageEvent) => {
      let data: Record<string, unknown> = {};
      try { data = JSON.parse(ev.data); } catch { /* noop */ }
      onEvent?.({ type: ev.type, ...data });
      if (ev.type === "snapshot") {
        qc.setQueryData(["run", runId], data);
      } else if (ev.type === "step") {
        qc.setQueryData(["run", runId], (old: any) => {
          if (!old?.steps) return old;
          const steps = old.steps.map((s: any) =>
            s.stage === data.stage ? { ...s, ...data } : s);
          return { ...old, steps };
        });
      } else if (ev.type === "run_status") {
        invalidate();
        qc.invalidateQueries({ queryKey: ["case"] });
        qc.invalidateQueries({ queryKey: ["entities", runId] });
        qc.invalidateQueries({ queryKey: ["reports", runId] });
      } else if (ev.type === "report") {
        qc.invalidateQueries({ queryKey: ["reports", runId] });
      }
    };
    for (const type of ["snapshot", "step", "run_status", "report", "warning", "model_call"]) {
      es.addEventListener(type, handler);
    }
    return () => es.close();
  }, [runId, active, qc, onEvent]);
}
