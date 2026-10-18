from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import User
from ..security import decode_token
from ..ws_manager import manager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str):
    """Connect with ws://HOST/ws?token=<JWT>. Admins get all alerts; users get their own notices."""
    try:
        payload = decode_token(token)
        with SessionLocal() as db:
            user = db.get(User, int(payload["sub"]))
            ok = bool(user and user.is_active)
            uid, role = (user.id, user.role) if user else (0, "")
    except Exception:
        ok = False
    if not ok:
        await ws.close(code=4401)
        return
    await manager.connect(ws, uid, role)
    try:
        while True:
            await ws.receive_text()  # keep-alive; client may send "ping"
    except WebSocketDisconnect:
        manager.disconnect(ws)
