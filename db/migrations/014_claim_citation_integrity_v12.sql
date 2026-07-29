-- Enforce the Phase 1 citation contract at transaction commit.
-- Claims and their citations are inserted in the same transaction, so this
-- must be deferred until all claim_evidence rows have been written.

CREATE OR REPLACE FUNCTION validate_claim_citation_integrity(
    checked_claim_id BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    claim_competitor_id INTEGER;
BEGIN
    SELECT competitor_id
    INTO claim_competitor_id
    FROM claims
    WHERE id = checked_claim_id;

    -- The parent claim may have been deleted in the same transaction.
    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM claim_evidence
        WHERE claim_id = checked_claim_id
    ) THEN
        RAISE EXCEPTION
            'Claim % must contain at least one evidence citation',
            checked_claim_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'claims_require_evidence_citation';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM claim_evidence link
        LEFT JOIN evidence item
          ON item.id = link.evidence_id
        LEFT JOIN document_chunks chunk
          ON chunk.id = link.document_chunk_id
        WHERE link.claim_id = checked_claim_id
          AND (
              (
                  link.evidence_id IS NOT NULL
                  AND item.competitor_id IS DISTINCT FROM claim_competitor_id
              )
              OR (
                  link.document_chunk_id IS NOT NULL
                  AND chunk.competitor_id IS DISTINCT FROM claim_competitor_id
              )
          )
    ) THEN
        RAISE EXCEPTION
            'Claim % contains a citation owned by another company',
            checked_claim_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'claim_citations_match_competitor';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_claim_citation_from_claim()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM validate_claim_citation_integrity(NEW.id);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_claim_citation_from_link()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM validate_claim_citation_integrity(NEW.claim_id);
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE')
       AND (TG_OP = 'DELETE' OR OLD.claim_id IS DISTINCT FROM NEW.claim_id) THEN
        PERFORM validate_claim_citation_integrity(OLD.claim_id);
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS claims_require_evidence_citation ON claims;
CREATE CONSTRAINT TRIGGER claims_require_evidence_citation
AFTER INSERT OR UPDATE ON claims
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_claim_citation_from_claim();

DROP TRIGGER IF EXISTS claim_links_preserve_citation_integrity ON claim_evidence;
CREATE CONSTRAINT TRIGGER claim_links_preserve_citation_integrity
AFTER INSERT OR UPDATE OR DELETE ON claim_evidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_claim_citation_from_link();
