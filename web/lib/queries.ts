import { gql, API_URL } from "./graphql";
import type {
  Advisory,
  ApiHealthStats,
  BlastRadius,
  DayPoint,
  Dependency,
  DependencyScanResult,
  Incident,
  JournalEntry,
  Migration,
  RegistrySyncResult,
  Runbook,
  SavingsDigest,
  Stats,
  SystemStatus,
  TrustBadge,
  WebhookActivity,
} from "./types";

const INCIDENT_FIELDS = `
  id assetUrn assetName signalType summary changeType confidence narrative
  rootCauseAsset rootCauseColumn tier status resolved pr costUsd costBasis
  downstreamCount actionTypes detectedAt closedAt updatedAt minutesToClose
`;

export async function fetchStats(init?: RequestInit): Promise<Stats> {
  const data = await gql<{ stats: Stats }>(
    `query { stats { total resolved open exposureUsd mttrMinutes
      byChangeType { changeType count } } }`,
    undefined,
    init,
  );
  return data.stats;
}

export async function fetchSystemStatus(init?: RequestInit): Promise<SystemStatus> {
  const data = await gql<{ systemStatus: SystemStatus }>(
    `query { systemStatus {
      datahubReachable datahubVersion datahubUrl
      slackConfigured slackInteractiveApprovals
      pagerdutyConfigured llmConfigured llmModel
      webhookSourcesEnabled sweepIntervalMinutes
    } }`,
    undefined,
    init,
  );
  return data.systemStatus;
}

export async function fetchIncidents(
  opts: { status?: string; limit?: number } = {},
  init?: RequestInit,
): Promise<Incident[]> {
  const data = await gql<{ incidents: Incident[] }>(
    `query($status: String, $limit: Int!) {
      incidents(status: $status, limit: $limit) { ${INCIDENT_FIELDS} }
    }`,
    { status: opts.status ?? null, limit: opts.limit ?? 50 },
    init,
  );
  return data.incidents;
}

export async function fetchTrends(days = 30, init?: RequestInit): Promise<DayPoint[]> {
  const data = await gql<{ trends: DayPoint[] }>(
    `query($days: Int!) { trends(days: $days) {
      day total resolved exposureUsd mttrMinutes } }`,
    { days },
    init,
  );
  return data.trends;
}

export async function fetchDigest(init?: RequestInit): Promise<SavingsDigest> {
  const data = await gql<{ savingsDigest: SavingsDigest }>(
    `query { savingsDigest {
      incidents actionsApplied actionsSimulated actionsFailed
      hoursSaved shadowMode byAction { actionType count } } }`,
    undefined,
    init,
  );
  return data.savingsDigest;
}

export async function fetchTrustBadges(init?: RequestInit): Promise<TrustBadge[]> {
  const data = await gql<{ trustBadges: TrustBadge[] }>(
    `query { trustBadges {
      assetUrn assetName score grade failedAssertions openIncident
      volumeShift freshnessLagHours pastIncidents } }`,
    undefined,
    init,
  );
  return data.trustBadges;
}

export async function fetchRunbooks(init?: RequestInit): Promise<Runbook[]> {
  const data = await gql<{ runbooks: Runbook[] }>(
    `query { runbooks {
      changeType skillUrn registered title description instructions
      incidentsBacking incidentsNeeded } }`,
    undefined,
    init,
  );
  return data.runbooks;
}

export async function fetchJournal(limit = 100, init?: RequestInit): Promise<JournalEntry[]> {
  const data = await gql<{ journal: JournalEntry[] }>(
    `query($limit: Int!) { journal(limit: $limit) {
      actionType target status note incidentId reversible appliedAt } }`,
    { limit },
    init,
  );
  return data.journal;
}

