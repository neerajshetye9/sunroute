"""Outbound telemetry pusher for SunRoute Edge Agent.

Pulls pending records from local SQLite outbox and pushes them over HTTPS
with Bearer token authentication to the cloud ingestion endpoint.
Operates strictly outbound: no inbound ports opened on Jetson (Section 5.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

from edge.outbox import SQLiteOutbox

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("edge.telemetry_pusher")


class TelemetryPusher:
    """Outbound-only daemon delivering messages from SQLite outbox to cloud gateway."""

    def __init__(
        self,
        outbox_db_path: str = "edge_outbox.db",
        target_url: str | None = None,
        bearer_token: str | None = None,
        batch_size: int = 10,
        flush_interval_s: float = 5.0,
    ) -> None:
        self.outbox = SQLiteOutbox(outbox_db_path)
        self.target_url = target_url or os.environ.get(
            "TELEMETRY_INGESTION_URL", "http://localhost:8000/api/v1/telemetry"
        )
        self.bearer_token = bearer_token or os.environ.get(
            "TELEMETRY_BEARER_TOKEN", "sunroute-telemetry-secret-token"
        )
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._running = False

    async def flush_batch(self, client: httpx.AsyncClient | None = None) -> int:
        """Fetch a batch of pending messages from outbox and push to remote endpoint.

        Returns the number of successfully delivered messages.
        """
        pending = self.outbox.fetch_batch(batch_size=self.batch_size)
        if not pending:
            return 0

        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
        }

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            should_close = True

        delivered_count = 0
        try:
            for msg in pending:
                try:
                    payload_str = (
                        json.dumps(msg.payload)
                        if isinstance(msg.payload, dict)
                        else str(msg.payload)
                    )
                    resp = await client.post(
                        self.target_url,
                        content=payload_str,
                        headers=headers,
                    )
                    if resp.status_code in (200, 201, 202):
                        self.outbox.mark_delivered([msg.message_id])
                        delivered_count += 1
                        logger.debug("Delivered message %s", msg.message_id)
                    else:
                        logger.warning(
                            "Delivery failed for %s: HTTP %s",
                            msg.message_id,
                            resp.status_code,
                        )
                        self.outbox.mark_failed(msg.message_id, f"HTTP {resp.status_code}")
                except (httpx.RequestError, Exception) as exc:
                    logger.warning("Network connection error for %s: %s", msg.message_id, exc)
                    self.outbox.mark_failed(msg.message_id, str(exc))
        finally:
            if should_close:
                await client.aclose()

        return delivered_count

    async def run_loop(self) -> None:
        """Run continuous flush loop until cancelled."""
        self._running = True
        logger.info("Starting telemetry pusher -> %s", self.target_url)
        async with httpx.AsyncClient(timeout=10.0) as client:
            while self._running:
                try:
                    count = await self.flush_batch(client)
                    if count > 0:
                        logger.info("Flushed %d outbox messages", count)
                except Exception as e:
                    logger.error("Unexpected error in flush loop: %s", e)
                await asyncio.sleep(self.flush_interval_s)

    def stop(self) -> None:
        self._running = False


async def main() -> None:
    pusher = TelemetryPusher()
    await pusher.run_loop()


if __name__ == "__main__":
    asyncio.run(main())
