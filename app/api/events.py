"""Real-time Server-Sent Events (SSE) streaming endpoint for the dashboard."""
import asyncio
import json
from typing import Set
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.services.telegram_bot import log_buffer

router = APIRouter(prefix="/events", tags=["Events"])

# Active SSE client queues
_event_subscribers: Set[asyncio.Queue] = set()


def broadcast_event(event_type: str, data: dict):
    """Broadcast an event payload to all connected SSE clients.

    Short-circuits immediately when no clients are connected — skips
    json.dumps() serialization entirely. This is the hot path: during normal
    operation there are zero SSE viewers, so this guard eliminates thousands
    of unnecessary serialization calls per minute.
    """
    if not _event_subscribers:
        return
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    to_remove = set()
    for queue in _event_subscribers:
        try:
            queue.put_nowait(payload)
        except Exception:
            to_remove.add(queue)
    for q in to_remove:
        _event_subscribers.discard(q)


@router.get("/stream")
async def stream_events(request: Request):
    """Stream live bot logs and system events via Server-Sent Events (SSE)."""
    queue = asyncio.Queue(maxsize=100)
    _event_subscribers.add(queue)

    # Immediately send existing recent logs on connection open
    recent_logs = log_buffer.get_logs()
    initial_payload = f"event: initial_logs\ndata: {json.dumps({'logs': recent_logs})}\n\n"
    queue.put_nowait(initial_payload)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Wait for next event with 15s keepalive ping
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield payload
                except asyncio.TimeoutError:
                    # SSE Keepalive ping
                    yield ": ping\n\n"
        finally:
            _event_subscribers.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
