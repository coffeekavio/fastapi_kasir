# api/websockets.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List

router = APIRouter()

# Kelas untuk menyimpan daftar kasir yang sedang terhubung
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    # Fungsi untuk "berteriak" ke semua kasir
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"Gagal mengirim pesan: {e}")

# Buat instance manager
manager = ConnectionManager()

# Endpoint WebSocket (ws://domain-anda/api/ws/updates)
@router.websocket("/api/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Tetap biarkan koneksi terbuka
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)