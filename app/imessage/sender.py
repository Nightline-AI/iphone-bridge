"""
iMessage Sender - Send messages via AppleScript.

Uses macOS's `osascript` command to interact with the Messages app
and send iMessages/SMS. The Mac must be signed into the same iCloud
account as the target iPhone.
"""

import asyncio
import logging
import shlex
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SendResult(Enum):
    """Result of a send attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    INVALID_RECIPIENT = "invalid_recipient"


@dataclass
class SendResponse:
    """Response from a send attempt."""

    result: SendResult
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.result == SendResult.SUCCESS


class iMessageSender:
    """
    Send iMessages/SMS via AppleScript.

    Usage:
        sender = iMessageSender()
        response = await sender.send("+15551234567", "Hello!")
        if response.success:
            print("Message sent!")
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize the sender.

        Args:
            timeout: Maximum seconds to wait for AppleScript to complete
        """
        self.timeout = timeout

    def _escape_for_applescript(self, text: str) -> str:
        """
        Escape a string for use in AppleScript.

        AppleScript strings use double quotes, so we need to escape:
        - Backslashes (\ -> \\)
        - Double quotes (" -> \")
        """
        return text.replace("\\", "\\\\").replace('"', '\\"')

    def _build_send_script(self, phone: str, text: str) -> str:
        """
        Build the AppleScript to send a message.

        This script:
        1. Opens Messages app (if not already open)
        2. Finds or creates a conversation with the recipient
        3. Sends the message
        """
        escaped_text = self._escape_for_applescript(text)
        escaped_phone = self._escape_for_applescript(phone)

        # This AppleScript works with modern macOS (Ventura+)
        script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{escaped_phone}" of targetService
    send "{escaped_text}" to targetBuddy
end tell
'''
        return script.strip()

    def _build_send_script_fallback(self, phone: str, text: str) -> str:
        """
        Alternative AppleScript that may work on older macOS versions.
        Uses the 'buddy' approach instead of 'participant'.
        """
        escaped_text = self._escape_for_applescript(text)
        escaped_phone = self._escape_for_applescript(phone)

        script = f'''
tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "{escaped_phone}" of targetService
    send "{escaped_text}" to targetBuddy
end tell
'''
        return script.strip()

    async def _run_applescript(self, script: str) -> tuple[int, str, str]:
        """
        Execute an AppleScript and return (returncode, stdout, stderr).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript",
                "-e",
                script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )

            return (
                proc.returncode or 0,
                stdout.decode("utf-8").strip(),
                stderr.decode("utf-8").strip(),
            )

        except asyncio.TimeoutError:
            logger.error(f"AppleScript timed out after {self.timeout}s")
            return (1, "", "Timeout")

    async def send(self, phone: str, text: str) -> SendResponse:
        """
        Send an iMessage/SMS to a phone number.

        Args:
            phone: Phone number in E.164 format (e.g., "+15551234567")
            text: Message content to send

        Returns:
            SendResponse with success status and any error message
        """
        if not phone:
            return SendResponse(
                result=SendResult.INVALID_RECIPIENT,
                error="Phone number is required",
            )

        if not text:
            return SendResponse(
                result=SendResult.FAILED,
                error="Message text is required",
            )

        logger.info(f"Sending message to {phone}: {text[:50]}...")

        # Try the primary script first
        script = self._build_send_script(phone, text)
        returncode, stdout, stderr = await self._run_applescript(script)

        if returncode == 0:
            logger.info(f"Successfully sent message to {phone}")
            return SendResponse(result=SendResult.SUCCESS)

        # Log the error and try fallback
        logger.warning(f"Primary send failed: {stderr}, trying fallback...")

        script = self._build_send_script_fallback(phone, text)
        returncode, stdout, stderr = await self._run_applescript(script)

        if returncode == 0:
            logger.info(f"Successfully sent message to {phone} (fallback)")
            return SendResponse(result=SendResult.SUCCESS)

        # Both methods failed
        error_msg = stderr or "Unknown AppleScript error"
        logger.error(f"Failed to send message to {phone}: {error_msg}")

        # Check for common error patterns
        if "buddy" in error_msg.lower() or "participant" in error_msg.lower():
            return SendResponse(
                result=SendResult.INVALID_RECIPIENT,
                error=f"Could not find recipient {phone}. Ensure they have iMessage enabled.",
            )

        return SendResponse(result=SendResult.FAILED, error=error_msg)

    async def send_bulk(
        self, messages: list[tuple[str, str]], delay: float = 1.0
    ) -> list[SendResponse]:
        """
        Send multiple messages with a delay between each.

        Args:
            messages: List of (phone, text) tuples
            delay: Seconds to wait between messages (to avoid rate limiting)

        Returns:
            List of SendResponse objects in the same order as input
        """
        responses = []

        for i, (phone, text) in enumerate(messages):
            if i > 0:
                await asyncio.sleep(delay)

            response = await self.send(phone, text)
            responses.append(response)

        return responses


# Convenience function for one-off sends
async def send_imessage(phone: str, text: str) -> bool:
    """
    Convenience function to send a single iMessage.

    Returns True if successful, False otherwise.
    """
    sender = iMessageSender()
    response = await sender.send(phone, text)
    return response.success
