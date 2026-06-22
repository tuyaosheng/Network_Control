"""
被控端 WebSocket 客户端 - 连接主控端，断线自动重连
"""
import asyncio
import logging
import socket
import uuid
import os
import sys
from typing import Callable

import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from shared.protocol import (
    MSG_UPDATE_RULES, MSG_GET_STATUS, MSG_SET_FILTER,
    MSG_DISCONNECT, MSG_RECONNECT, MSG_BROWSING_UPDATE,
    MODE_WHITELIST,
    msg_register, msg_heartbeat, msg_status, msg_ack,
    msg_browsing_update, parse_msg
)

logger = logging.getLogger("ws_client")

HEARTBEAT_INTERVAL  = 20   # 秒
RECONNECT_DELAY     = 5    # 秒
BROWSING_INTERVAL   = 15   # 秒


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_mac() -> str:
    mac = uuid.getnode()
    return ":".join(f"{(mac >> i) & 0xff:02x}" for i in range(40, -1, -8))


class AgentWSClient:
    def __init__(self, controller_url: str,
                 on_update_rules: Callable | None = None,
                 on_set_filter: Callable | None = None,
                 on_disconnect: Callable | None = None,
                 on_reconnect: Callable | None = None,
                 get_status_fn: Callable | None = None,
                 get_browsing_fn: Callable | None = None):
        self.url            = controller_url
        self.on_update_rules = on_update_rules
        self.on_set_filter   = on_set_filter
        self.on_disconnect   = on_disconnect
        self.on_reconnect    = on_reconnect
        self.get_status_fn   = get_status_fn
        self.get_browsing_fn = get_browsing_fn
        self._ws   = None
        self._stop = False
        self.connected     = False
        self.filter_active = False
        self._net_state    = "normal"

    async def run(self):
        while not self._stop:
            try:
                logger.info(f"连接主控端: {self.url}")
                async with websockets.connect(self.url, ping_interval=None) as ws:
                    self._ws = ws
                    self.connected = True
                    logger.info("已连接主控端")
                    await self._on_connected(ws)
                    done, pending = await asyncio.wait(
                        [
                            asyncio.create_task(self._recv_loop(ws)),
                            asyncio.create_task(self._heartbeat_loop(ws)),
                            asyncio.create_task(self._browsing_loop(ws)),
                        ],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in pending:
                        t.cancel()
            except Exception as e:
                logger.warning(f"连接断开: {e}")
            finally:
                self._ws = None
                self.connected = False
                if not self._stop:
                    logger.info(f"{RECONNECT_DELAY}s 后重连...")
                    await asyncio.sleep(RECONNECT_DELAY)

    async def _on_connected(self, ws):
        await ws.send(msg_register(socket.gethostname(), get_local_ip(), get_mac()))

    async def _recv_loop(self, ws):
        async for raw in ws:
            try:
                await self._handle(ws, raw)
            except Exception as e:
                logger.error(f"处理消息异常: {e}")

    async def _heartbeat_loop(self, ws):
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await ws.send(msg_heartbeat(self.filter_active, self._net_state))
            except Exception:
                break

    async def _browsing_loop(self, ws):
        while True:
            await asyncio.sleep(BROWSING_INTERVAL)
            if not self.get_browsing_fn:
                continue
            try:
                domains = self.get_browsing_fn()
                if domains:
                    await ws.send(msg_browsing_update(domains))
            except Exception:
                break

    async def _handle(self, ws, raw: str):
        msg = parse_msg(raw)
        t = msg.get("type")

        if t == MSG_UPDATE_RULES:
            domains         = msg.get("domains", [])
            lan_subnets     = msg.get("lan_subnets", [])
            controller_ip   = msg.get("controller_ip", "")
            upstream_dns    = msg.get("upstream_dns", "114.114.114.114")
            mode            = msg.get("mode", MODE_WHITELIST)
            tray_pwd_hash   = msg.get("tray_pwd_hash", "")
            unlock_pwd_hash = msg.get("unlock_pwd_hash", "")
            if self.on_update_rules:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.on_update_rules,
                    domains, lan_subnets, controller_ip, upstream_dns, mode,
                    tray_pwd_hash, unlock_pwd_hash
                )
            await ws.send(msg_ack(True, "规则已应用"))

        elif t == MSG_SET_FILTER:
            enabled = msg.get("enabled", True)
            mode    = msg.get("mode", MODE_WHITELIST)
            self.filter_active = enabled
            self._net_state    = mode if enabled else "normal"
            if self.on_set_filter:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.on_set_filter, enabled, mode
                )
            await ws.send(msg_ack(True))

        elif t == MSG_DISCONNECT:
            self.filter_active = False
            self._net_state    = "disconnect"
            if self.on_disconnect:
                await asyncio.get_event_loop().run_in_executor(None, self.on_disconnect)
            await ws.send(msg_ack(True, "已断网（局域网保留）"))

        elif t == MSG_RECONNECT:
            self.filter_active = False
            self._net_state    = "normal"
            if self.on_reconnect:
                await asyncio.get_event_loop().run_in_executor(None, self.on_reconnect)
            await ws.send(msg_ack(True, "已恢复上网"))

        elif t == MSG_GET_STATUS:
            s = self.get_status_fn() if self.get_status_fn else {}
            await ws.send(msg_status(
                filter_active=s.get("filter_active", False),
                dns_running=s.get("dns_running", False),
                rule_count=s.get("rule_count", 0),
                net_state=s.get("net_state", "normal")
            ))

    def stop(self):
        self._stop = True
