"""Shared request helpers and event broadcasting for SSE."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..domain.enums import Role
from ..models import Trip, User
from ..security import visible_traveller_ids


def trip_query():
    return select(Trip).options(
        selectinload(Trip.segments),
        selectinload(Trip.hotels),
        selectinload(Trip.ground),
        selectinload(Trip.disruptions),
        selectinload(Trip.traveller),
    )


def load_trip(db: Session, trip_id: str) -> Trip | None:
    return db.scalars(trip_query().where(Trip.id == trip_id)).first()


def load_trips_for(db: Session, actor: User) -> list[Trip]:
    ids = visible_traveller_ids(db, actor)
    return list(db.scalars(trip_query().where(Trip.traveller_id.in_(ids)).order_by(Trip.starts_at_utc)).all())


def actor_can_access_trip(db: Session, actor: User, trip: Trip) -> bool:
    if actor.role == Role.ADMIN.value:
        return True
    if trip.traveller_id == actor.id:
        return True
    if actor.role == Role.TRAVEL_MANAGER.value:
        return trip.traveller_id in visible_traveller_ids(db, actor)
    return False


class EventBus:
    """In-process pub/sub for Server-Sent Events.

    One queue per trip. Bounded, so a disconnected client cannot grow memory
    without limit; the oldest event is dropped instead.
    """

    def __init__(self, max_queue: int = 64) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._max_queue = max_queue

    def subscribe(self, trip_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers[trip_id].add(queue)
        return queue

    def unsubscribe(self, trip_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[trip_id].discard(queue)
        if not self._subscribers[trip_id]:
            self._subscribers.pop(trip_id, None)

    def publish(self, trip_id: str, event: str, payload: dict) -> None:
        message = {
            "event": event,
            "sent_at_utc": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        for queue in list(self._subscribers.get(trip_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    continue

    async def stream(self, trip_id: str) -> AsyncIterator[str]:
        queue = self.subscribe(trip_id)
        try:
            yield _sse("connected", {"trip_id": trip_id})
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(message["event"], message["data"])
        finally:
            self.unsubscribe(trip_id, queue)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


bus = EventBus()
