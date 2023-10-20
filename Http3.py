import asyncio
import time
from typing import Dict, Callable
from email.utils import formatdate

from aioquic.asyncio import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)

SERVERNAME = "QuicChat"


class HttpRequestHandler:
    def __init__(self, *, authority: bytes, connection: H3Connection, protocol: QuicConnectionProtocol, scope: Dict,
                 stream_ended: bool, stream_id: int, transmit: Callable[[], None]) -> None:
        self.authority = authority
        self.connection = connection
        self.protocol = protocol
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit

        if stream_ended:
            self.queue.put_nowait({"type": "http.request"})

    async def receive(self) -> Dict:
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        if message["type"] == 'http.response.start':
            self.connection.send_headers(stream_id=self.stream_id,
                                         headers=[(b':status', str(message['status']).encode()),
                                                  (b'server', SERVERNAME.encode()),
                                                  (b'date', formatdate(time.time(), usegmt=True).encode())] +
                                                 [(h, v) for h, v in message['headers']]
                                         )
        elif message['type'] == 'http.response.body':
            self.connection.send_data(stream_id=self.stream_id,
                                      data=message.get("body", b''),
                                      end_stream=not message.get('more_body', False), )

        self.transmit()

    def http_event_receive(self, event: H3Event) -> None:
        if isinstance(event, DataReceived):
            self.queue.put_nowait({"type": "http.request", "body": event.data, "more_body": not event.stream_ended})
        elif isinstance(event, HeadersReceived) and event.stream_ended:
            self.queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})

    async def run_asgi(self, app: Callable) -> None:
        await app(self.scope, self.receive, self.send)
