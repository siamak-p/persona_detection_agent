
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ws", tags=["WebSocket"])


class ConnectionManager:
    
    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        
        logger.info(
            "ws:connect",
            extra={"user_id": user_id, "total_connections": len(self._connections.get(user_id, set()))},
        )
    
    async def disconnect(self, websocket: WebSocket, user_id: str):
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        
        logger.info("ws:disconnect", extra={"user_id": user_id})
    
    async def send_to_user(self, user_id: str, message: dict) -> bool:
        if user_id not in self._connections:
            logger.debug("ws:send:no_connection", extra={"user_id": user_id})
            return False
        
        message_json = json.dumps(message, ensure_ascii=False, default=str)
        
        disconnected = set()
        for websocket in self._connections[user_id]:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.warning(
                    "ws:send:error",
                    extra={"user_id": user_id, "error": str(e)},
                )
                disconnected.add(websocket)
        
        async with self._lock:
            for ws in disconnected:
                self._connections[user_id].discard(ws)
        
        return True
    
    async def broadcast(self, message: dict):
        message_json = json.dumps(message, ensure_ascii=False, default=str)
        
        for user_id, connections in list(self._connections.items()):
            for websocket in connections:
                try:
                    await websocket.send_text(message_json)
                except Exception:
                    pass
    
    def is_connected(self, user_id: str) -> bool:
        return user_id in self._connections and len(self._connections[user_id]) > 0
    
    def get_connected_users(self) -> list[str]:
        return list(self._connections.keys())


connection_manager = ConnectionManager()


@router.websocket("/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await connection_manager.connect(websocket, user_id)
    
    try:
        await websocket.send_json({
            "type": "connected",
            "message": f"Connected as {user_id}",
            "timestamp": datetime.now().isoformat(),
        })
        
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0,
                )
                
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
                    
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                    
    except WebSocketDisconnect:
        logger.info("ws:client_disconnected", extra={"user_id": user_id})
    except Exception as e:
        logger.error(
            "ws:error",
            extra={"user_id": user_id, "error": str(e)},
            exc_info=True,
        )
    finally:
        await connection_manager.disconnect(websocket, user_id)


@router.get("/status")
async def get_websocket_status():
    return {
        "connected_users": connection_manager.get_connected_users(),
        "total_users": len(connection_manager.get_connected_users()),
    }


async def notify_future_response(
    sender_id: str,
    recipient_id: str,
    recipient_name: str | None,
    detected_plan: str,
    creator_response: str,
) -> bool:
    name_part = recipient_name or recipient_id
    
    message = {
        "type": "future_response",
        "from_user": recipient_id,
        "from_name": name_part,
        "plan": detected_plan,
        "response": creator_response,
        "message": f"📬 {name_part} به درخواست شما ({detected_plan}) پاسخ داد:\n{creator_response}",
        "timestamp": datetime.now().isoformat(),
    }
    
    success = await connection_manager.send_to_user(sender_id, message)
    
    if success:
        logger.info(
            "ws:notify_future_response:sent",
            extra={"sender_id": sender_id, "recipient_id": recipient_id},
        )
    else:
        logger.info(
            "ws:notify_future_response:user_not_connected",
            extra={"sender_id": sender_id},
        )
    
    return success


async def notify_future_request_to_creator(
    creator_id: str,
    sender_id: str,
    sender_name: str | None,
    request_id: int,
    original_message: str,
    detected_plan: str,
    detected_datetime: str | None,
) -> bool:
    name_part = sender_name or sender_id
    
    message_text = f"📅 درخواست جدید از {name_part}:\n\n\"{original_message}\"\n\n🎯 برنامه: {detected_plan}"
    if detected_datetime:
        message_text += f"\n⏰ زمان: {detected_datetime}"
    
    message = {
        "type": "future_request",
        "request_id": request_id,
        "from_user": sender_id,
        "from_name": name_part,
        "original_message": original_message,
        "plan": detected_plan,
        "datetime": detected_datetime,
        "requires_action": True,
        "message": message_text,
        "timestamp": datetime.now().isoformat(),
    }
    
    success = await connection_manager.send_to_user(creator_id, message)
    
    if success:
        logger.info(
            "ws:notify_future_request_to_creator:sent",
            extra={"creator_id": creator_id, "sender_id": sender_id, "request_id": request_id},
        )
    else:
        logger.info(
            "ws:notify_future_request_to_creator:user_not_connected",
            extra={"creator_id": creator_id, "request_id": request_id},
        )
    
    return success


async def notify_financial_topic_to_creator(
    creator_id: str,
    sender_id: str,
    thread_id: int,
    original_message: str,
    topic_summary: str,
    amount: str | None = None,
) -> bool:
    message_text = f"💰 موضوع مالی جدید:\n\n\"{original_message}\"\n\n📌 موضوع: {topic_summary}"
    if amount:
        message_text += f"\n💵 مبلغ: {amount}"
    
    message = {
        "type": "financial_topic",
        "thread_id": thread_id,
        "from_user": sender_id,
        "original_message": original_message,
        "topic_summary": topic_summary,
        "amount": amount,
        "requires_action": True,
        "message": message_text,
        "timestamp": datetime.now().isoformat(),
    }
    
    success = await connection_manager.send_to_user(creator_id, message)
    
    if success:
        logger.info(
            "ws:notify_financial_topic:sent",
            extra={"creator_id": creator_id, "thread_id": thread_id},
        )
    else:
        logger.info(
            "ws:notify_financial_topic:user_not_connected",
            extra={"creator_id": creator_id, "thread_id": thread_id},
        )
    
    return success


async def notify_financial_message_to_creator(
    creator_id: str,
    sender_id: str,
    thread_id: int,
    message: str,
) -> bool:
    notification = {
        "type": "financial_message",
        "thread_id": thread_id,
        "from_user": sender_id,
        "message": message,
        "display_text": f"💰 پیام جدید در موضوع مالی:\n\n\"{message}\"",
        "requires_action": True,
        "timestamp": datetime.now().isoformat(),
    }
    
    success = await connection_manager.send_to_user(creator_id, notification)
    
    if success:
        logger.info(
            "ws:notify_financial_message:sent",
            extra={"creator_id": creator_id, "thread_id": thread_id},
        )
    
    return success


async def notify_financial_response_to_sender(
    sender_id: str,
    creator_id: str,
    creator_name: str | None,
    thread_id: int,
    topic_summary: str,
    creator_response: str,
) -> bool:
    name_part = creator_name or creator_id
    
    message = {
        "type": "financial_response",
        "thread_id": thread_id,
        "from_user": creator_id,
        "from_name": name_part,
        "topic_summary": topic_summary,
        "response": creator_response,
        "message": f"💰 {name_part} درباره {topic_summary} پاسخ داد:\n{creator_response}",
        "timestamp": datetime.now().isoformat(),
    }
    
    success = await connection_manager.send_to_user(sender_id, message)
    
    if success:
        logger.info(
            "ws:notify_financial_response:sent",
            extra={"sender_id": sender_id, "thread_id": thread_id},
        )
    
    return success
