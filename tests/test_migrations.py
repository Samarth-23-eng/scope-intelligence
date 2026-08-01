from db.postgres import get_migration_files


def test_migrations_are_numbered_and_ordered():
    names = [path.name for path in get_migration_files()]

    assert names == [
        "001_core_schema.sql",
        "002_intelligence_model.sql",
        "003_page_change_monitoring.sql",
        "004_relationship_intelligence.sql",
        "005_intelligence_foundation_v3.sql",
        "006_collection_engine_v4.sql",
        "007_relationship_fusion_v5.sql",
        "008_investigation_workbench_v6.sql",
        "009_name_first_company_identity_v7.sql",
        "010_access_recovery_and_error_center_v8.sql",
        "011_continuous_intelligence_v9.sql",
        "012_intelligence_verification_v10.sql",
        "013_event_fusion_timeline_v11.sql",
        "014_claim_citation_integrity_v12.sql",
        "015_agent_output_quality_v13.sql",
        "016_llm_gateway_v14.sql",
        "017_graph_studio_v15.sql",
        "018_social_collection_studio_v16.sql",
        "019_workspace_settings_v17.sql",
        "020_deep_research_lab_v18.sql",
    ]


def test_core_schema_preserves_long_source_fields():
    core_sql = get_migration_files()[0].read_text(encoding="utf-8")

    assert "source VARCHAR(512)" in core_sql
    assert "hash VARCHAR(512)" in core_sql


