// API Configuration and Helpers

import {
  Competitor,
  Insight,
  Signal,
  Prediction,
  RawData,
  PageChange,
  DashboardResponse,
  HealthResponse,
  PipelineResponse,
  EmptySummaryResponse,
  PipelineStatus,
  DiscoverResponse,
  Entity,
  Relationship,
  ModelCatalog,
  PipelineDataDeleteResponse,
  PipelineRun,
  EvidenceDocument,
  IntelligenceClaim,
  EvidenceSearchHit,
  SourceHealth,
  EvidenceOverview,
  CollectionCampaign,
  SourceProfile,
  CollectionCoverage,
  CollectionError,
  AccessRecoveryConfig,
  RelationshipIntelligence,
  Investigation,
  MonitoringOverview,
  TimelineOverview,
  VerificationOverview,
  LLMConnection,
  LLMConnectionUpdate,
  LLMProviderPresets,
} from './types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

async function apiError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null) as { detail?: string } | null;
  return new Error(payload?.detail ?? `API error: ${response.status} ${response.statusText}`);
}

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options?.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(url, {
    ...options,
    headers,
    cache: 'no-store',
  });

  if (!response.ok) {
    throw await apiError(response);
  }

  return response.json();
}

// Health
export async function getHealth(): Promise<HealthResponse> {
  return fetchAPI<HealthResponse>('/health');
}

// Competitors
export async function getCompetitors(): Promise<Competitor[]> {
  return fetchAPI<Competitor[]>('/competitors');
}

export async function getCompetitor(id: number): Promise<Competitor> {
  return fetchAPI<Competitor>(`/competitors/${id}`);
}