export async function fetchWebhookActivity(init?: RequestInit): Promise<WebhookActivity> {
  const data = await gql<{ webhookActivity: WebhookActivity }>(
    `query { webhookActivity {
      attached
      active { runId assetUrn source status startedAt finishedAt error }
      recent { runId assetUrn source status startedAt finishedAt error } } }`,
    undefined,
    init,
  );
  return data.webhookActivity;
}

export async function fetchIncident(id: string, init?: RequestInit): Promise<Incident | null> {
  const data = await gql<{ incident: Incident | null }>(
    `query($id: String!) {
      incident(id: $id) {
        ${INCIDENT_FIELDS}
        timeline { actionType target status note reversible appliedAt }
      }
    }`,
    { id },
    init,
  );
  return data.incident;
}

// --- Self-Maintaining APIs & Dependency Health ----------------------------- //

export async function fetchApiHealthStats(init?: RequestInit): Promise<ApiHealthStats> {
  const data = await gql<{ apiHealthStats: ApiHealthStats }>(
    `query { apiHealthStats {
      totalDependencies atRisk healthy activeAdvisories
      resolvedMigrations pendingMigrations totalAffectedUsages
    } }`,
    undefined,
    init,
  );
  return data.apiHealthStats;
}

export async function fetchDependencies(
  force = false,
  init?: RequestInit,
): Promise<Dependency[]> {
  const data = await gql<{ apiDependencies: Dependency[] }>(
    `query($force: Boolean!) { apiDependencies(force: $force) {
      package installedVersion filesUsing impactedAssets assetUrns hasAdvisory status
    } }`,
    { force },
    init,
  );
  return data.apiDependencies;
}

export async function fetchAdvisories(init?: RequestInit): Promise<Advisory[]> {
  const data = await gql<{ activeAdvisories: Advisory[] }>(
    `query { activeAdvisories {
      id package importName fromVersion toVersion kind summary migration
      symbols usagesCount impactedCount publishedAt
      usages { file line code }
      impactedAssets
    } }`,
    undefined,
    init,
  );
  return data.activeAdvisories;
}

export async function fetchMigrations(init?: RequestInit): Promise<Migration[]> {
  const data = await gql<{ migrationHistory: Migration[] }>(
    `query { migrationHistory {
      incidentId assetUrn assetName status resolved pr costUsd narrative
      detectedAt closedAt hasDiff diffPreview
    } }`,
    undefined,
    init,
  );
  return data.migrationHistory;
}

export async function fetchBlastRadius(
  pkg: string,
  init?: RequestInit,
): Promise<BlastRadius> {
  const data = await gql<{ dependencyBlastRadius: BlastRadius }>(
    `query($package: String!) { dependencyBlastRadius(package: $package) {
      package files directAssets totalImpacted
      downstreamAssets { urn name entityType upstreamOf }
    } }`,
    { package: pkg },
    init,
  );
  return data.dependencyBlastRadius;
}

export async function triggerDependencyScan(): Promise<DependencyScanResult> {
  const data = await gql<{ triggerDependencyScan: DependencyScanResult }>(
    `query { triggerDependencyScan {
      scanned advisoriesChecked incidentsFound error
    } }`,
  );
  return data.triggerDependencyScan;
}

export async function syncRegistries(): Promise<RegistrySyncResult> {
  const data = await gql<{ syncRegistries: RegistrySyncResult }>(
    `query { syncRegistries {
      success packagesChecked advisoriesGenerated networkOnline error
      generated { package path source }
    } }`,
  );
  return data.syncRegistries;
}

export async function ingestVendorAdvisory(payload: {
  package: string;
  import_name?: string;
  from_version?: string;
  to_version?: string;
  kind?: string;
  summary: string;
  migration?: string;
  symbols?: string[];
}): Promise<{ accepted: boolean; advisory_id?: string; path?: string }> {
  const res = await fetch(`${API_URL}/api/v1/advisory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to publish advisory" }));
    throw new Error(err.detail || "Failed to publish advisory");
  }
  return res.json();
}

