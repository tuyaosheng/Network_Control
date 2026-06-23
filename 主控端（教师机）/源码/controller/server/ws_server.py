"""
主控端 WebSocket 服务器 - 管理所有被控端连接，下发指令
"""
import asyncio
import logging
import socket
import ipaddress
from collections import deque
from datetime import datetime
from typing import Callable

import websockets
from websockets.server import WebSocketServerProtocol

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from shared.protocol import (
    MSG_REGISTER, MSG_HEARTBEAT, MSG_STATUS, MSG_ACK, MSG_BROWSING_UPDATE,
    MODE_WHITELIST, MODE_BLACKLIST,
    parse_msg, msg_update_rules, msg_set_filter,
    msg_disconnect, msg_reconnect, msg_get_status
)

logger = logging.getLogger("ws_server")


class ConnectedAgent:
    def __init__(self, ws: WebSocketServerProtocol | None, ip: str):
        self.ws            = ws
        self.ip            = ip
        self.hostname      = ""
        self.mac           = ""
        self.filter_active = False
        self.net_state     = "normal"
        self.is_online     = True
        self.connected_at  = datetime.now()
        self.last_seen     = datetime.now()
        self.recent_domains: deque = deque(maxlen=30)

    def to_dict(self) -> dict:
        return {
            "ip":             self.ip,
            "hostname":       self.hostname,
            "mac":            self.mac,
            "filter_active":  self.filter_active,
            "net_state":      self.net_state,
            "is_online":      self.is_online,
            "connected_at":   self.connected_at.strftime("%H:%M:%S"),
            "last_seen":      self.last_seen.strftime("%H:%M:%S"),
            "recent_domains": list(self.recent_domains),
        }


class ControllerServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765,
                 on_agent_change: Callable | None = None,
                 on_agent_reconnect: Callable | None = None,
                 initial_states: dict | None = None):
        self.host              = host
        self.port              = port
        self.on_agent_change   = on_agent_change
        self._on_agent_reconnect = on_agent_reconnect
        self._agents: dict[str, ConnectedAgent]         = {}   # 在线
        self._offline: dict[str, ConnectedAgent]        = {}   # 曾连接但已断开
        self._saved_states: dict[str, str]              = initial_states or {}
        self._lock   = asyncio.Lock()
        self._server = None

    # ── 公开接口 ─────────────────────────────────────────────────

    def get_agents(self) -> list[dict]:
        """返回所有被控端（在线在前，离线在后）。"""
        online  = [a.to_dict() for a in self._agents.values()]
        offline = [a.to_dict() for a in self._offline.values()]
        return online + offline

    def get_online_ips(self) -> list[str]:
        return list(self._agents.keys())

    def update_saved_state(self, ip: str, net_state: str):
        self._saved_states[ip] = net_state

    async def push_rules(self, domains: list[str], lan_subnets: list[str],
                         upstream_dns: str, mode: str = MODE_WHITELIST,
                         target_ip: str | None = None,
                         tray_pwd_hash: str = "",
                         unlock_pwd_hash: str = ""):
        controller_ip = self._get_local_ip()
        raw = msg_update_rules(domains, lan_subnets, controller_ip, upstream_dns,
                               mode, tray_pwd_hash, unlock_pwd_hash)
        await self._broadcast(raw, target_ip)

    async def set_filter(self, enabled: bool, mode: str = MODE_WHITELIST,
                         target_ip: str | None = None):
        raw = msg_set_filter(enabled, mode)
        await self._broadcast(raw, target_ip)

    async def disconnect_internet(self, target_ip: str | None = None):
        await self._broadcast(msg_disconnect(), target_ip)

    async def reconnect_internet(self, target_ip: str | None = None):
        await self._broadcast(msg_reconnect(), target_ip)

    async def request_status(self, target_ip: str | None = None):
        await self._broadcast(msg_get_status(), target_ip)

    # ── 内部逻辑 ─────────────────────────────────────────────────

    async def _broadcast(self, raw: str, target_ip: str | None):
        async with self._lock:
            targets = (
                [self._agents[target_ip]] if target_ip and target_ip in self._agents
                else list(self._agents.values())
            )
        failed = []
        for agent in targets:
            try:
                await agent.ws.send(raw)
            except Exception as e:
                logger.warning(f"发送失败 [{agent.ip}]: {e}")
                failed.append(agent.ip)
        for ip in failed:
            async with self._lock:
                agent = self._agents.pop(ip, None)
                if agent:
                    agent.ws        = None
                    agent.is_online = False
                    self._offline[ip] = agent
            self._notify_change()

    async def _handle_connection(self, ws: WebSocketServerProtocol):
        ip = ws.remote_address[0]
        logger.info(f"新连接: {ip}")

        async with self._lock:
            # 若是曾经连过的离线机器重连，复用其历史信息（含断线前的 net_state）
            prev = self._offline.pop(ip, None)
            if prev:
                agent = prev
                agent.ws        = ws
                agent.is_online = True
                agent.connected_at = datetime.now()
            else:
                agent = ConnectedAgent(ws, ip)
                # 跨会话（主控重启后）：从持久化状态恢复 net_state
                saved = self._saved_states.get(ip, "normal")
                if saved != "normal":
                    agent.net_state = saved
            self._agents[ip] = agent

        try:
            async for raw in ws:
                await self._handle_message(agent, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"连接异常 [{ip}]: {e}")
        finally:
            async with self._lock:
                self._agents.pop(ip, None)
                agent.ws        = None
                agent.is_online = False
                self._offline[ip] = agent
            logger.info(f"断开连接: {ip}")
            self._notify_change()

    async def _handle_message(self, agent: ConnectedAgent, raw: str):
        try:
            msg = parse_msg(raw)
        except Exception:
            return
        t = msg.get("type")
        agent.last_seen = datetime.now()

        if t == MSG_REGISTER:
            agent.hostname = msg.get("hostname", "")
            agent.mac      = msg.get("mac", "")
            logger.info(f"注册: {agent.ip} ({agent.hostname})")
            self._notify_change()
            # 被控端开机默认断网（fail-closed），注册时按【老师设过的权威状态】下发，含 normal=放行。
            # 必须用 _saved_states（老师意图），不能用 agent.net_state——后者会被"开机临时断网"的
            # 自报污染，导致每次开机都被误判为断网、即使老师从没设过断网也开不了网。
            if self._on_agent_reconnect:
                authoritative = self._saved_states.get(agent.ip, "normal")
                asyncio.create_task(self._on_agent_reconnect(agent.ip, authoritative))

        elif t in (MSG_HEARTBEAT, MSG_STATUS):
            agent.filter_active = msg.get("filter_active", False)
            agent.net_state     = msg.get("net_state", "normal")
            self._notify_change()

        elif t == MSG_BROWSING_UPDATE:
            domains = msg.get("domains", [])
            for d in domains:
                agent.recent_domains.append(d)
            self._notify_change()

        elif t == MSG_ACK:
            logger.info(f"ACK [{agent.ip}]: {msg.get('message', '')}")

    def _notify_change(self):
        if self.on_agent_change:
            self.on_agent_change()

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def start(self):
        self._server = await websockets.serve(
            self._handle_connection, self.host, self.port,
            ping_interval=30, ping_timeout=10
        )
        logger.info(f"WebSocket服务器已启动: {self.host}:{self.port}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


async def scan_ip_range(subnet: str, port: int = 8765,
                        timeout: float = 0.5) -> list[str]:
    network = ipaddress.IPv4Network(subnet, strict=False)
    results = []

    async def check(ip_str):
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip_str, port), timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            results.append(ip_str)
        except Exception:
            pass

    await asyncio.gather(*[check(str(ip)) for ip in network.hosts()])
    return sorted(results)
