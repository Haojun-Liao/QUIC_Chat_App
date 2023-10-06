import asyncio
import importlib
import time
import ssl
from collections import deque
from typing import Dict, Optional, Union, Callable, cast, Deque, List
from email.utils import formatdate

import wsproto
import wsproto.events

from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.exceptions import NoAvailablePushIDError
from aioquic.h0.connection import H0_ALPN, H0Connection
from aioquic.quic.events import DatagramFrameReceived, ProtocolNegotiated, QuicEvent, ConnectionTerminated
from aioquic.h3.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)

SERVERNAME = 'QUICChat'


class WebSocketHandler:
    def __init__(self, *, connection: H3Connection, scope: Dict, stream_id: int, transmit: Callable[[], None],) -> None:
        self.closed = False
        self.connection = connection
        self.http_event_queue: Deque[DataReceived] = deque()
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.scope = scope
        self.stream_id = stream_id
        self.transmit = transmit
        self.websocket: Optional[wsproto.Connection] = None

    def http_event_receive(self, event: H3Event) -> None:
        if isinstance(event, DataReceived) and not self.closed:
            if self.websocket is not None:
                self.websocket.receive_data(event.data)

                for ws_event in self.websocket.events():
                    self.websocket_event_received(ws_event)
            else:
                self.http_event_queue.append(event)

    def websocket_event_received(self, event: wsproto.events.Event) -> None:
        if isinstance(event, wsproto.events.TextMessage):
            self.queue.put_nowait({'type': 'websocket.receive', 'text': event.data})
        elif isinstance(event, wsproto.events.Message):
            self.queue.put_nowait({"type": "websocket.receive", "bytes": event.data})
        elif isinstance(event, wsproto.events.CloseConnection):
            self.queue.put_nowait({"type": "websocket.disconnect", "code": event.code})

    async def receive(self) -> Dict:
        return await self.queue.get()

    async def send(self, message: Dict) -> None:
        data = b''
        end_stream = False

        if message['type'] == 'websocket.accept':
            subprotocol = message.get('subprotocol')
            self.websocket = wsproto.Connection(wsproto.ConnectionType.SERVER)
            headers = [(b':status', b'200'),
                       (b'server', SERVERNAME.encode()),
                       (b'date', formatdate(time.time(), usegmt=True).encode())]
            if subprotocol is not None:
                headers.append((b'sec-websocket-protocol', subprotocol.encode()))
            self.connection.send_headers(stream_id=self.stream_id, headers=headers)

            while self.http_event_queue:
                self.http_event_receive(self.http_event_queue.popleft())

        elif message['type'] == 'websocket.close':
            if self.websocket is not None:
                data = self.websocket.send(
                    wsproto.events.CloseConnection(code=message['code'])
                )
            else:
                self.connection.send_headers(stream_id=self.stream_id, headers=[(b':status', b'403')])
            end_stream = True

        elif message['type'] == 'websocket.send':
            if message.get('text') is not None:
                data = self.websocket.send(wsproto.events.TextMessage(data=message['text']))
            elif message.get('bytes') is not None:
                data = self.websocket.send(wsproto.events.Message(data=message['bytes']))

        if data:
            self.connection.send_data(stream_id=self.stream_id, data=data, end_stream=end_stream)
        if end_stream:
            self.closed = True
        self.transmit()

    async def run_asgi(self, app: Callable) -> None:
        self.queue.put_nowait({'type': 'websocket.connect'})

        try:
            await app(self.scope, self.receive, self.send)
        finally:
            if not self.closed:
                await self.send({'type': 'websocket.close', 'code': 1000})
