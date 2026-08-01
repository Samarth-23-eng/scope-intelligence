// API response types for Scope Intelligence

export interface Competitor {
  id: number;
  name: string;
  domain: string | null;
  industry: string | null;
  created_at: string;
  updated_at: string | null;
  website: string | null;
  description: string | null;
  hq: string | null;
  founded: number | null;
  executives: unknown[];
  subsidiaries: unknown[];
  key_products: unknown[];
  technologies: unknown[];
  social_media: Record<string, unknown>;
  careers_url: string | null;
  blog_url: string | null;
  discovery_status: string;
  domain_verified: boolean;
  identity_context: Record<string, unknown>;
  access_recovery_enabled: boolean;
}

export interface Insight {
  id: number;
  competitor_id: number;
  insight_type: string;
  summary: string;
  confidence: number;
  created_at: string;
}

export interface Signal {
  id: number;
  competitor_id: number;
  signal_type: string;
  description: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  detected_at: string;
}

export interface Prediction {
  id: number;
  competitor_id: number;
  prediction: string;
  confidence: number;
  timeframe: string;
  created_at: string;
}

export interface RawData {
  id: number;
  competitor_id: number;
  source: string;
  content: string;
  collected_at: string;
  hash: string;
  metadata: Record<string, unknown>;
}

export interface PageChange {
  id: number;
  competitor_id: number;
  source_url: string;
  title: string | null;
  change_type: 'pricing' | 'product' | 'integration' | 'leadership' | 'hiring' | 'website';
  summary: string;
  before_excerpt: string | null;
  after_excerpt: string | null;
  similarity: number;
  significance: number;
  detected_at: string;
  evidence_id: number;
  evidence_snippet: string | null;
  evidence_confidence: number;
  evidence_collected_at: string;
}

export interface DashboardCompetitor {
  id: number;
  name: string;
  domain: string | null;
  industry: string | null;
  latest_summary: string | null;
  signal_count: number;
  prediction_count: number;
  last_updated: string | null;
}

export interface DashboardResponse {
  competitors: DashboardCompetitor[];
  total_count: number;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
  competitors_count: number;
  services: Record<string, string>;
}

export interface EmptySummaryResponse {
  summary: null;
  message: string;
}

export interface PipelineResponse {
  status: string;
  competitor_id: number;
  run_id: number | null;
}

export interface PipelineStatus {
  status: 'idle' | 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  competitor_id: number;
  stage: string | null;
  stage_status: string | null;
  started_at: string | null;
  finished_at: string | null;
  results: Record<string, unknown>;
  models: Record<string, string>;
  error: string | null;
  run_id: number | null;
}

export interface PipelineDataDeleteResponse {
  status: 'deleted';
  competitor_id: number;
  deleted: Record<string, number>;
  reports_deleted: number;
}

export interface ModelCatalog {
  models: string[];
  default: string;
}

export interface LLMConnection {
  provider: string;
  display_name: string;
  base_url: string;
  model: string;
  auth_mode: 'api_key' | 'bearer' | 'none';
  enabled: boolean;
  source: 'saved' | 'environment';
  last_status: 'untested' | 'connected' | 'error';
  last_error: string | null;
  last_tested_at: string | null;
  has_secret: boolean;
  configured: boolean;
}

export interface LLMProviderPreset {
  id: string;
  label: string;
  base_url: string;
  default_auth_mode: 'api_key' | 'bearer' | 'none';
}

export interface LLMProviderPresets {
  providers: LLMProviderPreset[];
  auth_modes: Array<{
    id: 'api_key' | 'bearer' | 'none';
    label: string;
    description: string;
  }>;
}

export interface LLMConnectionUpdate {
  provider: string;
  display_name?: string;
  base_url?: string;
  model: string;
  auth_mode: 'api_key' | 'bearer' | 'none';
  api_key?: string;
  enabled: boolean;
  clear_secret?: boolean;
}