export async function createCompetitor(data: {
  name: string;
  domain: string;
  industry?: string;
  rss_feeds?: string[];
}): Promise<Competitor> {
  return fetchAPI<Competitor>('/competitors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// Insights
export async function getCompetitorInsights(id: number): Promise<Insight[]> {
  return fetchAPI<Insight[]>(`/competitors/${id}/insights`);
}

// Signals
export async function getCompetitorSignals(
  id: number,
  severity?: string
): Promise<Signal[]> {
  const params = severity ? `?severity=${severity}` : '';
  return fetchAPI<Signal[]>(`/competitors/${id}/signals${params}`);
}

// Predictions
export async function getCompetitorPredictions(id: number): Promise<Prediction[]> {
  return fetchAPI<Prediction[]>(`/competitors/${id}/predictions`);
}

// Raw Data
export async function getCompetitorRawData(
  id: number,
  source?: string
): Promise<RawData[]> {
  const params = source ? `?source=${source}` : '';
  return fetchAPI<RawData[]>(`/competitors/${id}/raw_data${params}`);
}

export async function getCompetitorChanges(
  id: number,
  changeType?: string
): Promise<PageChange[]> {
  const params = changeType ? `?change_type=${encodeURIComponent(changeType)}` : '';
  return fetchAPI<PageChange[]>(`/competitors/${id}/changes${params}`);
}

// Summary
export async function getCompetitorSummary(id: number): Promise<Insight | EmptySummaryResponse> {
  return fetchAPI<Insight | EmptySummaryResponse>(`/competitors/${id}/summary`);
}

// Pipeline
export async function runPipeline(
  id: number,
  model?: string
): Promise<PipelineResponse> {
  return fetchAPI<PipelineResponse>(`/competitors/${id}/run_pipeline`, {
    method: 'POST',
    body: JSON.stringify(model ? { model } : {}),
  });
}

export async function getModelCatalog(): Promise<ModelCatalog> {
  return fetchAPI<ModelCatalog>('/models');
}

export async function getLLMConnection(): Promise<LLMConnection> {
  return fetchAPI<LLMConnection>('/settings/llm');
}

export async function getLLMProviderPresets(): Promise<LLMProviderPresets> {
  return fetchAPI<LLMProviderPresets>('/settings/llm/providers');
}

export async function saveLLMConnection(data: LLMConnectionUpdate): Promise<LLMConnection> {
  return fetchAPI<LLMConnection>('/settings/llm', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function testLLMConnection(): Promise<{
  ok: boolean;
  message: string;
  response?: string;
}> {
  return fetchAPI('/settings/llm/test', { method: 'POST' });
}

export async function resetLLMConnection(): Promise<{
  status: 'reset';
  connection: LLMConnection;
}> {
  return fetchAPI('/settings/llm', { method: 'DELETE' });
}

export async function discoverCompany(name: string): Promise<DiscoverResponse> {
  return fetchAPI<DiscoverResponse>('/discover', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

export async function getPipelineStatus(id: number): Promise<PipelineStatus> {
  return fetchAPI<PipelineStatus>(`/competitors/${id}/pipeline_status`);
}

export async function getPipelineRuns(id: number): Promise<PipelineRun[]> {
  return fetchAPI<PipelineRun[]>(`/competitors/${id}/pipeline_runs`);
}

export async function cancelPipelineRun(id: number, runId: number): Promise<{
  status: string;
  competitor_id: number;
  run_id: number;
}> {
  return fetchAPI(`/competitors/${id}/pipeline_runs/${runId}/cancel`, {
    method: 'POST',
  });
}

export async function retryPipelineTask(
  id: number,
  runId: number,
  taskId: number,
): Promise<{
  status: string;
  competitor_id: number;
  source_run_id: number;
  source_task_id: number;
  retry_run_id: number;
  task_key: string;
}> {
  return fetchAPI(`/competitors/${id}/pipeline_runs/${runId}/tasks/${taskId}/retry`, {
    method: 'POST',
  });
}

export async function getEvidenceOverview(id: number): Promise<EvidenceOverview> {
  return fetchAPI<EvidenceOverview>(`/competitors/${id}/evidence/overview`);
}

export async function getEvidenceDocuments(id: number): Promise<EvidenceDocument[]> {
  return fetchAPI<EvidenceDocument[]>(`/competitors/${id}/documents`);
}

export async function getIntelligenceClaims(id: number): Promise<IntelligenceClaim[]> {
  return fetchAPI<IntelligenceClaim[]>(`/competitors/${id}/claims`);
}

export async function searchEvidence(
  id: number,
  query: string,
  limit = 20,
): Promise<EvidenceSearchHit[]> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return fetchAPI<EvidenceSearchHit[]>(`/competitors/${id}/evidence/search?${params}`);
}

export async function getSourceHealth(id: number): Promise<SourceHealth[]> {
  return fetchAPI<SourceHealth[]>(`/competitors/${id}/source_health`);
}

export async function getCollectionCampaigns(id: number): Promise<CollectionCampaign[]> {
  return fetchAPI<CollectionCampaign[]>(`/competitors/${id}/collection/campaigns`);
}

export async function getSourceProfiles(id: number): Promise<SourceProfile[]> {
  return fetchAPI<SourceProfile[]>(`/competitors/${id}/source_profiles`);
}

export async function getCollectionCoverage(id: number): Promise<CollectionCoverage> {
  return fetchAPI<CollectionCoverage>(`/competitors/${id}/collection/coverage`);
}

export async function getCollectionErrors(
  id: number,
  includeResolved = false,
): Promise<CollectionError[]> {
  const params = new URLSearchParams({
    limit: '100',
    include_resolved: String(includeResolved),
  });
  return fetchAPI<CollectionError[]>(
    `/competitors/${id}/collection/errors?${params}`
  );
}

export async function getAccessRecoveryConfig(
  id: number,
): Promise<AccessRecoveryConfig> {
  return fetchAPI<AccessRecoveryConfig>(
    `/competitors/${id}/collection/access-recovery`
  );
}

export async function updateAccessRecoveryConfig(
  id: number,
  enabled: boolean,
): Promise<AccessRecoveryConfig> {
  return fetchAPI<AccessRecoveryConfig>(
    `/competitors/${id}/collection/access-recovery`,
    {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    },
  );
}

export async function getMonitoringOverview(
  id: number,
): Promise<MonitoringOverview> {
  return fetchAPI<MonitoringOverview>(`/competitors/${id}/monitoring`);
}

export async function updateMonitoringProfile(
  id: number,
  input: {
    enabled: boolean;
    cadence_minutes: number;
    focus_topics: string[];
    alert_severities: string[];
  },
): Promise<MonitoringOverview> {
  return fetchAPI<MonitoringOverview>(`/competitors/${id}/monitoring`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}

export async function runMonitoringNow(
  id: number,
): Promise<{
  status: string;
  competitor_id: number;
  monitoring_profile_id: number;
  activity_id: number;
  model: string;
}> {
  return fetchAPI(`/competitors/${id}/monitoring/run-now`, {
    method: 'POST',
  });
}

export async function getVerificationOverview(
  id: number,
): Promise<VerificationOverview> {
  return fetchAPI<VerificationOverview>(`/competitors/${id}/verification`);
}

export async function runClaimVerification(
  id: number,
): Promise<{
  result: {
    competitor_id: number;
    claims_assessed: number;
    sources_assessed: number;
    status_counts: Record<string, number>;
  };
  overview: VerificationOverview;
}> {
  return fetchAPI(`/competitors/${id}/verification/run`, { method: 'POST' });
}

export async function getIntelligenceTimeline(
  id: number,
): Promise<TimelineOverview> {
  return fetchAPI<TimelineOverview>(`/competitors/${id}/timeline`);
}

export async function rebuildIntelligenceTimeline(
  id: number,
): Promise<{
  result: {
    competitor_id: number;
    observations: number;
    events: number;
    correlations: number;
  };
  overview: TimelineOverview;
}> {
  return fetchAPI(`/competitors/${id}/timeline/rebuild`, {
    method: 'POST',
  });
}

export async function reviewClaim(
  id: number,
  claimId: number,
  decision: 'supported' | 'confirmed' | 'disputed' | 'stale',
  note?: string,
): Promise<Record<string, unknown>> {
  return fetchAPI(`/competitors/${id}/claims/${claimId}/review`, {
    method: 'POST',
    body: JSON.stringify({ decision, note: note || null }),
  });
}

export async function updateSourceReliability(
  id: number,
  sourceProfileId: number,
  reliability: number,
  basis: string,
): Promise<{ overview: VerificationOverview }> {
  return fetchAPI(
    `/competitors/${id}/verification/sources/${sourceProfileId}`,
    {
      method: 'PUT',
      body: JSON.stringify({ reliability, basis }),
    },
  );
}

export async function registerSourceProfile(
  id: number,
  profileUrl: string,
  sourceType?: string,
): Promise<SourceProfile> {
  return fetchAPI<SourceProfile>(`/competitors/${id}/source_profiles`, {
    method: 'POST',
    body: JSON.stringify({
      profile_url: profileUrl,
      ...(sourceType ? { source_type: sourceType } : {}),
    }),
  });
}

export async function updateSourceProfile(
  id: number,
  profileId: number,
  status: 'active' | 'disabled',
): Promise<SourceProfile> {
  return fetchAPI<SourceProfile>(`/competitors/${id}/source_profiles/${profileId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export async function deletePipelineData(id: number): Promise<PipelineDataDeleteResponse> {
  return fetchAPI<PipelineDataDeleteResponse>(`/competitors/${id}/pipeline_data`, {
    method: 'DELETE',
  });
}

export async function getCompetitorEntities(id: number): Promise<Entity[]> {
  return fetchAPI<Entity[]>(`/competitors/${id}/entities`);
}

export async function getCompetitorRelationships(id: number): Promise<Relationship[]> {
  return fetchAPI<Relationship[]>(`/competitors/${id}/relationships`);
}

export async function getRelationshipIntelligence(
  id: number
): Promise<RelationshipIntelligence> {
  return fetchAPI<RelationshipIntelligence>(
    `/competitors/${id}/relationship_intelligence`
  );
}

export async function analyzeRelationships(
  id: number
): Promise<RelationshipIntelligence> {
  return fetchAPI<RelationshipIntelligence>(
    `/competitors/${id}/relationships/analyze`,
    { method: 'POST' }
  );
}

export async function getInvestigations(id: number): Promise<Investigation[]> {
  return fetchAPI<Investigation[]>(`/competitors/${id}/investigations`);
}

export async function getInvestigation(
  id: number,
  investigationId: number
): Promise<Investigation> {
  return fetchAPI<Investigation>(
    `/competitors/${id}/investigations/${investigationId}`
  );
}

export async function createInvestigation(
  id: number,
  input: { title?: string; question: string; max_steps: number }
): Promise<Investigation> {
  return fetchAPI<Investigation>(`/competitors/${id}/investigations`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function runInvestigation(
  id: number,
  investigationId: number
): Promise<{ status: string; investigation_id: number; model: string }> {
  return fetchAPI(`/competitors/${id}/investigations/${investigationId}/run`, {
    method: 'POST',
  });
}

export async function cancelInvestigation(
  id: number,
  investigationId: number
): Promise<{ status: string; investigation_id: number }> {
  return fetchAPI(`/competitors/${id}/investigations/${investigationId}/cancel`, {
    method: 'POST',
  });
}

export async function resolveEntities(id: number): Promise<{
  entities_resolved: number;
  relationships_built: number;
  profile_updated: boolean;
}> {
  return fetchAPI(`/competitors/${id}/resolve_entities`, { method: 'POST' });
}

// Dashboard
export async function getDashboard(): Promise<DashboardResponse> {
  return fetchAPI<DashboardResponse>('/dashboard');
}

// Reports
export async function generateReport(id: number): Promise<Blob> {
  const url = `${API_BASE_URL}/competitors/${id}/report`;
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
  });

  if (!response.ok) {
    throw await apiError(response);
  }

  return response.blob();
}

export async function getLatestReport(id: number): Promise<{
  filename: string;
  size: number;
  created_at: string;
}> {
  return fetchAPI(`/competitors/${id}/report/latest`);
}

export async function listReports(id: number): Promise<Array<{
  filename: string;
  competitor_id: number;
  size: number;
  created_at: string;
}>> {
  return fetchAPI(`/competitors/${id}/report/list`);
}

// Alerts
export async function getAlerts(id: number): Promise<Array<{
  type: string;
  competitor_id: number;
  competitor_name: string;
  title: string;
  details: string;
  severity: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}>> {
  return fetchAPI(`/competitors/${id}/alerts`);
}

export async function sendReport(id: number): Promise<{
  status: string;
  report_path: string | null;
  alerts_triggered: number;
}> {
  return fetchAPI(`/competitors/${id}/send_report`, {
    method: 'POST',
  });
}
