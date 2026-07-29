#!/usr/bin/env python3
"""
Alert Engine for OSINT Platform
Monitors for new intelligence and triggers alerts with deduplication.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from db.postgres import get_connection
from db.redis_client import get_client as get_redis_client

logger = logging.getLogger(__name__)

# Alert type constants
ALERT_NEW_SIGNAL = "new_signal"
ALERT_HIGH_SEVERITY = "high_severity_signal"
ALERT_NEW_PREDICTION = "new_prediction"
ALERT_SUMMARY_UPDATED = "summary_updated"
ALERT_PAGE_CHANGE = "page_change"

# Redis key prefix for alert deduplication
ALERT_KEY_PREFIX = "osint:alert:"
ALERT_EXPIRY_HOURS = 24 * 7  # Keep alert dedup keys for 7 days


def _get_redis():
    """Get Redis client."""
    return get_redis_client()


def _is_alert_duplicate(alert_key: str) -> bool:
    """
    Check if an alert has already been sent recently.
    
    Args:
        alert_key: Unique key for the alert
        
    Returns:
        True if alert is duplicate, False if new
    """
    try:
        redis = _get_redis()
        key = f"{ALERT_KEY_PREFIX}{alert_key}"
        exists = redis.exists(key)
        return bool(exists)
    except Exception as e:
        logger.error(f"Redis check failed: {e}")
        return False


def _mark_alert_sent(alert_key: str) -> None:
    """
    Mark an alert as sent to prevent duplicates.
    
    Args:
        alert_key: Unique key for the alert
    """
    try:
        redis = _get_redis()
        key = f"{ALERT_KEY_PREFIX}{alert_key}"
        redis.setex(key, ALERT_EXPIRY_HOURS * 3600, "1")
    except Exception as e:
        logger.error(f"Redis set failed: {e}")


def _create_alert(
    alert_type: str,
    competitor_id: int,
    competitor_name: str,
    title: str,
    details: str,
    severity: str = "info",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create an alert object.
    
    Args:
        alert_type: Type of alert
        competitor_id: ID of the competitor
        competitor_name: Name of the competitor
        title: Alert title
        details: Alert details
        severity: Alert severity (info, warning, critical)
        metadata: Additional metadata
        
    Returns:
        Alert dictionary
    """
    return {
        "type": alert_type,
        "competitor_id": competitor_id,
        "competitor_name": competitor_name,
        "title": title,
        "details": details,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }


def check_new_signals() -> List[Dict[str, Any]]:
    """
    Check for new strategic signals.
    
    Returns:
        List of triggered alerts
    """
    alerts = []
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get signals from the last hour
                cur.execute("""
                    SELECT s.id, s.competitor_id, s.signal_type, s.description, 
                           s.severity, s.detected_at, c.name as competitor_name
                    FROM signals s
                    JOIN competitors c ON s.competitor_id = c.id
                    WHERE s.detected_at > NOW() - INTERVAL '1 hour'
                    ORDER BY s.detected_at DESC
                """)
                signals = cur.fetchall()
                
                for signal in signals:
                    alert_key = f"signal_{signal['id']}"
                    
                    if _is_alert_duplicate(alert_key):
                        continue
                    
                    # Determine severity
                    severity = "info"
                    if signal['severity'] in ('high', 'critical'):
                        severity = "warning" if signal['severity'] == 'high' else "critical"
                    
                    # Create alert
                    alert = _create_alert(
                        alert_type=ALERT_NEW_SIGNAL,
                        competitor_id=signal['competitor_id'],
                        competitor_name=signal['competitor_name'],
                        title=f"New Signal: {signal['signal_type']}",
                        details=signal['description'],
                        severity=severity,
                        metadata={
                            "signal_id": signal['id'],
                            "signal_type": signal['signal_type'],
                            "detected_at": signal['detected_at'].isoformat(),
                        }
                    )
                    
                    alerts.append(alert)
                    _mark_alert_sent(alert_key)
                    
                    # Also check for high severity
                    if signal['severity'] in ('high', 'critical'):
                        high_alert_key = f"high_signal_{signal['id']}"
                        if not _is_alert_duplicate(high_alert_key):
                            high_alert = _create_alert(
                                alert_type=ALERT_HIGH_SEVERITY,
                                competitor_id=signal['competitor_id'],
                                competitor_name=signal['competitor_name'],
                                title=f"HIGH SEVERITY: {signal['signal_type']}",
                                details=signal['description'],
                                severity="critical",
                                metadata={
                                    "signal_id": signal['id'],
                                    "signal_type": signal['signal_type'],
                                    "severity": signal['severity'],
                                }
                            )
                            alerts.append(high_alert)
                            _mark_alert_sent(high_alert_key)
                
                logger.info(f"Found {len(alerts)} new signal alerts")
                
    except Exception as e:
        logger.error(f"Failed to check new signals: {e}")
    
    return alerts


