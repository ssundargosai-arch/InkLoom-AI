import asyncio
import json
from collections import defaultdict
from typing import Dict, Optional, Set

from fastapi import WebSocket


class CollaborationHub:
    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._user_connections: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._connection_reviews: Dict[WebSocket, int] = {}
        self._connection_users: Dict[WebSocket, int] = {}
        self._user_names: Dict[int, str] = {}
        self._user_roles: Dict[int, str] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        review_id: int,
        websocket: WebSocket,
        user_id: int,
        display_name: str,
        role: str,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[review_id].add(websocket)
            self._user_connections[user_id].add(websocket)
            self._connection_reviews[websocket] = review_id
            self._connection_users[websocket] = user_id
            self._user_names[user_id] = display_name
            self._user_roles[user_id] = role

    async def participants(self, review_id: int) -> list:
        async with self._lock:
            user_ids = {
                self._connection_users[client]
                for client in self._connections.get(review_id, set())
                if client in self._connection_users
            }
            return [
                {
                    "id": user_id,
                    "display_name": self._user_names.get(user_id, "Workspace member"),
                    "role": self._user_roles.get(user_id),
                }
                for user_id in sorted(user_ids)
            ]

    async def disconnect(self, review_id: int, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            self._connections[review_id].discard(websocket)
            if not self._connections[review_id]:
                self._connections.pop(review_id, None)
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                self._user_connections.pop(user_id, None)
            self._connection_reviews.pop(websocket, None)
            self._connection_users.pop(websocket, None)
            if not self._user_connections.get(user_id):
                self._user_names.pop(user_id, None)
                self._user_roles.pop(user_id, None)

    async def disconnect_user(self, user_id: int) -> None:
        async with self._lock:
            clients = list(self._user_connections.pop(user_id, set()))
            for client in clients:
                review_id = self._connection_reviews.pop(client, None)
                self._connection_users.pop(client, None)
                self._user_names.pop(user_id, None)
                self._user_roles.pop(user_id, None)
                if review_id is not None:
                    self._connections[review_id].discard(client)
                    if not self._connections[review_id]:
                        self._connections.pop(review_id, None)
        if clients:
            await asyncio.gather(
                *(client.close(code=4401, reason="Workspace access changed.") for client in clients),
                return_exceptions=True,
            )

    async def broadcast(
        self,
        review_id: int,
        message: dict,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        encoded = json.dumps(message, default=str)
        async with self._lock:
            clients = [
                client
                for client in self._connections.get(review_id, set())
                if client is not exclude
            ]
        if not clients:
            return
        results = await asyncio.gather(
            *(client.send_text(encoded) for client in clients),
            return_exceptions=True,
        )
        failed = [
            client
            for client, result in zip(clients, results)
            if isinstance(result, Exception)
        ]
        for client in failed:
            async with self._lock:
                user_id = self._connection_users.get(client)
            if user_id is not None:
                await self.disconnect(review_id, client, user_id)


collaboration_hub = CollaborationHub()
