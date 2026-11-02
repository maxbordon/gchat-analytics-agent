"""Maps each Chat space to an agent conversation, expiring idle ones.

The store is an interface so the in-memory version (fine for a single
instance) can be swapped for Firestore/Redis when the service scales out.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversationHandle:
    conversation_id: str
    is_new: bool  # True -> must be created remotely before the first :chat call


class ConversationStore(Protocol):
    def get_or_create(self, space: str) -> ConversationHandle: ...
    def forget(self, space: str) -> None: ...


class InMemoryConversationStore:
    def __init__(
        self,
        ttl_seconds: int,
        prefix: str = "conv",
        clock: Callable[[], float] = time.time,
    ):
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix
        self._clock = clock
        self._entries: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get_or_create(self, space: str) -> ConversationHandle:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(space)
            if entry is not None:
                conv_id, last_used = entry
                if now - last_used <= self.ttl_seconds:
                    self._entries[space] = (conv_id, now)
                    return ConversationHandle(conv_id, is_new=False)
                logger.info("Conversation for %s expired after %.0fs idle", space, now - last_used)

            conv_id = f"{self.prefix}{uuid.uuid4().hex}"
            self._entries[space] = (conv_id, now)
            return ConversationHandle(conv_id, is_new=True)

    def forget(self, space: str) -> None:
        with self._lock:
            self._entries.pop(space, None)