export interface WorkspacePreferences {
  crawler_max_pages: number;
  crawler_max_depth: number;
  crawler_concurrency: number;
  crawler_max_browser_fallbacks: number;
  crawler_request_timeout_seconds: number;
  crawler_retry_attempts: number;
  crawler_respect_robots: boolean;
  crawler_max_pdf_pages: number;
  crawler_max_external_profiles: number;
  enable_external_sources: boolean;
  enable_job_scraper: boolean;
  enable_linkedin_scraper: boolean;
  job_sources: string;
  job_results_wanted: number;
  job_search_location: string;
  job_hours_old: number;
  youtube_max_videos: number;
  youtube_comments_per_video: number;
  enable_youtube_transcripts: boolean;
  github_max_repositories: number;
  github_releases_per_repository: number;
  enable_social_collection: boolean;
  social_max_items_per_run: number;
  social_max_comments_per_item: number;
  social_request_delay_seconds: number;
  social_run_timeout_seconds: number;
  social_youtube_retention_days: number;
  enable_deep_research: boolean;
  deep_research_max_results: number;
  deep_research_max_pages: number;
  deep_research_request_delay_seconds: number;
  deep_research_timeout_seconds: number;
}

export interface WorkspaceSecretState {
  configured: boolean;
  source: 'saved' | 'environment' | 'missing';
}

export interface WorkspaceSettings {
  preferences: WorkspacePreferences;
  secrets: Record<'youtube_api_key' | 'github_token' | 'newsapi_key', WorkspaceSecretState>;
  source: 'saved' | 'environment';
  updated_at: string | null;
  requires_restart: string[];
}

export type WorkspaceSettingsUpdate = Partial<WorkspacePreferences> & {
  youtube_api_key?: string;
  github_token?: string;
  newsapi_key?: string;
  clear_youtube_api_key?: boolean;
  clear_github_token?: boolean;
  clear_newsapi_key?: boolean;
};

export interface IntegrationTestResult {
  ok: boolean;
  integration: 'youtube' | 'github' | 'newsapi';
  message: string;
}

export interface DeepResearchResult {
  id: number;
  run_id: number;
  competitor_id: number;
  engine: string;
  source_url: string;
  title: string | null;
  excerpt: string | null;
  fetch_status: 'discovered' | 'collected' | 'skipped' | 'failed';
  http_status: number | null;
  evidence_id: number | null;
  metadata: Record<string, unknown>;
  discovered_at: string;
  collected_at: string | null;
}

export interface DeepResearchRun {
  id: number;
  competitor_id: number;
  query: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  options: Record<string, unknown>;
  checkpoint: {
    stage?: string;
    current?: number;
    total?: number;
    discovered?: number;
    diagnostics?: Array<{ code: string; message: string; url_hash?: string }>;
    engines?: Array<{ engine: string; ok: boolean; code?: string; results?: number; http_status?: number }>;
  };
  summary: Record<string, unknown>;
  error: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  results?: DeepResearchResult[];
}

export interface DeepResearchOverview {
  enabled: boolean;
  experimental: true;
  policy: string;
  limits: { max_results: number; max_pages: number; timeout_seconds: number };
  runs: DeepResearchRun[];
  latest_run: DeepResearchRun | null;
}

export interface DiscoverResponse {
  competitor: Competitor;
  website: string | null;
  rss_feeds: string[];
  confidence: number;
  search_candidates: number;
  existing: boolean;
  resolution_mode: 'website_assisted' | 'name_first';
}