def test_intelligence_migration_defines_recovered_tables():
    intelligence_sql = get_migration_files()[1].read_text(encoding="utf-8")

    for table in ("entities", "relationships", "evidence", "sources"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in intelligence_sql
    assert "DROP TABLE" not in intelligence_sql.upper()


def test_change_monitoring_migration_is_additive_and_evidence_backed():
    change_sql = get_migration_files()[2].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS page_snapshots" in change_sql
    assert "CREATE TABLE IF NOT EXISTS page_changes" in change_sql
    assert "REFERENCES evidence(id)" in change_sql
    assert "DROP TABLE" not in change_sql.upper()


def test_relationship_intelligence_migration_adds_provenance():
    relationship_sql = get_migration_files()[3].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS relationship_evidence" in relationship_sql
    assert "ADD COLUMN IF NOT EXISTS metadata JSONB" in relationship_sql
    assert "ADD COLUMN IF NOT EXISTS evidence_count" in relationship_sql
    assert "DROP TABLE" not in relationship_sql.upper()


def test_intelligence_foundation_migration_is_additive_and_citation_aware():
    foundation_sql = get_migration_files()[4].read_text(encoding="utf-8")

    for table in (
        "pipeline_runs",
        "pipeline_tasks",
        "documents",
        "document_versions",
        "document_chunks",
        "claims",
        "claim_evidence",
        "source_health",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in foundation_sql
    assert "REFERENCES document_versions(id)" in foundation_sql
    assert "REFERENCES claims(id)" in foundation_sql
    assert "DROP TABLE" not in foundation_sql.upper()


def test_collection_engine_migration_adds_resumable_source_acquisition():
    collection_sql = get_migration_files()[5].read_text(encoding="utf-8")

    for table in (
        "collection_campaigns",
        "crawl_frontier",
        "source_profiles",
        "collection_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in collection_sql
    assert "pipeline_run_id BIGINT REFERENCES pipeline_runs(id)" in collection_sql
    assert "UNIQUE (campaign_id, url_hash)" in collection_sql
    assert "DROP TABLE" not in collection_sql.upper()


def test_relationship_fusion_migration_adds_temporal_graph_assessment():
    fusion_sql = get_migration_files()[6].read_text(encoding="utf-8")

    for table in (
        "entity_aliases",
        "relationship_observations",
        "graph_snapshots",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in fusion_sql
    for column in (
        "corroboration_score",
        "source_diversity",
        "freshness_score",
        "contradiction_count",
        "risk_level",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in fusion_sql
    assert "DROP TABLE" not in fusion_sql.upper()


def test_investigation_migration_adds_durable_citation_bound_research():
    investigation_sql = get_migration_files()[7].read_text(encoding="utf-8")

    for table in (
        "investigations",
        "investigation_steps",
        "investigation_findings",
        "investigation_citations",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in investigation_sql
    assert "REFERENCES document_chunks(id)" in investigation_sql
    assert "REFERENCES evidence(id)" in investigation_sql
    assert "cancel_requested_at" in investigation_sql
    assert "DROP TABLE" not in investigation_sql.upper()


def test_name_first_identity_migration_makes_domains_optional():
    identity_sql = get_migration_files()[8].read_text(encoding="utf-8")

    assert "ALTER COLUMN domain DROP NOT NULL" in identity_sql
    assert "domain_verified BOOLEAN" in identity_sql
    assert "identity_context JSONB" in identity_sql
    assert "idx_competitors_name_lower" in identity_sql
    assert "DROP TABLE" not in identity_sql.upper()


def test_access_recovery_migration_adds_opt_in_policy_and_error_center():
    recovery_sql = get_migration_files()[9].read_text(encoding="utf-8")

    assert "access_recovery_enabled BOOLEAN" in recovery_sql
    assert "CREATE TABLE IF NOT EXISTS collection_errors" in recovery_sql
    assert "user_message TEXT NOT NULL" in recovery_sql
    assert "technical_message TEXT NOT NULL" in recovery_sql
    assert "idx_collection_errors_active_fingerprint" in recovery_sql
    assert "DROP TABLE" not in recovery_sql.upper()


def test_continuous_intelligence_migration_adds_scheduler_state_and_audit():
    monitoring_sql = get_migration_files()[10].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS monitoring_profiles" in monitoring_sql
    assert "CREATE TABLE IF NOT EXISTS monitoring_activity" in monitoring_sql
    assert "cadence_minutes BETWEEN 15 AND 10080" in monitoring_sql
    assert "idx_monitoring_profiles_due" in monitoring_sql
    assert "DROP TABLE" not in monitoring_sql.upper()


def test_verification_migration_adds_source_claim_and_review_state():
    verification_sql = get_migration_files()[11].read_text(encoding="utf-8")

    for table in (
        "source_reliability_profiles",
        "claim_verifications",
        "claim_reviews",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in verification_sql
    assert "independent_sources" in verification_sql
    assert "contradiction_score" in verification_sql
    assert "DROP TABLE" not in verification_sql.upper()


def test_event_fusion_migration_adds_temporal_intelligence_model():
    event_sql = get_migration_files()[12].read_text(encoding="utf-8")

    for table in (
        "intelligence_events",
        "intelligence_event_links",
        "intelligence_event_correlations",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in event_sql
    assert "occurred_at TIMESTAMPTZ" in event_sql
    assert "verification_status" in event_sql
    assert "source_event_id < target_event_id" in event_sql
    assert "DROP TABLE" not in event_sql.upper()


def test_claim_citation_integrity_is_enforced_at_transaction_commit():
    citation_sql = get_migration_files()[13].read_text(encoding="utf-8")

    assert "validate_claim_citation_integrity" in citation_sql
    assert "must contain at least one evidence citation" in citation_sql
    assert "contains a citation owned by another company" in citation_sql
    assert "DEFERRABLE INITIALLY DEFERRED" in citation_sql
    assert "AFTER INSERT OR UPDATE OR DELETE ON claim_evidence" in citation_sql


def test_agent_output_quality_migration_tracks_repairs_and_grounding():
    quality_sql = get_migration_files()[14].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS agent_quality_events" in quality_sql
    assert "grounded_items INTEGER" in quality_sql
    assert "rejected_items INTEGER" in quality_sql
    assert "repaired BOOLEAN" in quality_sql
    assert "validation_errors JSONB" in quality_sql


def test_llm_gateway_migration_keeps_credentials_encrypted():
    gateway_sql = get_migration_files()[15].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS llm_configuration" in gateway_sql
    assert "secret_ciphertext TEXT" in gateway_sql
    assert "api_key TEXT" not in gateway_sql
    assert "CHECK (id = 1)" in gateway_sql
    assert "DROP TABLE" not in gateway_sql.upper()


def test_social_collection_migration_is_normalized_and_evidence_backed():
    social_sql = get_migration_files()[17].read_text(encoding="utf-8")

    for table in (
        "social_collection_runs",
        "social_profiles",
        "social_posts",
        "social_comments",
        "social_observations",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in social_sql
    assert "REFERENCES evidence(id)" in social_sql
    assert "REFERENCES document_versions(id)" in social_sql
    assert "refresh_due_at TIMESTAMPTZ" in social_sql
    assert "identity_retained" not in social_sql
    assert "DROP TABLE" not in social_sql.upper()


def test_workspace_settings_migration_keeps_connector_secrets_encrypted():
    settings_sql = get_migration_files()[18].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS workspace_configuration" in settings_sql
    assert "preferences JSONB" in settings_sql
    assert "secret_ciphertexts JSONB" in settings_sql
    assert "Plaintext credentials are never stored" in settings_sql
    assert "api_key TEXT" not in settings_sql
    assert "github_token TEXT" not in settings_sql
    assert "CHECK (id = 1)" in settings_sql
    assert "DROP TABLE" not in settings_sql.upper()


def test_deep_research_migration_is_bounded_and_evidence_backed():
    deep_sql = get_migration_files()[19].read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS deep_research_runs" in deep_sql
    assert "CREATE TABLE IF NOT EXISTS deep_research_results" in deep_sql
    assert "REFERENCES evidence(id)" in deep_sql
    assert "idx_deep_research_one_active_run" in deep_sql
    assert "authentication material must never be stored" in deep_sql
    assert "DROP TABLE" not in deep_sql.upper()
