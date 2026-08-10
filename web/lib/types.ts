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

// --- Self-Maintaining APIs & Dependency Health Types ----------------------- //

export interface Dependency {
  package: string;
  installedVersion: string | null;
  filesUsing: number;
  impactedAssets: number;
  assetUrns: string[];
  hasAdvisory: boolean;
  status: "healthy" | "at_risk" | "unknown" | string;
}

export interface AdvisoryUsage {
  file: string;
  line: number;
  code: string;
}

export interface Advisory {
  id: string;
  package: string;
  importName: string;
  fromVersion: string;
  toVersion: string;
  kind: string;
  summary: string;
  migration: string;
  symbols: string[];
  usages: AdvisoryUsage[];
  usagesCount: number;
  impactedAssets: string[];
  impactedCount: number;
  publishedAt: string;
}

export interface Migration {
  incidentId: string;
  assetUrn: string;
  assetName: string | null;
  status: string;
  resolved: boolean;
  pr: string | null;
  costUsd: number | null;
  narrative: string;
  detectedAt: string;
  closedAt: string | null;
  hasDiff: boolean;
  diffPreview: string;
}

export interface BlastRadiusNode {
  urn: string;
  name: string;
  entityType: string;
  upstreamOf: string;
}

export interface BlastRadius {
  package: string;
  files: string[];
  directAssets: string[];
  downstreamAssets: BlastRadiusNode[];
  totalImpacted: number;
}

export interface ApiHealthStats {
  totalDependencies: number;
  atRisk: number;
  healthy: number;
  activeAdvisories: number;
  resolvedMigrations: number;
  pendingMigrations: number;
  totalAffectedUsages: number;
}

export interface DependencyScanResult {
  scanned: boolean;
  advisoriesChecked: number;
  incidentsFound: number;
  error: string | null;
}

export interface RegistrySyncItem {
  package: string;
  path: string;
  source: string;
}

export interface RegistrySyncResult {
  success: boolean;
  packagesChecked: number;
  advisoriesGenerated: number;
  networkOnline: boolean;
  error: string | null;
  generated: RegistrySyncItem[];
}