def check_new_predictions() -> List[Dict[str, Any]]:
    """
    Check for new predictions generated.
    
    Returns:
        List of triggered alerts
    """
    alerts = []
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get predictions from the last hour
                cur.execute("""
                    SELECT p.id, p.competitor_id, p.prediction, p.confidence, 
                           p.timeframe, p.created_at, c.name as competitor_name
                    FROM predictions p
                    JOIN competitors c ON p.competitor_id = c.id
                    WHERE p.created_at > NOW() - INTERVAL '1 hour'
                    ORDER BY p.created_at DESC
                """)
                predictions = cur.fetchall()
                
                for pred in predictions:
                    alert_key = f"prediction_{pred['id']}"
                    
                    if _is_alert_duplicate(alert_key):
                        continue
                    
                    confidence_pct = int(pred['confidence'] * 100)
                    
                    alert = _create_alert(
                        alert_type=ALERT_NEW_PREDICTION,
                        competitor_id=pred['competitor_id'],
                        competitor_name=pred['competitor_name'],
                        title=f"New Prediction ({pred['timeframe']})",
                        details=f"Confidence: {confidence_pct}% - {pred['prediction'][:200]}",
                        severity="info",
                        metadata={
                            "prediction_id": pred['id'],
                            "confidence": pred['confidence'],
                            "timeframe": pred['timeframe'],
                        }
                    )
                    
                    alerts.append(alert)
                    _mark_alert_sent(alert_key)
                
                logger.info(f"Found {len(alerts)} new prediction alerts")
                
    except Exception as e:
        logger.error(f"Failed to check new predictions: {e}")
    
    return alerts


def check_summary_updates() -> List[Dict[str, Any]]:
    """
    Check for updated competitor summaries.
    
    Returns:
        List of triggered alerts
    """
    alerts = []
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get summaries from the last hour
                cur.execute("""
                    SELECT i.id, i.competitor_id, i.summary, i.confidence, 
                           i.created_at, c.name as competitor_name
                    FROM insights i
                    JOIN competitors c ON i.competitor_id = c.id
                    WHERE i.insight_type = 'weekly_summary'
                    AND i.created_at > NOW() - INTERVAL '1 hour'
                    ORDER BY i.created_at DESC
                """)
                summaries = cur.fetchall()
                
                for summary in summaries:
                    alert_key = f"summary_{summary['id']}"
                    
                    if _is_alert_duplicate(alert_key):
                        continue
                    
                    confidence_pct = int(summary['confidence'] * 100)
                    
                    alert = _create_alert(
                        alert_type=ALERT_SUMMARY_UPDATED,
                        competitor_id=summary['competitor_id'],
                        competitor_name=summary['competitor_name'],
                        title="Summary Updated",
                        details=f"New weekly summary generated (Confidence: {confidence_pct}%)",
                        severity="info",
                        metadata={
                            "insight_id": summary['id'],
                            "confidence": summary['confidence'],
                        }
                    )
                    
                    alerts.append(alert)
                    _mark_alert_sent(alert_key)
                
                logger.info(f"Found {len(alerts)} summary update alerts")
                
    except Exception as e:
        logger.error(f"Failed to check summary updates: {e}")
    
    return alerts


