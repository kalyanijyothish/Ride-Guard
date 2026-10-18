"""WebSocket hub. Admins receive every alert; users receive messages addressed to them."""
import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: list[tuple[WebSocket, int, str]] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, user_id: int, role: str):
        await ws.accept()
        self.active.append((ws, user_id, role))

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c[0] is not ws]

    async def _send(self, admin_payload, user_payload, user_ids, to_all):
        for ws, uid, role in list(self.active):
            payload = None
            if role == "admin":
                payload = admin_payload
            elif to_all or uid in user_ids:
                payload = user_payload or admin_payload
            if payload is None:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(ws)

    def push(self, admin_payload: dict, user_payload: dict | None = None,
             user_ids=(), to_all: bool = False):
        """Thread-safe: callable from sync endpoints and the background worker."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._send(admin_payload, user_payload, set(user_ids), to_all), self.loop)


manager = ConnectionManager()
