#!/usr/bin/env python3
"""
Report API routes for Scope Intelligence
Endpoints for generating reports and managing alerts.
"""

import os
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db.postgres import get_connection
from reports.pdf_generator import (
    generate_competitor_report,
    get_latest_report,
    list_reports,
)
from alerts.alert_engine import (
    run_alert_checks,
    get_recent_alerts,
    send_alerts,
)
from alerts.discord_notifier import send_discord_alert
from alerts.email_notifier import send_email_alert

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Pydantic Models
# ============================================================

class ReportResponse(BaseModel):
    filename: str
    path: str
    size: int
    created_at: str


class AlertResponse(BaseModel):
    type: str
    competitor_id: int
    competitor_name: str
    title: str
    details: str
    severity: str
    timestamp: str
    metadata: dict


class SendReportResponse(BaseModel):
    status: str
    report_path: Optional[str]
    alerts_triggered: int


# ============================================================
# Helper Functions
# ============================================================

def _verify_competitor_exists(competitor_id: int) -> bool:
    """Check if a competitor exists in the database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM competitors WHERE id = %s", (competitor_id,))
                return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Failed to verify competitor: {e}")
        return False


def _background_generate_and_alert(competitor_id: int) -> None:
    """Background task to generate report and send alerts."""
    try:
        # Generate report
        report_path = generate_competitor_report(competitor_id)
        
        # Run alert checks
        alerts = run_alert_checks()
        
        # Send alerts
        if alerts:
            send_alerts(alerts)
        
        logger.info(f"Background report generation complete for competitor {competitor_id}")
        
    except Exception as e:
        logger.error(f"Background task failed: {e}")


# ============================================================
# Endpoints
# ============================================================

@router.get("/competitors/{competitor_id}/report")
async def get_report(competitor_id: int):
    """
    Generate and download a PDF report for a competitor.
    
    Returns the PDF file as a download.
    """
    # Verify competitor exists
    if not _verify_competitor_exists(competitor_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    try:
        # Generate report
        report_path = generate_competitor_report(competitor_id)
        
        if not report_path or not os.path.exists(report_path):
            raise HTTPException(status_code=500, detail="Failed to generate report")
        
        # Get filename for download
        filename = os.path.basename(report_path)
        
        return FileResponse(
            path=report_path,
            filename=filename,
            media_type="application/pdf",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report")


@router.get("/competitors/{competitor_id}/report/latest")
async def get_latest_report_endpoint(competitor_id: int):
    """
    Get the latest generated report for a competitor.
    
    Returns report metadata.
    """
    # Verify competitor exists
    if not _verify_competitor_exists(competitor_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    try:
        report_path = get_latest_report(competitor_id)
        
        if not report_path:
            raise HTTPException(status_code=404, detail="No reports found")
        
        filename = os.path.basename(report_path)
        stat = os.stat(report_path)
        
        return ReportResponse(
            filename=filename,
            path=report_path,
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get latest report: {e}")
        raise HTTPException(status_code=500, detail="Failed to get report")


@router.get("/competitors/{competitor_id}/report/list")
async def list_competitor_reports(competitor_id: int):
    """
    List all reports for a competitor.
    
    Returns list of report metadata.
    """
    # Verify competitor exists
    if not _verify_competitor_exists(competitor_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    try:
        reports = list_reports(competitor_id)
        return reports
        
    except Exception as e:
        logger.error(f"Failed to list reports: {e}")
        raise HTTPException(status_code=500, detail="Failed to list reports")


@router.get("/competitors/{competitor_id}/alerts")
async def get_alerts(competitor_id: int):
    """
    Get recent alerts for a competitor.
    
    Returns list of alerts.
    """
    # Verify competitor exists
    if not _verify_competitor_exists(competitor_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    try:
        alerts = get_recent_alerts(competitor_id=competitor_id)
        return alerts
        
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alerts")


@router.get("/alerts")
async def get_all_alerts():
    """
    Get all recent alerts across all competitors.
    
    Returns list of alerts.
    """
    try:
        alerts = get_recent_alerts()
        return alerts
        
    except Exception as e:
        logger.error(f"Failed to get alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alerts")


@router.post("/competitors/{competitor_id}/send_report")
async def send_report(competitor_id: int, background_tasks: BackgroundTasks):
    """
    Generate report and send alerts.
    
    Triggers background report generation and sends notifications.
    """
    # Verify competitor exists
    if not _verify_competitor_exists(competitor_id):
        raise HTTPException(status_code=404, detail="Competitor not found")
    
    try:
        # Add background task
        background_tasks.add_task(_background_generate_and_alert, competitor_id)
        
        return SendReportResponse(
            status="started",
            report_path=None,
            alerts_triggered=0,
        )
        
    except Exception as e:
        logger.error(f"Failed to send report: {e}")
        raise HTTPException(status_code=500, detail="Failed to send report")


@router.post("/alerts/check")
async def trigger_alert_check():
    """
    Manually trigger alert checks.
    
    Runs all alert checks and sends any triggered alerts.
    """
    try:
        alerts = run_alert_checks()
        
        if alerts:
            send_alerts(alerts)
        
        return {
            "status": "completed",
            "alerts_triggered": len(alerts),
            "alerts": alerts,
        }
        
    except Exception as e:
        logger.error(f"Failed to run alert check: {e}")
        raise HTTPException(status_code=500, detail="Failed to run alert check")


@router.post("/alerts/test-discord")
async def test_discord():
    """Test Discord webhook connection."""
    from alerts.discord_notifier import test_discord_connection
    
    success = test_discord_connection()
    
    return {
        "status": "success" if success else "failed",
        "message": "Discord connection test passed" if success else "Discord connection test failed",
    }


@router.post("/alerts/test-email")
async def test_email():
    """Test email SMTP connection."""
    from alerts.email_notifier import test_email_connection
    
    success = test_email_connection()
    
    return {
        "status": "success" if success else "failed",
        "message": "Email connection test passed" if success else "Email connection test failed",
    }