def check_page_changes() -> List[Dict[str, Any]]:
    """Create deduplicated alerts for recently detected meaningful page changes."""
    alerts = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT changes.id,
                           changes.competitor_id,
                           changes.change_type,
                           changes.summary,
                           changes.significance,
                           changes.source_url,
                           changes.evidence_id,
                           changes.detected_at,
                           competitors.name AS competitor_name
                    FROM page_changes AS changes
                    JOIN competitors
                      ON competitors.id = changes.competitor_id
                    WHERE changes.detected_at > NOW() - INTERVAL '1 hour'
                    ORDER BY changes.detected_at DESC
                    """
                )
                for change in cur.fetchall():
                    alert_key = f"page_change_{change['id']}"
                    if _is_alert_duplicate(alert_key):
                        continue

                    significance = float(change["significance"])
                    severity = "warning" if (
                        change["change_type"] in {"pricing", "leadership"}
                        or significance >= 0.35
                    ) else "info"
                    alert = _create_alert(
                        alert_type=ALERT_PAGE_CHANGE,
                        competitor_id=change["competitor_id"],
                        competitor_name=change["competitor_name"],
                        title=f"{change['change_type'].title()} Change Detected",
                        details=change["summary"],
                        severity=severity,
                        metadata={
                            "change_id": change["id"],
                            "change_type": change["change_type"],
                            "source_url": change["source_url"],
                            "evidence_id": change["evidence_id"],
                            "significance": significance,
                            "detected_at": change["detected_at"].isoformat(),
                        },
                    )
                    alerts.append(alert)
                    _mark_alert_sent(alert_key)
        logger.info(f"Found {len(alerts)} page change alerts")
    except Exception as e:
        logger.error(f"Failed to check page changes: {e}")
    return alerts


def run_alert_checks() -> List[Dict[str, Any]]:
    """
    Run all alert checks and return triggered alerts.
    
    Returns:
        List of all triggered alerts
    """
    all_alerts = []
    
    logger.info("Running alert checks...")
    
    # Check for new signals
    signal_alerts = check_new_signals()
    all_alerts.extend(signal_alerts)
    
    # Check for new predictions
    prediction_alerts = check_new_predictions()
    all_alerts.extend(prediction_alerts)
    
    # Check for summary updates
    summary_alerts = check_summary_updates()
    all_alerts.extend(summary_alerts)

    # Check for evidence-backed website changes
    page_change_alerts = check_page_changes()
    all_alerts.extend(page_change_alerts)
    
    logger.info(f"Total alerts triggered: {len(all_alerts)}")
    
    return all_alerts


def get_recent_alerts(
    competitor_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Get recent alerts from Redis.
    
    Args:
        competitor_id: Optional filter by competitor ID
        limit: Maximum number of alerts to return
        
    Returns:
        List of recent alerts
    """
    try:
        redis = _get_redis()
        pattern = f"{ALERT_KEY_PREFIX}*"
        
        alerts = []
        for key in redis.scan_iter(match=pattern):
            if key.startswith(f"{ALERT_KEY_PREFIX}osint:"):
                # Skip internal keys
                continue
                
            try:
                data = redis.get(key)
                if data:
                    alert = json.loads(data)
                    
                    if competitor_id and alert.get('competitor_id') != competitor_id:
                        continue
                    
                    alerts.append(alert)
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Sort by timestamp, newest first
        alerts.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return alerts[:limit]
        
    except Exception as e:
        logger.error(f"Failed to get recent alerts: {e}")
        return []


def store_alert(alert: Dict[str, Any]) -> None:
    """
    Store an alert in Redis for later retrieval.
    
    Args:
        alert: Alert dictionary to store
    """
    try:
        redis = _get_redis()
        key = f"{ALERT_KEY_PREFIX}stored:{alert['type']}:{alert['competitor_id']}:{alert['timestamp']}"
        redis.setex(key, ALERT_EXPIRY_HOURS * 3600, json.dumps(alert))
    except Exception as e:
        logger.error(f"Failed to store alert: {e}")


def send_alerts(alerts: List[Dict[str, Any]]) -> None:
    """
    Send alerts through configured notification channels.
    
    Args:
        alerts: List of alerts to send
    """
    if not alerts:
        return
    
    # Import notifiers
    from alerts.discord_notifier import send_discord_alert
    from alerts.email_notifier import send_email_alert
    
    for alert in alerts:
        # Store alert
        store_alert(alert)
        
        # Format message
        message = (
            f"**{alert['title']}**\n"
            f"Competitor: {alert['competitor_name']}\n"
            f"Severity: {alert['severity'].upper()}\n"
            f"Time: {alert['timestamp']}\n"
            f"\n"
            f"{alert['details']}"
        )
        
        # Send Discord notification
        send_discord_alert(message)
        
        # Send email for high severity alerts
        if alert['severity'] in ('warning', 'critical'):
            subject = f"[OSINT Alert] {alert['title']} - {alert['competitor_name']}"
            send_email_alert(subject, message)
