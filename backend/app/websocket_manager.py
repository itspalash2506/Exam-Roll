import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._stage_history: dict[str, list[dict]] = {}

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(job_id, []).append(websocket)
        logger.debug("WS connected  job=%s  total=%d", job_id, len(self._connections[job_id]))

        # Background processing starts the instant the upload response comes
        # back, which can race a slower-to-open WebSocket — replay whatever
        # stage events already fired so a late-connecting client still sees
        # every real stage instead of silently missing the fast early ones.
        for payload in self._stage_history.get(job_id, []):
            try:
                await websocket.send_text(json.dumps(payload))
            except Exception:
                break

    def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        sockets = self._connections.get(job_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._connections.pop(job_id, None)
            self._stage_history.pop(job_id, None)
        logger.debug("WS disconnected  job=%s", job_id)

    async def send_progress(
        self,
        job_id: str,
        progress: int,
        message: str,
        status: str,
    ) -> None:
        payload = {
            "progress": progress,
            "message": message,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.broadcast_to_job(job_id, payload)

    async def send_stage(self, job_id: str, payload: dict) -> None:
        """Broadcast a granular stage event (type 'stage' or 'error').

        Distinct from send_progress: callers pass the full event dict (stage_id,
        label, status, detail, count, percent, ...); this just stamps a
        timestamp and broadcasts it as-is, without reinterpreting the shape.
        """
        enriched = {**payload, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._stage_history.setdefault(job_id, []).append(enriched)
        await self.broadcast_to_job(job_id, enriched)

    async def broadcast_to_job(self, job_id: str, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(job_id, [])):
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, job_id)


manager = ConnectionManager()
