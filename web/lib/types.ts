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

export interface RemediateAdvisoryResult {
  success: boolean;
  incidentId: string | null;
  package: string | null;
  pr: string | null;
  diffPath: string | null;
  diffPreview: string | null;
  filesModified: number;
  error: string | null;
}

export interface DiscoveredEntityItem {
  name: string;
  kind: string;
  urn: string;
  file: string;
}

export interface OnboardedRepoResult {
  repoName: string;
  repoPath: string;
  totalFilesScanned: number;
  datasetsCount: number;
  modelsCount: number;
  jobsCount: number;
  lineageEdgesCount: number;
  mlflowExperimentId: string;
  mlflowExperimentName: string;
  datahubGraphEmitted: boolean;
  githubWorkflowContent: string;
  scannedAt: string;
  entities: DiscoveredEntityItem[];
}

export interface ChaosScenarioInfo {
  id: string;
  name: string;
  category: string;
  description: string;
  signalType: string;
  expectedRootCause: string;
}

export interface ChaosDrillResult {
  success: boolean;
  scenarioId: string;
  scenarioName: string;
  incidentId: string | null;
  signalType: string | null;
  assetUrn?: string | null;
  summary?: string | null;
  rootCauseAsset?: string | null;
  rootCauseColumn?: string | null;
  actionsTaken?: string[];
  pr?: string | null;
  changeType?: string | null;
  status: string;
  log: string[];
  error: string | null;
}

export interface ConnectedRepository {
  id: string;
  repoName: string;
  repoPath: string;
  commitSha: string | null;
  datasetsCount: number;
  modelsCount: number;
  jobsCount: number;
  edgesCount: number;
  mlflowExperimentId: string | null;
  onboardedAt: string;
  isActive: boolean;
  entities?: DiscoveredEntityItem[];
}
