import { gql } from "./graphql";
import type {
  DayPoint,
  Incident,
  JournalEntry,
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
