#!/usr/bin/env python3
"""
PDF Report Generator for OSINT Platform
Generates professional PDF reports for competitor intelligence.
"""

import os
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

from db.postgres import get_connection

logger = logging.getLogger(__name__)

# Output directory for generated reports. Resolve it once so every later path
# can be constrained to the same trusted directory.
REPORTS_ROOT = (Path(__file__).resolve().parent / "generated").resolve()
REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
REPORTS_DIR = str(REPORTS_ROOT)
REPORT_FILENAME_PATTERN = re.compile(
    r"^competitor_(?P<competitor_id>[1-9]\d*)_(?P<timestamp>\d{8}_\d{6})\.pdf$"
)


def secure_report_path(
    path_value: str | os.PathLike[str],
    *,
    competitor_id: int | None = None,
    require_exists: bool = True,
) -> Path | None:
    """Return a report path only when it is a valid file inside REPORTS_ROOT."""
    filename = Path(os.fspath(path_value)).name
    match = REPORT_FILENAME_PATTERN.fullmatch(filename)
    if not match:
        return None
    if (
        competitor_id is not None
        and int(match.group("competitor_id")) != int(competitor_id)
    ):
        return None

    candidate = (REPORTS_ROOT / filename).resolve()
    if candidate.parent != REPORTS_ROOT:
        return None
    if require_exists and not candidate.is_file():
        return None
    return candidate


def _get_competitor_info(competitor_id: int) -> Optional[Dict[str, Any]]:
    """Fetch competitor information from database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, domain, industry, created_at
                    FROM competitors
                    WHERE id = %s
                """, (competitor_id,))
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to fetch competitor info: {e}")
        return None


def _get_latest_summary(competitor_id: int) -> Optional[Dict[str, Any]]:
    """Fetch the latest weekly summary insight."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT summary, confidence, created_at
                    FROM insights
                    WHERE competitor_id = %s AND insight_type = 'weekly_summary'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (competitor_id,))
                row = cur.fetchone()
                return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to fetch summary: {e}")
        return None


def _get_signals(competitor_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch latest signals for the competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT signal_type, description, severity, detected_at
                    FROM signals
                    WHERE competitor_id = %s
                    ORDER BY detected_at DESC
                    LIMIT %s
                """, (competitor_id, limit))
                rows = cur.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch signals: {e}")
        return []


def _get_predictions(competitor_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch latest predictions for the competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT prediction, confidence, timeframe, created_at
                    FROM predictions
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (competitor_id, limit))
                rows = cur.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch predictions: {e}")
        return []


def _create_styles():
    """Create custom paragraph styles for the PDF."""
    styles = getSampleStyleSheet()
    
    # Title style
    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=6,
        textColor=colors.HexColor('#f97316'),
        alignment=TA_CENTER,
    ))
    
    # Subtitle style
    styles.add(ParagraphStyle(
        name='ReportSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=20,
        textColor=colors.gray,
        alignment=TA_CENTER,
    ))
    
    # Section header style
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading2'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor('#1a1a1a'),
        borderWidth=1,
        borderColor=colors.HexColor('#f97316'),
        borderPadding=5,
    ))
    
    # The sample stylesheet already owns ``BodyText``. Use a report-specific
    # name so ReportLab does not reject the stylesheet during generation.
    styles.add(ParagraphStyle(
        name='ReportBody',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=8,
        alignment=TA_JUSTIFY,
        leading=14,
    ))
    
    # Signal severity styles
    styles.add(ParagraphStyle(
        name='SignalHigh',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#dc2626'),
        fontWeight='bold',
    ))
    
    styles.add(ParagraphStyle(
        name='SignalMedium',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#d97706'),
    ))
    
    styles.add(ParagraphStyle(
        name='SignalLow',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#16a34a'),
    ))
    
    return styles


