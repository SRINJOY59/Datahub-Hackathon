// Mirrors api/types.py — GraphQL auto-converts snake_case to camelCase, so
// these field names match what the schema actually serves, not the Python.

export interface ActionEntry {
  actionType: string;
  target: string;
  status: string;
  note: string;
  reversible: boolean;
  appliedAt: string | null;
}

export interface Incident {
  id: string;
  assetUrn: string;
  assetName: string | null;
  signalType: string | null;
  summary: string | null;
  changeType: string | null;
  confidence: string | null;
  narrative: string | null;
  rootCauseAsset: string | null;
  rootCauseColumn: string | null;
  tier: string | null;
  status: string;
  resolved: boolean;
  pr: string | null;
  costUsd: number | null;
  costBasis: string | null;
  downstreamCount: number | null;
  actionTypes: string[];
  detectedAt: string;
  closedAt: string | null;
  updatedAt: string;
  minutesToClose: number | null;
  timeline: ActionEntry[];
}

export interface ChangeTypeCount {
  changeType: string;
  count: number;
}

export interface Stats {
  total: number;
  resolved: number;
  open: number;
  exposureUsd: number;
  mttrMinutes: number | null;
  byChangeType: ChangeTypeCount[];
}

export interface DayPoint {
  day: string;
  total: number;
  resolved: number;
  exposureUsd: number;
  mttrMinutes: number | null;
}

export interface ActionCount {
  actionType: string;
  count: number;
}

export interface SavingsDigest {
  incidents: number;
  actionsApplied: number;
  actionsSimulated: number;
  actionsFailed: number;
  hoursSaved: number;
  shadowMode: boolean;
  byAction: ActionCount[];
}

export interface TrustBadge {
  assetUrn: string;
  assetName: string;
  score: number;
  grade: string;
  failedAssertions: number;
  openIncident: boolean;
  volumeShift: number;
  freshnessLagHours: number;
  pastIncidents: number;
}

export interface Runbook {
  changeType: string;
  skillUrn: string | null;
  registered: boolean;
  title: string | null;
  description: string | null;
  instructions: string | null;
  incidentsBacking: number;
  incidentsNeeded: number;
}

export interface JournalEntry {
  actionType: string;
  target: string;
  status: string;
  note: string;
  incidentId: string;
  reversible: boolean;
  appliedAt: string | null;
}

export interface WebhookRun {
  runId: string;
  assetUrn: string;
  source: string;
  status: string;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
}

export interface WebhookActivity {
  attached: boolean;
  active: WebhookRun[];
  recent: WebhookRun[];
}

export interface SystemStatus {
  datahubReachable: boolean;
  datahubVersion: string | null;
  datahubUrl: string;
  slackConfigured: boolean;
  slackInteractiveApprovals: boolean;
  pagerdutyConfigured: boolean;
  llmConfigured: boolean;
  llmModel: string;
  webhookSourcesEnabled: string[];
  sweepIntervalMinutes: number;
}
