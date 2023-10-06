import json
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi import Request, Response, Cookie
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from ConnectionManager import ConnectionManager
from datetime import datetime
from pydantic import BaseModel
from Utils import Socket


class RegisterValidator(BaseModel):
    username: str


app = FastAPI()
app.add_middleware(
   CORSMiddleware,
   allow_origins=["*"],
   allow_credentials=True,
   allow_methods=["*"],
   allow_headers=["*"],
)
manager = ConnectionManager()
templates = Jinja2Templates(directory="templates")


@app.get("/api/current_user")
def get_user(request: Request):
    return request.cookies.get("QuicChat-username")


@app.get("/get_files/{filename}")
async def download_file(filename):
    print("here")
    return FileResponse(f"./files/{filename}", filename=filename)


@app.get("/")
async def get_home(request: Request):
    return templates.TemplateResponse("hello.html", {"request": request})


@app.get("/chat")
async def get_home(request: Request):
    return templates.TemplateResponse("chatroom.html", {"request": request})


@app.post("/api/register")
async def register_user(request: Request, response: Response):
    data = (await request.body()).decode()
    data = json.loads(data)
    response.set_cookie(key="QuicChat-username", value=data['username'], httponly=True)

#
# @app.websocket("/api/chat")
# async def websocket_endpoint(websocket: WebSocket):
#     print("websocket")
#     user = websocket.cookies.get("QuicChat-username")
#     if user:
#         await manager.connect(websocket, user)
#         message = {"user": user, "message": "is here"}
#         await manager.broadcast(message)
#         now = datetime.now()
#         current_time = now.strftime("%H:%M")
#
#         try:
#             while True:
#                 data = await websocket.receive_text()
#                 message = {"time": current_time, "message": data}
#                 await manager.broadcast(json.dumps(message))
#         except WebSocketDisconnect:
#             manager.disconnect(websocket, user)
#             message = {"time": current_time, "message": "offline"}
#             await manager.broadcast(json.dumps(message))


async def wt(scope, receive, send) -> None:
    message = await receive()
    assert message["type"] == "webtransport.connect"
    await send({"type": "webtransport.accept"})
    file_buffer: Dict[int, Dict] = {}
    user: Socket
    while True:
        message = await receive()
        if message["type"] == "webtransport.datagram.receive":
            data = json.loads(message['data'].decode())
            if data["type"] == "welcome":
                username = data['username']
                user = Socket(username, receive, send)
                manager.add_new_user(user)
                broadcast_message = {
                    "data": json.dumps({"message": f"{user.id} is here"}).encode(),
                    "type": "webtransport.datagram.send",
                }
                await manager.broadcast(broadcast_message)
            if data["type"] == "text":
                broadcast_message = {
                    "data": json.dumps(data).encode(),
                    "type": "webtransport.datagram.send",
                }
                await manager.broadcast(broadcast_message)

        elif message["type"] == "webtransport.stream.receive":
            if not message["stream_ended"]:
                data: Any
                try:
                    data = json.loads(message['data'].decode())
                    if "type" in data:
                        message_type = data["type"]
                        if message_type == "upload_file":
                            filename = data["filename"]
                            file_buffer[message["stream"]] = {"filename": filename}
                            file_buffer[message["stream"]]["file_size"] = data["file_size"]
                            file_buffer[message["stream"]]["file_data"] = b''
                    else:
                        raise KeyError("No type key in data")
                except (KeyError, ValueError):
                    file_buffer[message["stream"]]["file_data"] += message["data"]

            else:
                file_buffer[message["stream"]]["file_data"] += message["data"]
                filename = file_buffer[message["stream"]]["filename"]
                file = open(f"./files/{user.id}_{filename}", "wb")
                file.write(bytes(json.loads(file_buffer[message["stream"]]["file_data"].decode())))
                file.close()

                msg_data = {"message": f"{user.id}_{filename}",
                            "sender": user.id}
                broadcast_message = {
                    "data": json.dumps(msg_data).encode(),
                    "type": "webtransport.datagram.send",
                }
                await manager.broadcast(broadcast_message)

        elif message["type"] == "webtransport.close":
            manager.disconnect(user)
            broadcast_message = {
                "data": json.dumps({"message": f'{user.id} left the room'}).encode(),
                "type": "webtransport.datagram.send",
            }
            await manager.broadcast(broadcast_message)
            # break


async def application(scope, receive, send) -> None:
    if scope["type"] == "webtransport" and scope["path"] == "/wt":
        await wt(scope, receive, send)
    else:
        await app(scope, receive, send)
