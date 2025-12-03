"""
Modular FILO Queue Manager for MCP Monitors

This module provides a reusable queue abstraction that any monitor can plug into.
It handles the triple-task pattern (poller + processor + heartbeat) and uses SQLite for persistence.

Architecture:
- Poller Task: Continuously receives messages via MCP, stores in SQLite
- Processor Task: Pulls the newest messages first (FILO) while sharing the full backlog context
- Heartbeat Task: Keeps MCP connection alive with periodic pings (every 4 minutes)
- All tasks run concurrently via asyncio.gather()

Benefits:
- Zero message loss (SQLite buffer)
- FILO focus (ORDER BY timestamp DESC) so the agent can respond to the latest state while seeing the queue snapshot
- Crash resilient (persistent storage)
- Connection resilient (heartbeat prevents 5-minute timeout)
- Modular (any monitor can use it)
- Pluggable handlers (monitors implement simple async function)
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from mcp import ClientSession

from ax_agent_studio.mcp_heartbeat import keep_alive
from ax_agent_studio.message_store import MessageStore

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Modular FILO queue manager for MCP monitors.

    Usage:
        async def my_handler(content: str) -> str:
            # Your processing logic here
            return "Response"

        queue_mgr = QueueManager(agent_name, session, my_handler)
        await queue_mgr.run()  # Runs forever
    """

    def __init__(
        self,
        agent_name: str,
        session: ClientSession,
        message_handler: Callable[[str], Awaitable[str]],
        store: MessageStore | None = None,
        mark_read: bool = False,
        poll_interval: float = 1.0,
        startup_sweep: bool = True,
        startup_sweep_limit: int = 10,
        heartbeat_interval: int = 240,  # 4 minutes default
    ):
        """
        Initialize QueueManager.

        Args:
            agent_name: Name of the agent (e.g., "lunar_craft_128")
            session: MCP ClientSession for tool calls
            message_handler: Async function that processes message content and returns response
            store: Optional MessageStore instance (creates default if None)
            mark_read: Whether to mark messages as read (default: False for queued processing)
            poll_interval: Seconds to wait between queue checks if empty (default: 1.0)
            startup_sweep: Whether to fetch unread messages on startup (default: True)
            startup_sweep_limit: Max unread messages to fetch on startup, 0=unlimited (default: 10)
            heartbeat_interval: Seconds between heartbeat pings (default: 240 = 4 minutes, 0=disabled)
        """
        self.agent_name = agent_name
        self.session = session
        self.handler = message_handler
        self.store = store or MessageStore()
        self.mark_read = mark_read
        self.poll_interval = poll_interval
        self.startup_sweep = startup_sweep
        self.startup_sweep_limit = startup_sweep_limit
        self.heartbeat_interval = heartbeat_interval
        self._running = False

        # Error handling and retry state
        self._poll_backoff = 5  # Current backoff time in seconds
        self._poll_backoff_max = 60  # Max backoff time
        self._poll_consecutive_errors = 0  # Track consecutive errors for backoff

        logger.info(f" QueueManager initialized for @{agent_name}")
        logger.info(f"   Storage: {self.store.db_path}")
        logger.info(f"   Mark read: {self.mark_read}")
        logger.info(f"   Startup sweep: {self.startup_sweep} (limit: {self.startup_sweep_limit})")
        logger.info(
            f"   Heartbeat: {'enabled' if self.heartbeat_interval > 0 else 'disabled'} (interval: {self.heartbeat_interval}s)"
        )

    def _parse_message(self, result) -> tuple[str, str, str] | None:
        """
        Parse MCP messages tool result to extract message ID, sender, and content.

        The MCP remote server returns messages in different formats:
        - result.messages: Structured array of message objects (current aX Platform format)
        - result.content: Status messages like " WAIT SUCCESS: Found 1 mentions"
        - result.events: Actual message data (for some MCP implementations)
        - result.content with formatted text: Message data in text format (for others)

        Returns:
            Tuple of (message_id, sender, content) or None if no valid message
        """
        try:
            # Try result.messages first (current aX Platform format)
            if hasattr(result, "messages") and result.messages:
                # Find first message that mentions this agent
                for msg in result.messages:
                    # Check if this message DIRECTLY mentions our agent (not just references in task descriptions)
                    # Match @agent_name only when it appears as a direct mention (at start or after whitespace)
                    content = msg.get("content", "")
                    mention_pattern = rf"(?:^|[\s\n])@{re.escape(self.agent_name)}(?:[\s\n]|$)"
                    if re.search(mention_pattern, content):
                        msg_id = msg.get("id", "unknown")
                        sender = msg.get("sender_name", "unknown")
                        content = msg.get("content", "")

                        # Skip self-mentions
                        if sender == self.agent_name:
                            logger.warning(f"⏭  SKIPPING SELF-MENTION: {sender} (agent={self.agent_name})")
                            continue

                        logger.info(f"✅ Found message: {msg_id[:8]} from {sender}")
                        return (msg_id, sender, content)

                # No valid messages found for this agent
                logger.debug(f"No messages mentioning @{self.agent_name} in response")
                return None

            # Try result.events (old format from some MCP servers)
            if hasattr(result, "events") and result.events:
                event = result.events[0]
                msg_id = event.get("id", "unknown")
                sender = event.get("sender_name", "unknown")
                content = event.get("content", "")

                logger.info(f" Found message via events: {msg_id[:8]} from {sender}")
                return (msg_id, sender, content)

            # Try result.content (current format)
            content = result.content
            if not content:
                logger.debug(" Empty content in result")
                return None

            # Extract message text
            if hasattr(content, "text"):
                messages_data = content.text
            else:
                messages_data = str(content[0].text) if content else ""

            if not messages_data:
                logger.debug(" Empty messages_data")
                return None

            # Skip status messages like "WAIT SUCCESS"
            if "WAIT SUCCESS" in messages_data or "No mentions" in messages_data:
                logger.debug(f" Skipping status message: {messages_data}")
                return None

            # Extract message ID from [id:xxxxxxxx] tags
            message_id_match = re.search(r"\[id:([a-f0-9-]+)\]", messages_data)
            if not message_id_match:
                logger.warning("  No message ID found in response")
                return None

            message_id = message_id_match.group(1)

            # Verify there's an actual mention (not just "no mentions found")
            mention_match = re.search(r"• ([^:]+): (@\S+)\s+(.+)", messages_data)
            if not mention_match:
                logger.debug("⏭  No actual mentions in response")
                return None

            # Verify THIS agent is mentioned
            if f"@{self.agent_name}" not in messages_data:
                logger.debug(f"⏭  Message doesn't mention @{self.agent_name}")
                return None

            # Extract sender and content
            sender = mention_match.group(1)

            # Skip self-mentions (agent mentioning themselves)
            if sender == self.agent_name:
                logger.warning(
                    f"⏭  SKIPPING SELF-MENTION: {sender} mentioned themselves (agent={self.agent_name})"
                )
                return None

            # Full content includes the mention pattern
            content = messages_data

            logger.info(f" VALID MESSAGE: from {sender} to {self.agent_name}")
            return (message_id, sender, content)

        except Exception as e:
            logger.error(f" Error parsing message: {e}")
            return None

    def _parse_error_and_get_wait_time(self, error: Exception) -> tuple[str, int]:
        """
        Parse error and determine appropriate wait time before retry.

        Returns:
            Tuple of (error_type, wait_seconds)
            error_type: "rate_limit", "connection_timeout", "connection_error", "unknown"
            wait_seconds: How long to wait before retrying
        """
        import json

        error_str = str(error)

        # Check for rate limit (HTTP 429)
        if "HTTP 429" in error_str or "rate_limited" in error_str.lower():
            # Try to extract retry_after from error message
            try:
                # Error format: {"error":"rate_limited","retry_after":27,...}
                if "{" in error_str:
                    json_start = error_str.find("{")
                    json_end = error_str.rfind("}") + 1
                    error_json = json.loads(error_str[json_start:json_end])
                    retry_after = error_json.get("retry_after", 30)
                    logger.warning(
                        f"⏱️  RATE LIMIT: Server requests {retry_after}s wait (next allowed: {error_json.get('next_allowed_at', 'unknown')})"
                    )
                    return ("rate_limit", retry_after)
            except Exception:
                pass
            # Fallback if parsing fails
            logger.warning("⏱️  RATE LIMIT: Using default 30s wait")
            return ("rate_limit", 30)

        # Check for connection timeouts
        if (
            "ConnectTimeoutError" in error_str
            or "Connection timeout" in error_str
            or "TimeoutError" in error_str
        ):
            # Use exponential backoff for connection timeouts
            wait_time = min(self._poll_backoff, self._poll_backoff_max)
            logger.warning(f"🔌 CONNECTION TIMEOUT: Will retry in {wait_time}s (backoff: {self._poll_backoff}s)")
            return ("connection_timeout", wait_time)

        # Check for connection errors (ECONNRESET, etc.)
        if (
            "ECONNRESET" in error_str
            or "ConnectionResetError" in error_str
            or "ConnectionRefusedError" in error_str
            or "OSError" in error_str
        ):
            # Use exponential backoff
            wait_time = min(self._poll_backoff, self._poll_backoff_max)
            logger.warning(f"🔌 CONNECTION ERROR: {error.__class__.__name__} - Will retry in {wait_time}s")
            return ("connection_error", wait_time)

        # Unknown error - use current backoff
        wait_time = min(self._poll_backoff, self._poll_backoff_max)
        logger.error(f"❌ UNKNOWN ERROR: {error.__class__.__name__}: {str(error)[:200]}")
        return ("unknown", wait_time)

    async def _startup_sweep(self):
        """
        Startup sweep: Fetch unread messages before starting poller.

        This gives monitors context when they join late by catching up on
        the last N unread messages. Uses mode='unread' + wait=False to
        fetch backlog without blocking.

        Following ax_sentinel's recommendation:
        1. Fetch unread messages in loop until empty or limit reached
        2. Store each in the queue
        3. Mark them as read via up_to_id to prevent reprocessing
        """
        if not self.startup_sweep:
            logger.info("⏭  Startup sweep disabled, starting poller...")
            return

        logger.info(
            f" Starting unread message sweep (limit: {self.startup_sweep_limit or 'unlimited'})"
        )

        fetched = 0
        last_id = None

        try:
            max_iterations = 200  # Safety limit to prevent infinite loops
            iteration = 0

            while iteration < max_iterations:
                # Stop if we've reached the limit
                if self.startup_sweep_limit > 0 and fetched >= self.startup_sweep_limit:
                    logger.info(f" Sweep limit reached ({fetched} messages)")
                    break

                # Fetch unread messages (non-blocking)
                # Mark as read immediately to prevent re-fetching the same message
                result = await self.session.call_tool(
                    "messages",
                    {
                        "action": "check",
                        "filter_agent": self.agent_name,
                        "mode": "unread",
                        "wait": False,
                        "limit": 1,  # Fetch one at a time to avoid duplicates
                        "mark_read": True,  # Mark read immediately
                    },
                )

                # Parse message
                parsed = self._parse_message(result)
                if not parsed:
                    # No more unread messages
                    logger.info(f" Sweep complete ({fetched} messages fetched)")
                    break

                msg_id, sender, content = parsed

                # Store in queue
                success = self.store.store_message(
                    msg_id=msg_id, agent=self.agent_name, sender=sender, content=content
                )

                if success:
                    fetched += 1
                    last_id = msg_id
                    logger.info(f" Sweep [{fetched}]: {msg_id[:8]} from {sender}")

                iteration += 1

                # CRITICAL: Rate limit protection - wait between requests
                # MCP server rate limit: ~100 req/min, so 0.7s = ~85 req/min (safe)
                await asyncio.sleep(0.7)

            if iteration >= max_iterations:
                logger.warning(f"  Hit max iterations ({max_iterations}) during sweep")

        except Exception as e:
            logger.error(f" Startup sweep error: {e}")
            logger.info("   Continuing with normal polling...")

    async def poll_and_store(self):
        """
        Poller Task: Continuously receive messages and store in queue.

        This task runs forever, blocking on wait=true until messages arrive.
        When a message arrives, it's immediately stored in SQLite, then we
        go back to waiting. This ensures no messages are lost while the
        processor is busy.
        """
        logger.info(" Poller task started")
        iteration = 0

        while self._running:
            try:
                iteration += 1
                logger.debug(f"[Poller] Waiting for messages... (iteration {iteration})")

                # Check if agent is paused BEFORE fetching messages
                # This avoids wasting API rate limits and keeps agent truly idle during pause
                if self.store.is_agent_paused(self.agent_name):
                    # Check if auto-resume timer expired (set via action=stop)
                    self.store.check_auto_resume(self.agent_name)
                    # Sleep briefly and check again
                    await asyncio.sleep(1)
                    continue

                # Short-poll for messages (wait=false to avoid socket errors)
                result = await self.session.call_tool(
                    "messages", {
                        "action": "check",
                        "filter_agent": self.agent_name,
                        "wait": False,
                        "mark_read": self.mark_read
                    }
                )

                # Parse and validate message
                parsed = self._parse_message(result)
                if not parsed:
                    # No message found - successful poll, reset backoff if needed
                    if self._poll_consecutive_errors > 0:
                        logger.info(
                            f"✅ Polling recovered after {self._poll_consecutive_errors} consecutive errors"
                        )
                        self._poll_consecutive_errors = 0
                        self._poll_backoff = 5  # Reset to initial value

                    # Sleep before next poll to avoid rate limits
                    logger.info(f"⏱️  [{datetime.now().strftime('%H:%M:%S')}] Polled - no new messages")
                    await asyncio.sleep(5)  # Poll every 5 seconds when idle
                    continue

                msg_id, sender, content = parsed

                # Store in SQLite queue
                success = self.store.store_message(
                    msg_id=msg_id, agent=self.agent_name, sender=sender, content=content
                )

                if success:
                    backlog = self.store.get_backlog_count(self.agent_name)
                    logger.info(f" Stored message {msg_id[:8]} from {sender} (backlog: {backlog})")

                    # Reset error backoff on successful message processing
                    if self._poll_consecutive_errors > 0:
                        logger.info(
                            f"✅ Polling recovered after {self._poll_consecutive_errors} consecutive errors"
                        )
                        self._poll_consecutive_errors = 0
                        self._poll_backoff = 5  # Reset to initial value
                else:
                    logger.warning(f"  Failed to store message {msg_id[:8]} (likely duplicate)")

            except asyncio.CancelledError:
                logger.info(" Poller task cancelled")
                break
            except Exception as e:
                # Parse error and determine appropriate wait time
                error_type, wait_seconds = self._parse_error_and_get_wait_time(e)

                # Track consecutive errors for backoff calculation
                self._poll_consecutive_errors += 1

                # For rate limits, use the exact wait time from server
                if error_type == "rate_limit":
                    logger.warning(f"💤 Waiting {wait_seconds}s before retrying (rate limit)...")
                    await asyncio.sleep(wait_seconds)
                    # Don't increase backoff for rate limits
                    continue

                # For connection errors, use exponential backoff
                if error_type in ("connection_timeout", "connection_error"):
                    logger.warning(
                        f"💤 Waiting {wait_seconds}s before retrying (attempt {self._poll_consecutive_errors})..."
                    )
                    await asyncio.sleep(wait_seconds)

                    # Increase backoff exponentially: 5s → 10s → 20s → 40s → 60s (max)
                    self._poll_backoff = min(self._poll_backoff * 2, self._poll_backoff_max)
                    logger.debug(f"📈 Next backoff will be {self._poll_backoff}s")
                    continue

                # For unknown errors, use backoff but log more details
                logger.error(
                    f"❌ Poller error (attempt {self._poll_consecutive_errors}): {e.__class__.__name__}"
                )
                logger.warning(f"💤 Waiting {wait_seconds}s before retrying...")
                await asyncio.sleep(wait_seconds)
                self._poll_backoff = min(self._poll_backoff * 2, self._poll_backoff_max)
                continue

    async def process_queue(self):
        """
        Processor Task: Pull newest messages from queue (FILO) while providing backlog context.

        This task runs forever, checking the queue for pending messages.
        When a message is found, it's processed with the handler, response
        is sent, and message is marked complete. If queue is empty, we
        sleep briefly before checking again.
        """
        logger.info("  Processor task started")

        from pathlib import Path

        kill_switch_file = Path("data/KILL_SWITCH")

        while self._running:
            try:
                #  KILL SWITCH: Check if processing should be paused
                if kill_switch_file.exists():
                    logger.warning(" KILL SWITCH ACTIVE - Processing paused")
                    await asyncio.sleep(5)  # Check every 5 seconds
                    continue

                # Check if agent is paused
                if self.store.is_agent_paused(self.agent_name):
                    # Check for auto-resume
                    if self.store.check_auto_resume(self.agent_name):
                        logger.info(f"  Agent {self.agent_name} auto-resumed")
                    else:
                        agent_status = self.store.get_agent_status(self.agent_name)
                        reason = agent_status.get("paused_reason", "Unknown")
                        logger.debug(f"⏸  Agent paused: {reason}")
                        await asyncio.sleep(5)  # Check every 5 seconds
                        continue

                # Check backlog to determine processing order
                backlog = self.store.get_backlog_count(self.agent_name)

                # Hybrid FILO/FIFO: If backlog exceeds batch limit, drain oldest first
                # to prevent starvation. Otherwise, process newest first (FILO).
                if backlog > 100:
                    # High load: Switch to FIFO to drain backlog
                    processing_order = "asc"
                    logger.info(f"High backlog ({backlog} messages) - switching to FIFO to drain")
                else:
                    # Normal load: FILO processing (newest first)
                    processing_order = "desc"

                # Get pending messages with appropriate ordering
                all_pending = self.store.get_pending_messages(
                    self.agent_name, limit=100, order=processing_order
                )

                if not all_pending:
                    # Queue empty - brief pause
                    await asyncio.sleep(self.poll_interval)
                    continue

                batch_size = len(all_pending)

                # Precompute queue snapshot for handler + board context
                # Keep in processing order (first = currently processing)
                # so formatter can correctly mark [PROCESSING NOW]
                queue_snapshot = [
                    {
                        "id": msg.id,
                        "sender": msg.sender,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                    }
                    for msg in all_pending
                ]

                # Determine processing mode
                if batch_size > 1:
                    logger.info(
                        f"📦 BATCH MODE: Processing {batch_size} messages together (backlog: {backlog})"
                    )
                else:
                    logger.info(
                        f"  SINGLE MODE: Processing message {all_pending[0].id[:8]} from {all_pending[0].sender} (backlog: {backlog})"
                    )

                # Mark all as processing (prevents duplicate processing)
                for msg in all_pending:
                    self.store.mark_processing_started(msg.id, self.agent_name)

                try:
                    # Prepare message context
                    if batch_size > 1:
                        # BATCH MODE: Current message + history
                        # In FILO mode (desc): current = newest, history = older
                        # In FIFO mode (asc): current = oldest, history = newer
                        current_msg = all_pending[0]  # First message in fetch order
                        history_msgs = all_pending[1:]  # Remaining messages

                        # Always provide history in chronological order (oldest → newest)
                        if processing_order == "desc":
                            # FILO: Reverse to get chronological order
                            history_msgs = list(reversed(history_msgs))
                        # FIFO: Already in chronological order, no reversal needed

                        history_dicts = [
                            {
                                "id": m.id,
                                "sender": m.sender,
                                "content": m.content,
                                "timestamp": m.timestamp,
                            }
                            for m in history_msgs
                        ]

                        response = await self.handler(
                            {
                                "content": current_msg.content,
                                "sender": current_msg.sender,
                                "id": current_msg.id,
                                "timestamp": current_msg.timestamp,
                                # Batch processing context
                                "batch_mode": True,
                                "batch_size": batch_size,
                                "history_messages": history_dicts,  # Older messages for context
                                "queue_status": {
                                    "backlog_count": backlog,
                                    "pending_messages": queue_snapshot,
                                },
                                "queue_messages": queue_snapshot,
                            }
                        )
                    else:
                        # SINGLE MODE: Just one message
                        msg = all_pending[0]
                        response = await self.handler(
                            {
                                "content": msg.content,
                                "sender": msg.sender,
                                "id": msg.id,
                                "timestamp": msg.timestamp,
                                "batch_mode": False,
                                "queue_status": {
                                    "backlog_count": backlog,
                                    "pending_messages": queue_snapshot,
                                },
                                "queue_messages": queue_snapshot,
                            }
                        )

                    # Ensure response is a string
                    if not isinstance(response, str):
                        response = str(response)

                    # NOTE: Pause/stop functionality now handled server-side via action=stop
                    # No client-side text parsing needed

                    # Only send if response is not empty (handler may return "" to skip)
                    if response and response.strip():
                        send_content = response

                        # Determine which message to reply to (newest in queue / current focus)
                        reply_to_msg = all_pending[0]

                        # Send response as a REPLY to the newest message (creates thread)
                        await self.session.call_tool(
                            "messages",
                            {
                                "action": "send",
                                "content": send_content,
                                "parent_message_id": reply_to_msg.id,  # Reply to the newest message
                            },
                        )
                        if batch_size > 1:
                            logger.info(
                                f" Completed BATCH of {batch_size} messages (threaded reply)"
                            )
                        else:
                            logger.info(
                                f" Completed message {reply_to_msg.id[:8]} (threaded reply)"
                            )
                    else:
                        # Handler returned empty response (e.g., blocked self-mention)
                        if batch_size > 1:
                            logger.info(
                                f" Completed BATCH of {batch_size} messages: (no response - handler blocked)"
                            )
                        else:
                            logger.info(
                                f" Completed message {all_pending[0].id[:8]}: (no response - handler blocked)"
                            )

                    # Mark ALL messages as processed (removes from queue)
                    for msg in all_pending:
                        self.store.mark_processed(msg.id, self.agent_name)

                except Exception as e:
                    if batch_size > 1:
                        logger.error(f" Handler error for BATCH of {batch_size} messages: {e}")
                    else:
                        logger.error(f" Handler error for message {all_pending[0].id[:8]}: {e}")
                    logger.error(f"   Error details: {type(e).__name__}: {e!s}")
                    # Mark ALL as processed to prevent infinite retry loop
                    # TODO: Add retry limits and dead-letter queue for transient failures
                    for msg in all_pending:
                        self.store.mark_processed(msg.id, self.agent_name)
                    if batch_size > 1:
                        logger.warning(
                            f"  BATCH of {batch_size} messages marked as failed (won't retry)"
                        )
                    else:
                        logger.warning(
                            f"  Message {all_pending[0].id[:8]} marked as failed (won't retry)"
                        )

            except asyncio.CancelledError:
                logger.info("  Processor task cancelled")
                break
            except Exception as e:
                logger.error(f" Processor error: {e}")
                await asyncio.sleep(5)  # Brief pause on error

    async def heartbeat(self):
        """
        Heartbeat Task: Keep MCP connection alive with periodic pings.

        Uses the reusable keep_alive() utility from mcp_heartbeat module.
        This ensures DRY - all MCP connections use the same heartbeat logic.
        """
        # Use the centralized heartbeat utility
        await keep_alive(self.session, interval=self.heartbeat_interval, name=self.agent_name)

    async def run(self):
        """
        Run all tasks concurrently (poller + processor + heartbeat).

        This is the main entry point for monitors. It starts all tasks
        and runs until interrupted (Ctrl+C).
        """
        self._running = True

        try:
            # Show initial stats
            stats = self.store.get_stats(self.agent_name)
            logger.info(f" Queue stats: {stats['pending']} pending, {stats['completed']} completed")

            # Do startup sweep to catch up on missed messages
            await self._startup_sweep()

            # Run all tasks concurrently (poller + processor + heartbeat)
            tasks = [
                self.poll_and_store(),
                self.process_queue(),
            ]

            # Add heartbeat if enabled
            if self.heartbeat_interval > 0:
                tasks.append(self.heartbeat())

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info(" QueueManager stopped by user")
        except Exception as e:
            logger.error(f" QueueManager error: {e}")
        finally:
            self._running = False

            # Show final stats
            stats = self.store.get_stats(self.agent_name)
            logger.info(f" Final stats: {stats['pending']} pending, {stats['completed']} completed")
            logger.info(f"   Avg processing time: {stats['avg_processing_time']:.2f}s")
            # Note: Heartbeat stats are logged by keep_alive() utility

    async def cleanup_old_messages(self, days: int = 7) -> int:
        """
        Clean up old processed messages.

        Args:
            days: Delete messages older than this many days (default: 7)

        Returns:
            Number of messages deleted
        """
        count = self.store.cleanup_old_messages(days)
        logger.info(f"  Cleaned up {count} messages older than {days} days")
        return count