export interface Entity {
  id: number;
  competitor_id: number;
  name: string;
  entity_type: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Relationship {
  id: number;
  source_entity_id: number;
  source_name: string;
  source_type: string;
  target_entity_id: number;
  target_name: string;
  target_type: string;
  relationship_type: string;
  weight: number;
  rationale: string | null;
  extraction_method: string;
  evidence_count: number;
  corroboration_score: number;
  source_diversity: number;
  freshness_score: number;
  contradiction_count: number;
  risk_level: 'unassessed' | 'low' | 'medium' | 'high' | 'critical';
  status: 'active' | 'stale' | 'disputed';
  metadata: Record<string, unknown>;
  created_at: string;
  first_seen_at: string;
  last_seen_at: string;
  evidence: RelationshipEvidence[];
}

export interface StrategicGraphNode {
  entity_id: number;
  name: string;
  entity_type: string;
  degree: number;
  weighted_degree: number;
  page_rank: number;
}

export interface DuplicateEntityCandidate {
  normalized_alias: string;
  entity_ids: number[];
  entity_names: string[];
}

export interface RelationshipIntelligence {
  snapshot_id: number | null;
  competitor_id: number;
  entity_count: number;
  relationship_count: number;
  component_count: number;
  disputed_relationships: number;
  weak_relationships: number;
  metrics: {
    component_count?: number;
    largest_component?: number;
    isolated_entities?: number;
    alias_count?: number;
    strategic_nodes: StrategicGraphNode[];
    duplicate_candidates: DuplicateEntityCandidate[];
    risk_distribution: Record<'low' | 'medium' | 'high' | 'critical', number>;
  };
  created_at: string | null;
}

export interface GraphSnapshot {
  id: number;
  pipeline_run_id: number | null;
  entity_count: number;
  relationship_count: number;
  component_count: number;
  disputed_relationships: number;
  weak_relationships: number;
  metrics: Record<string, unknown>;
  created_at: string;
  has_state: boolean;
}

export interface GraphPath {
  mode: 'strongest' | 'shortest';
  hop_count: number;
  score: number;
  nodes: Entity[];
  relationships: Relationship[];
}

export interface GraphDiff {
  from_snapshot_id: number;
  to_snapshot_id: number;
  entities: {
    added: Entity[];
    removed: Entity[];
  };
  relationships: {
    added: Relationship[];
    removed: Relationship[];
    changed: Array<{
      relationship_id: number;
      change_type: 'strengthened' | 'weakened' | 'disputed' | 'updated';
      weight_delta: number;
      before: Relationship;
      after: Relationship;
    }>;
  };
  summary: {
    entities_added: number;
    entities_removed: number;
    relationships_added: number;
    relationships_removed: number;
    relationships_changed: number;
  };
}

export type InvestigationStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled';

export interface InvestigationStep {
  id: number;
  investigation_id: number;
  step_index: number;
  question: string;
  rationale: string | null;
  search_query: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  answer: string | null;
  evidence_count: number;
  source_diversity: number;
  metadata: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface InvestigationFinding {
  id: number;
  investigation_id: number;
  step_id: number | null;
  finding_type: 'fact' | 'inference' | 'risk' | 'opportunity';
  statement: string;
  confidence: number;
  status: 'supported' | 'provisional' | 'disputed';
  evidence_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface InvestigationCitation {
  id: number;
  investigation_id: number;
  step_id: number | null;
  finding_id: number | null;
  evidence_id: number | null;
  document_chunk_id: number | null;
  stance: 'supports' | 'contradicts' | 'context';
  excerpt: string | null;
  source_url: string;
  title: string | null;
  source_type: string;
  relevance: number;
  created_at: string;
}

export interface Investigation {
  id: number;
  competitor_id: number;
  pipeline_run_id: number | null;
  title: string;
  question: string;
  scope: Record<string, unknown>;
  status: InvestigationStatus;
  model: string | null;
  max_steps: number;
  completed_steps: number;
  evidence_count: number;
  source_diversity: number;
  confidence: number;
  executive_summary: string | null;
  answer: string | null;
  gaps: string[];
  metadata: Record<string, unknown>;
  error: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  steps?: InvestigationStep[];
  findings?: InvestigationFinding[];
  citations?: InvestigationCitation[];
}

export interface RelationshipEvidence {
  id: number;
  source_url: string;
  title: string | null;
  snippet: string | null;
  confidence: number;
  collected_at: string;
}

export interface PipelineTask {
  id: number;
  run_id: number;
  task_key: string;
  stage: string;
  agent_name: string;
  status: 'pending' | 'running' | 'retrying' | 'completed' | 'failed' | 'skipped' | 'cancelled';
  attempt: number;
  max_attempts: number;
  output: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  quality: {
    status?: 'valid' | 'repaired' | 'rejected' | 'empty' | 'error';
    attempts?: number;
    parse_valid?: boolean;
    schema_valid?: boolean;
    repaired?: boolean;
    grounded_items?: number;
    rejected_items?: number;
    latency_ms?: number;
    validation_errors?: string[];
    metadata?: {
      response_chars?: number;
      retrieval?: {
        candidate_chunks?: number;
        selected_chunks?: number;
        selected_documents?: number;
        selected_domains?: number;
        selected_source_types?: number;
        prompt_chars?: number;
        prompt_char_budget?: number;
        used_recent_fallback?: boolean;
      };
    };
    created_at?: string;
  };
}

export interface PipelineRun {
  id: number;
  competitor_id: number;
  parent_run_id: number | null;
  run_type: string;
  trigger_type: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  model: string | null;
  configuration: Record<string, unknown>;
  summary: Record<string, unknown>;
  error: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  tasks: PipelineTask[];
}

export interface EvidenceDocument {
  id: number;
  competitor_id: number;
  canonical_url: string;
  source_type: string;
  source_name: string | null;
  media_type: string;
  title: string | null;
  author: string | null;
  published_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  current_version_id: number | null;
  version_count: number;
  chunk_count: number;
  indexed_chunk_count: number;
  metadata: Record<string, unknown>;
}

export interface ClaimEvidence {
  evidence_id: number | null;
  document_chunk_id: number | null;
  stance: 'supports' | 'contradicts' | 'context';
  excerpt: string | null;
  confidence: number;
  source_url: string | null;
  title: string | null;
}

export interface IntelligenceClaim {
  id: number;
  competitor_id: number;
  pipeline_run_id: number | null;
  claim_type: string;
  subject: string | null;
  predicate: string | null;
  object_text: string | null;
  statement: string;
  confidence: number;
  status: 'proposed' | 'supported' | 'confirmed' | 'disputed' | 'stale';
  occurred_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  evidence: ClaimEvidence[];
}

export interface EvidenceSearchHit {
  chunk_id: number;
  evidence_id: number | null;
  document_id: number;
  document_version_id: number;
  source_url: string;
  title: string | null;
  source_type: string;
  content: string;
  published_at: string | null;
  collected_at: string | null;
  score: number;
  retrieval_methods: string[];
  metadata: Record<string, unknown>;
}

export interface SourceHealth {
  id: number;
  competitor_id: number;
  adapter_name: string;
  source_key: string;
  status: 'healthy' | 'degraded' | 'error' | 'disabled';
  consecutive_failures: number;
  total_attempts: number;
  total_items: number;
  last_latency_ms: number | null;
  last_error: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  metadata: Record<string, unknown>;
}

export interface EvidenceOverview {
  competitor_id: number;
  documents: number;
  document_versions: number;
  chunks: number;
  indexed_chunks: number;
  claims: number;
  cited_claims: number;
  citation_coverage: number;
  source_adapters: number;
  healthy_sources: number;
}

export interface CollectionCampaign {
  id: number;
  competitor_id: number;
  pipeline_run_id: number | null;
  campaign_type: string;
  status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
  strategy: string;
  budget: Record<string, unknown>;
  statistics: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  frontier: Record<string, number>;
}

export interface SourceProfile {
  id: number;
  competitor_id: number;
  source_type: string;
  profile_url: string;
  profile_key: string | null;
  status: 'discovered' | 'verified' | 'active' | 'error' | 'disabled';
  confidence: number;
  discovered_from: string | null;
  last_collected_at: string | null;
  verified_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CollectionCoverage {
  competitor_id: number;
  documents_by_source: Array<{
    source_type: string;
    documents: number;
    recent: number;
  }>;
  profiles: Array<{
    source_type: string;
    status: string;
    count: number;
  }>;
  adapters: Array<{
    adapter_name: string;
    events: number;
    successful_events: number;
    items: number;
    bytes_collected: number;
    last_event_at: string | null;
  }>;
  campaigns: {
    campaigns: number;
    completed: number;
    partial: number;
    last_completed_at: string | null;
  };
}

export interface CollectionError {
  id: number;
  competitor_id: number;
  pipeline_run_id: number | null;
  campaign_id: number | null;
  url: string | null;
  error_code: string;
  category: string;
  http_status: number | null;
  severity: 'info' | 'warning' | 'error' | 'critical';
  engine: string | null;
  attempts: string[];
  technical_message: string;
  user_message: string;
  suggested_action: string | null;
  recoverable: boolean;
  metadata: Record<string, unknown>;
  occurrences: number;
  first_occurred_at: string;
  last_occurred_at: string;
  resolved_at: string | null;
  created_at: string;
}

export type SocialCollectionMode = 'discover' | 'account' | 'evidence';
export type SocialRunStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled';

export interface SocialConnector {
  platform: string;
  label: string;
  version: string;
  capabilities: string[];
  modes: SocialCollectionMode[];
  public_access: boolean;
  api_key_configured: boolean;
  comments_require_api_key: boolean;
  warnings: string[];
  readiness: 'ready' | 'needs_configuration' | 'disabled';
  features: Record<string, 'ready' | 'needs_configuration' | 'disabled'>;
}

export interface SocialRunEvent {
  id: number;
  adapter_name: string;
  event_type: string;
  success: boolean;
  items: number;
  bytes_collected: number;
  latency_ms: number | null;
  error: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SocialRun {
  id: number;
  competitor_id: number;
  pipeline_run_id: number;
  campaign_id: number;
  platform: string;
  mode: SocialCollectionMode;
  query: string | null;
  target_url: string | null;
  connector_version: string;
  options: {
    max_items?: number;
    include_comments?: boolean;
    comment_limit?: number;
    include_replies?: boolean;
    max_reply_depth?: number;
    include_transcript?: boolean;
  };
  checkpoint: {
    stage?: string;
    updated_at?: string;
    current?: number;
    total?: number;
    video_id?: string;
    comments?: number;
    budget?: number;
    persisted?: Record<string, number>;
    diagnostics?: Array<{
      code: string;
      message: string;
      severity: 'info' | 'warning' | 'error';
      recoverable: boolean;
      suggested_action?: string | null;
    }>;
  };
  created_at: string;
  updated_at: string;
  status: SocialRunStatus;
  summary: Record<string, unknown>;
  statistics: Record<string, unknown>;
  error: string | null;
  cancel_requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  task_id: number | null;
  task_status: string | null;
  attempt: number | null;
  heartbeat_at: string | null;
  events?: SocialRunEvent[];
}

export interface SocialOverview {
  competitor_id: number;
  profiles: number;
  posts: number;
  comments: number;
  observations: number;
  refresh_due: number;
  active_runs: number;
  by_platform: Array<{ platform: string; posts: number }>;
  last_completed_at: string | null;
}

export interface SocialCollectionInput {
  platform: 'youtube';
  mode: SocialCollectionMode;
  target: string;
  options: {
    max_items: number;
    include_comments: boolean;
    comment_limit: number;
    include_replies: boolean;
    max_reply_depth: number;
    include_transcript: boolean;
  };
}

export interface SocialProfileRecord {
  id: number;
  competitor_id: number;
  platform: string;
  platform_profile_id: string;
  handle: string | null;
  display_name: string | null;
  profile_url: string;
  biography: string | null;
  follower_count: number | null;
  following_count: number | null;
  content_count: number | null;
  verified: boolean;
  metadata: Record<string, unknown>;
  evidence_id: number | null;
  document_version_id: number | null;
  refresh_due_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SocialPostRecord {
  id: number;
  competitor_id: number;
  profile_id: number | null;
  first_seen_run_id: number | null;
  latest_seen_run_id: number | null;
  platform: string;
  platform_post_id: string;
  content_type: string;
  url: string;
  title: string | null;
  body: string | null;
  author_platform_id: string | null;
  author_handle: string | null;
  published_at: string | null;
  language: string | null;
  engagement: Record<string, number>;
  media: Array<{
    type?: string;
    url?: string;
    width?: number;
    height?: number;
  }>;
  metadata: Record<string, unknown>;
  evidence_id: number | null;
  document_version_id: number | null;
  refresh_due_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface SocialCommentRecord {
  id: number;
  competitor_id: number;
  post_id: number;
  first_seen_run_id: number | null;
  latest_seen_run_id: number | null;
  platform: string;
  platform_comment_id: string;
  parent_platform_comment_id: string | null;
  thread_root_platform_comment_id: string | null;
  depth: number;
  text: string;
  like_count: number;
  reply_count: number;
  published_at: string | null;
  metadata: Record<string, unknown>;
  evidence_id: number | null;
  document_version_id: number | null;
  refresh_due_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface AccessRecoveryConfig {
  available: boolean;
  enabled: boolean;
  experimental: boolean;
  max_attempts_per_campaign: number;
  label: string;
}

export interface MonitoringProfile {
  id: number;
  competitor_id: number;
  enabled: boolean;
  cadence_minutes: number;
  focus_topics: string[];
  alert_severities: Array<'low' | 'medium' | 'high' | 'critical'>;
  last_scheduled_at: string | null;
  next_run_at: string | null;
  last_run_id: number | null;
  last_status:
    | 'idle'
    | 'queued'
    | 'running'
    | 'completed'
    | 'partial'
    | 'failed'
    | 'cancelled'
    | 'skipped';
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonitoringActivity {
  id: number;
  monitoring_profile_id: number;
  competitor_id: number;
  pipeline_run_id: number | null;
  event_type: string;
  status: string;
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface MonitoringOverview {
  profile: MonitoringProfile;
  metrics: {
    changes_7d: number;
    signals_7d: number;
    priority_signals_7d: number;
    documents_7d: number;
    open_collection_errors: number;
  };
  activity: MonitoringActivity[];
  latest_run: {
    id: number;
    status: string;
    trigger_type: string;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
  } | null;
  scheduler_online: boolean;
}

export interface SourceReliabilityProfile {
  id: number;
  competitor_id: number;
  source_domain: string;
  source_type: string;
  reliability: number;
  tier: 'primary' | 'reliable' | 'contextual' | 'low';
  basis: string;
  is_override: boolean;
  evidence_count: number;
  last_seen_at: string | null;
  assessed_at: string;
  updated_at: string;
}

export interface ClaimVerification {
  id: number;
  claim_id: number;
  competitor_id: number;
  support_count: number;
  contradiction_count: number;
  independent_sources: number;
  corroboration_score: number;
  contradiction_score: number;
  freshness_score: number;
  source_quality: number;
  final_confidence: number;
  status: 'proposed' | 'supported' | 'confirmed' | 'disputed' | 'stale';
  risk_flags: string[];
  rationale: string;
  metadata: Record<string, unknown>;
  assessed_at: string;
  statement: string;
  claim_type: string;
  claim_created_at: string;
  claim_metadata: Record<string, unknown>;
}

export interface ClaimReview {
  id: number;
  claim_id: number;
  competitor_id: number;
  decision: 'supported' | 'confirmed' | 'disputed' | 'stale';
  previous_status: string;
  note: string | null;
  created_at: string;
  statement: string;
}

export interface VerificationOverview {
  summary: {
    total_claims: number;
    confirmed: number;
    supported: number;
    needs_review: number;
    disputed: number;
    average_confidence: number;
    source_count: number;
  };
  queue: ClaimVerification[];
  verifications: ClaimVerification[];
  sources: SourceReliabilityProfile[];
  reviews: ClaimReview[];
}

export interface IntelligenceEvent {
  id: number;
  competitor_id: number;
  event_key: string;
  event_type: string;
  title: string;
  summary: string;
  impact_level: 'low' | 'medium' | 'high' | 'critical';
  confidence: number;
  verification_status:
    | 'proposed'
    | 'supported'
    | 'confirmed'
    | 'disputed'
    | 'stale';
  status: 'active' | 'developing' | 'disputed' | 'stale';
  source_count: number;
  occurred_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
  metadata: {
    observation_count?: number;
    source_kinds?: string[];
    date_basis?: string;
    span_days?: number;
    momentum?: string;
  };
  created_at: string;
  updated_at: string;
  linked_observations: number;
  correlation_count: number;
}

export interface EventCorrelation {
  id: number;
  competitor_id: number;
  source_event_id: number;
  target_event_id: number;
  correlation_type: string;
  score: number;
  rationale: string;
  created_at: string;
  source_title: string;
  target_title: string;
}

export interface TimelineOverview {
  summary: {
    total_events: number;
    recent_events: number;
    previous_period_events: number;
    high_impact: number;
    disputed: number;
    developing: number;
    top_type: string | null;
  };
  events: IntelligenceEvent[];
  correlations: EventCorrelation[];
  weekly_activity: Array<{
    start: string;
    end: string;
    events: number;
    high_impact: number;
  }>;
  event_types: Record<string, number>;
}
