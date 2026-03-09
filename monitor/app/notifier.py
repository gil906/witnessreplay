import httpx
import os
import logging

logger = logging.getLogger(__name__)

MCP_URL = os.environ.get("MCP_URL", "http://192.168.68.68:8086/mcp")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "gdleonq@gmail.com")


async def send_alert(subject: str, html_body: str) -> bool:
    """Send email alert via MCP mailreporter server."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            # Step 1: Initialize MCP session
            init_resp = await client.post(MCP_URL, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "wr-monitor", "version": "1.0"},
                }
            }, headers=headers)

            session_id = init_resp.headers.get("mcp-session-id")
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            # Step 2: Initialized notification
            await client.post(MCP_URL, json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }, headers=headers)

            # Step 3: Call send_email tool
            resp = await client.post(MCP_URL, json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "send_email",
                    "arguments": {
                        "to": ALERT_EMAIL,
                        "subject": subject,
                        "html_body": html_body,
                    }
                }
            }, headers=headers)

            logger.info(f"Email alert sent: {subject} (status={resp.status_code})")
            return True

    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")
        # Fallback: try without init handshake
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(MCP_URL, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "send_email",
                        "arguments": {
                            "to": ALERT_EMAIL,
                            "subject": subject,
                            "html_body": html_body,
                        }
                    }
                }, headers={"Content-Type": "application/json"})
                logger.info(f"Email alert sent (fallback): {resp.status_code}")
                return True
        except Exception as e2:
            logger.error(f"Email fallback also failed: {e2}")
            return False
