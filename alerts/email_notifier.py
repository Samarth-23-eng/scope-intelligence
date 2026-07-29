#!/usr/bin/env python3
"""
Email Notifier for OSINT Platform
Sends alert emails via SMTP.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, List

logger = logging.getLogger(__name__)

# SMTP configuration from environment
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")


def _build_html_email(subject: str, body: str) -> str:
    """
    Build an HTML email template.
    
    Args:
        subject: Email subject
        body: Email body text
        
    Returns:
        HTML formatted email
    """
    # Convert markdown-like formatting to HTML
    html_body = body.replace('\n', '<br>')
    html_body = html_body.replace('**', '<strong>').replace('**', '</strong>')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #f97316; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f5f5f5; padding: 20px; border: 1px solid #ddd; }}
            .footer {{ text-align: center; padding: 10px; color: #666; font-size: 12px; }}
            .severity-high {{ color: #dc2626; font-weight: bold; }}
            .severity-medium {{ color: #d97706; }}
            .severity-low {{ color: #16a34a; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🔍 OSINT Platform Alert</h2>
            </div>
            <div class="content">
                <h3>{subject}</h3>
                <p>{html_body}</p>
            </div>
            <div class="footer">
                <p>OSINT Platform - Competitor Intelligence System</p>
                <p>Generated at {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_email_alert(
    subject: str,
    body: str,
    to_email: Optional[str] = None,
) -> bool:
    """
    Send an alert email.
    
    Args:
        subject: Email subject
        body: Email body text
        to_email: Recipient email (uses ALERT_EMAIL_TO if not specified)
        
    Returns:
        True if sent successfully, False otherwise
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        logger.debug("SMTP not configured, skipping email notification")
        return False
    
    recipient = to_email or ALERT_EMAIL_TO
    if not recipient:
        logger.warning("No recipient email configured")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[OSINT Alert] {subject}"
        msg['From'] = SMTP_USER
        msg['To'] = recipient
        
        # Attach plain text version
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach HTML version
        html_content = _build_html_email(subject, body)
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to SMTP server
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"Email alert sent to {recipient}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_bulk_email_alert(
    subject: str,
    body: str,
    recipients: List[str],
) -> dict:
    """
    Send alert to multiple recipients.
    
    Args:
        subject: Email subject
        body: Email body text
        recipients: List of recipient emails
        
    Returns:
        Dictionary with success/failure counts
    """
    results = {"success": 0, "failed": 0}
    
    for recipient in recipients:
        if send_email_alert(subject, body, to_email=recipient):
            results["success"] += 1
        else:
            results["failed"] += 1
    
    return results


def test_email_connection() -> bool:
    """
    Test the SMTP connection.
    
    Returns:
        True if connection works, False otherwise
    """
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        logger.warning("SMTP not configured")
        return False
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
        
        logger.info("SMTP connection test successful")
        return True
        
    except Exception as e:
        logger.error(f"SMTP connection test failed: {e}")
        return False
