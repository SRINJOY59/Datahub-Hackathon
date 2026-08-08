import { API_URL } from "./graphql";

export interface ActionsConfig {
  enabled: boolean;
  allowDrill: boolean;
  allowRollback: boolean;
  allowRescore: boolean;
  scenarios: string[];
}

export interface Job {
  id: string;
  kind: string;
  target: string;
  status: "running" | "succeeded" | "failed";
  log: string[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export async function fetchActionsConfig(): Promise<ActionsConfig> {
  const res = await fetch(`${API_URL}/actions/config`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function post(path: string): Promise<Job> {
  const res = await fetch(`${API_URL}${path}`, { method: "POST" });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.detail ?? `HTTP ${res.status}`);
  return body;
}

export const runDrill = (scenario: string) => post(`/actions/drill/${scenario}`);
export const runRollback = (incidentId: string) => post(`/actions/rollback/${incidentId}`);
export const runRescore = () => post(`/actions/rescore`);

export async function fetchJobs(): Promise<Job[]> {
  const res = await fetch(`${API_URL}/actions/jobs`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.jobs ?? [];
}

export async function fetchJob(id: string): Promise<Job | null> {
  const res = await fetch(`${API_URL}/actions/jobs/${id}`);
  if (!res.ok) return null;
  return res.json();
}
