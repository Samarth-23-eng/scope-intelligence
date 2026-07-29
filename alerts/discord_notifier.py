#!/usr/bin/env python3
"""
Discord Notifier for OSINT Platform
Sends alerts to Discord via webhook.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Discord webhook URL from environment
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


def send_discord_alert(message: str) -> bool:
    """
    Send an alert to Discord via webhook.
    
    Args:
        message: The message to send (supports markdown)
        
    Returns:
        True if sent successfully, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        logger.debug("Discord webhook URL not configured, skipping notification")
        return False
    
    try:
        # Build Discord embed
        embed = {
            "title": "🔍 OSINT Platform Alert",
            "description": message,
            "color": 0xf97316,  # Orange accent color
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {
                "text": "OSINT Platform - Competitor Intelligence"
            }
        }
        
        payload = {
            "embeds": [embed]
        }
        
        # Send request
        with httpx.Client() as client:
            response = client.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=10.0,
            )
            
            if response.status_code in (200, 204):
                logger.info("Discord notification sent successfully")
                return True
            else:
                logger.warning(f"Discord webhook returned status {response.status_code}")
                return False
                
    except httpx.TimeoutException:
        logger.warning("Discord webhook request timed out")
        return False
    except httpx.RequestError as e:
        logger.error(f"Discord webhook request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")
        return False


def send_discord_message(content: str) -> bool:
    """
    Send a plain text message to Discord.
    
    Args:
        content: The message content
        
    Returns:
        True if sent successfully, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        logger.debug("Discord webhook URL not configured, skipping message")
        return False
    
    try:
        payload = {
            "content": content
        }
        
        with httpx.Client() as client:
            response = client.post(
                DISCORD_WEBHOOK_URL,
                json=payload,
                timeout=10.0,
            )
            
            if response.status_code in (200, 204):
                logger.info("Discord message sent successfully")
                return True
            else:
                logger.warning(f"Discord webhook returned status {response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"Failed to send Discord message: {e}")
        return False


def test_discord_connection() -> bool:
    """
    Test the Discord webhook connection.
    
    Returns:
        True if connection works, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL not configured")
        return False
    
    return send_discord_message("✅ OSINT Platform connected to Discord successfully!")
