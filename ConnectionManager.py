from typing import List
from datetime import datetime
from Utils import Socket
import json


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[Socket] = []

    def add_new_user(self, socket: Socket):
        self.active_connections.append(socket)

    def size(self) -> int:
        return len(self.active_connections)

    def disconnect(self, socket: Socket):
        self.active_connections.remove(socket)

    async def broadcast(self, message):
        for socket in self.active_connections:
            await socket.send(message)



