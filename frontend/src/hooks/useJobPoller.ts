/**
 * useJobPoller.ts – isolated polling lifecycle hook.
 *
 * Handles: submit → queued → pending → success/failure/cancelled
 * and keeps a local copy of the active job synced with the server.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelJob as apiCancelJob,
  type JobProgress,
  normalizeJobRecord,
  pollJob as apiPollJob,
  submitGenerate,
  type GenerateRequest,
  type JobRecord,
  type JobResult,
} from "../api/pixelClient";

export type PollerState = {
  /** Current job ID being tracked, empty string when idle. */
  jobId: string;
  /** Human-readable status string from the backend (or "idle"). */
  status: string;
  /** Populated once the job succeeds. */
  result: JobResult | null;
  /** Error message to surface to the user. */
  errorMessage: string;
  /** Live progress payload from backend when available. */
  progress: JobProgress | null;
};

const IDLE: PollerState = {
  jobId: "",
  status: "idle",
  result: null,
  errorMessage: "",
  progress: null,
};

const POLL_INTERVAL_MS = 3_500;

type UseJobPollerReturn = {
  state: PollerState;
  /** Submit a new generate request. Resolves with the created JobRecord. */
  submit: (request: GenerateRequest) => Promise<JobRecord>;
  /** Cancel the active job. */
  cancel: () => Promise<void>;
  /** Reset to idle state. */
  reset: () => void;
};

/**
 * @param onJobUpdate - called every time a job's status/result changes so the
 *   parent can sync history and library caches.
 */
export function useJobPoller(
  onJobUpdate: (patch: Pick<JobRecord, "job_id" | "status" | "result" | "error">) => void,
): UseJobPollerReturn {
  const [state, setState] = useState<PollerState>(IDLE);
  const activeJobIdRef = useRef<string>("");

  // ── polling effect ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!state.jobId || !["queued", "pending"].includes(state.status)) {
      return;
    }

    const id = setInterval(() => {
      if (!activeJobIdRef.current) {
        return;
      }
      void runPoll(activeJobIdRef.current);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.jobId, state.status]);

  async function runPoll(jobId: string) {
    try {
      const data = await apiPollJob(jobId);
      setState((prev) => ({
        ...prev,
        status: data.status,
        progress: data.progress ?? null,
        result: data.result ?? null,
        errorMessage: data.error?.message ?? "",
      }));
      onJobUpdate({
        job_id: data.job_id,
        status: data.status,
        result: data.result,
        error: data.error,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Polling failed";
      if (message.includes("HTTP 404")) {
        // Backend job store is in-memory; old ids can disappear after restart.
        activeJobIdRef.current = "";
        setState((prev) => ({
          ...prev,
          status: "cancelled",
          errorMessage: "Job no longer exists on backend (likely after server restart).",
          progress: null,
        }));
        onJobUpdate({
          job_id: jobId,
          status: "cancelled",
          result: undefined,
          error: { code: "job_not_found", message: "job not found" },
        });
        return;
      }

      setState((prev) => ({ ...prev, status: "failure", errorMessage: message }));
    }
  }

  // ── submit ────────────────────────────────────────────────────────────────
  const submit = useCallback(
    async (request: GenerateRequest): Promise<JobRecord> => {
      setState({ jobId: "", status: "queued", result: null, errorMessage: "", progress: null });

      try {
        const data = await submitGenerate(request);
        const jobId = data.job_id;
        activeJobIdRef.current = jobId;

        setState({ jobId, status: data.status, result: null, errorMessage: "", progress: null });

        const record: JobRecord = {
          job_id: jobId,
          status: data.status,
          request,
          result: null,
          error: null,
          createdAt: new Date().toISOString(),
        };
        onJobUpdate({ job_id: jobId, status: data.status, result: undefined, error: null });

        // Kick off first poll immediately
        void runPoll(jobId);
        return record;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Submit failed";
        setState({ jobId: "", status: "failure", result: null, errorMessage: message, progress: null });
        throw err;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [onJobUpdate],
  );

  // ── cancel ────────────────────────────────────────────────────────────────
  const cancel = useCallback(async () => {
    const id = activeJobIdRef.current;
    if (!id) {
      return;
    }
    try {
      const data = await apiCancelJob(id);
      const nextStatus = data.status;
      if (["success", "failure", "cancelled"].includes(nextStatus)) {
        activeJobIdRef.current = "";
      }
      setState((prev) => ({ ...prev, status: nextStatus }));
      onJobUpdate({ job_id: id, status: nextStatus, result: undefined, error: null });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Cancel failed";
      setState((prev) => ({ ...prev, errorMessage: message }));
    }
  }, [onJobUpdate]);

  // ── reset ─────────────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    activeJobIdRef.current = "";
    setState(IDLE);
  }, []);

  return { state, submit, cancel, reset };
}

/** Convenience: apply a job patch into a JobRecord[] array (for history / library). */
export function applyJobPatch(
  list: JobRecord[],
  patch: Pick<JobRecord, "job_id" | "status" | "result" | "error">,
): JobRecord[] {
  const exists = list.some((item) => item.job_id === patch.job_id);
  if (!exists) {
    return list;
  }
  return list.map((item) =>
    item.job_id === patch.job_id ? { ...item, ...patch } : item,
  );
}

export { normalizeJobRecord };
