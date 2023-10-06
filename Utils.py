from typing import Dict, Optional, Union, List
from starlette.types import Receive, Send
from aioquic.tls import SessionTicket

# from Http3 import HttpRequestHandler
# from Websocket import WebSocketHandler
# from WebTransport import WebTransportHandler


SERVERNAME = 'QUICChat'



class SessionTicketStore:
    def __init__(self) -> None:
        self.tickets: Dict[bytes, SessionTicket] = {}

    def add(self, ticket: SessionTicket) -> None:
        self.tickets[ticket.ticket] = ticket

    def pop(self, label: bytes) -> Optional[SessionTicket]:
        return self.tickets.pop(label, None)


class Socket:
    def __init__(self, connection_id: str, receive: Receive, send: Send) -> None:
        self.id = connection_id
        self.receive = receive
        self.send = send