def _build_pdf(
    competitor: Dict[str, Any],
    summary: Optional[Dict[str, Any]],
    signals: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    output_path: str,
) -> str:
    """Build the PDF document with all sections."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    
    styles = _create_styles()
    story = []
    
    # Title Section
    story.append(Paragraph("OSINT Intelligence Report", styles['ReportTitle']))
    story.append(Paragraph(
        f"{competitor['name']} - {competitor['domain']}",
        styles['ReportSubtitle']
    ))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}",
        styles['ReportSubtitle']
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#f97316')))
    story.append(Spacer(1, 20))
    
    # Executive Summary Section
    story.append(Paragraph("1. Executive Summary", styles['SectionHeader']))
    story.append(Spacer(1, 10))
    
    if summary:
        story.append(Paragraph(
            f"<b>Confidence Level:</b> {int(summary['confidence'] * 100)}%",
            styles['ReportBody']
        ))
        story.append(Paragraph(
            f"<b>Analysis Date:</b> {summary['created_at'].strftime('%B %d, %Y')}",
            styles['ReportBody']
        ))
        story.append(Spacer(1, 10))
        
        # Split summary into paragraphs
        summary_text = summary['summary']
        for paragraph in summary_text.split('\n\n'):
            if paragraph.strip():
                story.append(Paragraph(paragraph.strip(), styles['ReportBody']))
                story.append(Spacer(1, 5))
    else:
        story.append(Paragraph(
            "No executive summary available. Run the analysis pipeline to generate insights.",
            styles['ReportBody']
        ))
    
    story.append(PageBreak())
    
    # Strategic Signals Section
    story.append(Paragraph("2. Strategic Signals", styles['SectionHeader']))
    story.append(Spacer(1, 10))
    
    if signals:
        # Create signals table
        table_data = [['Type', 'Severity', 'Description', 'Detected']]
        
        severity_colors = {
            'critical': colors.HexColor('#dc2626'),
            'high': colors.HexColor('#ea580c'),
            'medium': colors.HexColor('#d97706'),
            'low': colors.HexColor('#16a34a'),
        }
        
        for signal in signals[:15]:  # Limit to 15 for PDF readability
            detected = signal['detected_at'].strftime('%m/%d/%Y') if hasattr(signal['detected_at'], 'strftime') else str(signal['detected_at'])
            table_data.append([
                signal['signal_type'],
                signal['severity'].upper(),
                Paragraph(signal['description'][:100] + ('...' if len(signal['description']) > 100 else ''), styles['ReportBody']),
                detected,
            ])
        
        table = Table(table_data, colWidths=[1.2*inch, 0.8*inch, 3.5*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f5f5f5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e5e5')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        
        story.append(table)
    else:
        story.append(Paragraph(
            "No strategic signals detected yet.",
            styles['ReportBody']
        ))
    
    story.append(PageBreak())
    
    # Predictions Section
    story.append(Paragraph("3. Predictions", styles['SectionHeader']))
    story.append(Spacer(1, 10))
    
    if predictions:
        for i, pred in enumerate(predictions[:10], 1):
            confidence_pct = int(pred['confidence'] * 100)
            created = pred['created_at'].strftime('%B %d, %Y') if hasattr(pred['created_at'], 'strftime') else str(pred['created_at'])
            
            story.append(Paragraph(
                f"<b>Prediction {i}</b> ({pred['timeframe']})",
                styles['ReportBody']
            ))
            story.append(Paragraph(
                f"Confidence: {confidence_pct}%",
                styles['ReportBody']
            ))
            story.append(Paragraph(
                pred['prediction'],
                styles['ReportBody']
            ))
            story.append(Paragraph(
                f"<i>Generated: {created}</i>",
                styles['ReportBody']
            ))
            story.append(Spacer(1, 15))
    else:
        story.append(Paragraph(
            "No predictions available yet.",
            styles['ReportBody']
        ))
    
    story.append(PageBreak())
    
    # Intelligence Timeline Section
    story.append(Paragraph("4. Intelligence Timeline", styles['SectionHeader']))
    story.append(Spacer(1, 10))
    
    # Combine signals and predictions into a timeline
    timeline_events = []
    
    for signal in signals[:10]:
        timeline_events.append({
            'date': signal['detected_at'],
            'type': 'Signal',
            'description': f"{signal['signal_type']}: {signal['description'][:80]}...",
            'severity': signal['severity'],
        })
    
    for pred in predictions[:5]:
        timeline_events.append({
            'date': pred['created_at'],
            'type': 'Prediction',
            'description': f"{pred['timeframe']}: {pred['prediction'][:80]}...",
            'severity': 'info',
        })
    
    # Sort by date
    timeline_events.sort(key=lambda x: x['date'], reverse=True)
    
    if timeline_events:
        timeline_data = [['Date', 'Type', 'Event']]
        for event in timeline_events[:20]:
            date_str = event['date'].strftime('%m/%d/%Y %H:%M') if hasattr(event['date'], 'strftime') else str(event['date'])
            timeline_data.append([
                date_str,
                event['type'],
                Paragraph(event['description'], styles['ReportBody']),
            ])
        
        timeline_table = Table(timeline_data, colWidths=[1.5*inch, 0.8*inch, 4.2*inch])
        timeline_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fafafa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e5e5')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        
        story.append(timeline_table)
    else:
        story.append(Paragraph(
            "No timeline events available.",
            styles['ReportBody']
        ))
    
    # Footer
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.gray))
    story.append(Paragraph(
        "Generated by Scope Intelligence — Confidential Intelligence Report",
        styles['ReportSubtitle']
    ))
    
    # Build PDF
    doc.build(story)
    
    return output_path


def generate_competitor_report(competitor_id: int) -> Optional[str]:
    """
    Generate a PDF report for a competitor.
    
    Args:
        competitor_id: The ID of the competitor to generate report for
        
    Returns:
        Path to the generated PDF file, or None on failure
    """
    try:
        # Fetch all required data
        competitor = _get_competitor_info(competitor_id)
        if not competitor:
            logger.error(f"Competitor {competitor_id} not found")
            return None
        
        summary = _get_latest_summary(competitor_id)
        signals = _get_signals(competitor_id)
        predictions = _get_predictions(competitor_id)
        
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_competitor_id = int(competitor["id"])
        filename = f"competitor_{safe_competitor_id}_{timestamp}.pdf"
        output_path = secure_report_path(
            filename,
            competitor_id=safe_competitor_id,
            require_exists=False,
        )
        if output_path is None:
            logger.error("Could not construct a safe report path")
            return None
        
        # Build PDF
        result_path = _build_pdf(
            competitor,
            summary,
            signals,
            predictions,
            str(output_path),
        )
        
        logger.info(f"Report generated: {result_path}")
        return result_path
        
    except Exception:
        logger.exception(
            "Failed to generate report for competitor %s",
            competitor_id,
        )
        return None


def get_latest_report(competitor_id: int) -> Optional[str]:
    """
    Get the path to the latest generated report for a competitor.
    
    Args:
        competitor_id: The ID of the competitor
        
    Returns:
        Path to the latest PDF file, or None if no reports exist
    """
    try:
        prefix = f"competitor_{competitor_id}_"
        reports = [
            f for f in os.listdir(REPORTS_DIR)
            if f.startswith(prefix) and f.endswith('.pdf')
        ]
        
        if not reports:
            return None
        
        # Sort by filename (includes timestamp) and get latest
        reports.sort(reverse=True)
        latest = secure_report_path(reports[0], competitor_id=competitor_id)
        return str(latest) if latest else None
        
    except Exception as e:
        logger.error(f"Failed to get latest report: {e}")
        return None


def list_reports(competitor_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    List all generated reports.
    
    Args:
        competitor_id: Optional filter by competitor ID
        
    Returns:
        List of report metadata
    """
    try:
        reports = []
        for filename in os.listdir(REPORTS_DIR):
            if not filename.endswith('.pdf'):
                continue
            
            # Parse filename
            parts = filename.replace('.pdf', '').split('_')
            if len(parts) < 3:
                continue
            
            try:
                file_competitor_id = int(parts[1])
            except ValueError:
                continue
            
            if competitor_id and file_competitor_id != competitor_id:
                continue
            
            filepath = secure_report_path(
                filename,
                competitor_id=file_competitor_id,
            )
            if filepath is None:
                continue
            stat = filepath.stat()
            
            reports.append({
                'filename': filename,
                'competitor_id': file_competitor_id,
                'size': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        
        # Sort by creation time, newest first
        reports.sort(key=lambda x: x['created_at'], reverse=True)
        return reports
        
    except Exception as e:
        logger.error(f"Failed to list reports: {e}")
        return []


def delete_reports(competitor_id: int) -> int:
    """Delete generated PDF reports for one competitor."""
    deleted = 0
    prefix = f"competitor_{competitor_id}_"
    try:
        for filename in os.listdir(REPORTS_DIR):
            if not filename.startswith(prefix) or not filename.endswith(".pdf"):
                continue
            filepath = secure_report_path(filename, competitor_id=competitor_id)
            if filepath is None:
                continue
            filepath.unlink()
            deleted += 1
    except Exception as e:
        logger.error(f"Failed to delete reports for competitor {competitor_id}: {e}")
    return deleted
