"""
本地 DNS 服务器 - 支持白名单和黑名单两种模式
白名单：只放行指定域名（含通配符），其余 NXDOMAIN
        解析白名单域名时把上游返回的 IP 实时传给回调（用于动态加路由）
黑名单：拦截指定域名，其余正常解析
"""
import threading
import socket
import logging
from typing import Callable

from dnslib import DNSRecord, RCODE, QTYPE
from dnslib.server import DNSServer, BaseResolver

from shared.protocol import MODE_WHITELIST, MODE_BLACKLIST

logger = logging.getLogger("dns_server")


class FilterResolver(BaseResolver):
    def __init__(self, domains: list[str], upstream_dns: str,
                 mode: str = MODE_WHITELIST,
                 on_query: Callable[[str], None] | None = None,
                 on_resolved_ips: Callable[[list[str]], None] | None = None):
        self._lock = threading.Lock()
        self.upstream_dns = upstream_dns
        self.mode = mode
        self.on_query = on_query
        # 白名单模式：每次解析后把 A 记录里的 IP 通过此回调交给 firewall 模块加路由
        self.on_resolved_ips = on_resolved_ips
        self._domains: list[str] = []
        self.update_domains(domains)

    def update_domains(self, domains: list[str]):
        normalized = [d.strip().lower().rstrip(".") for d in domains if d.strip()]
        with self._lock:
            self._domains = normalized
        logger.info(f"[{self.mode}] 规则已更新，共 {len(normalized)} 条域名")

    def _matches(self, qname: str) -> bool:
        name = qname.lower().rstrip(".")
        with self._lock:
            for pattern in self._domains:
                if pattern.startswith("*."):
                    base = pattern[2:]
                    if name == base or name.endswith("." + base):
                        return True
                else:
                    if name == pattern or name.endswith("." + pattern):
                        return True
        return False

    def _forward(self, request):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(request.pack(), (self.upstream_dns, 53))
            data, _ = sock.recvfrom(4096)
            sock.close()
            return DNSRecord.parse(data)
        except Exception as e:
            logger.warning(f"上游DNS查询失败: {e}")
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply

    @staticmethod
    def _extract_a_records(response) -> list[str]:
        """从 DNS 响应中提取所有 A 记录里的 IPv4 地址。"""
        ips: list[str] = []
        try:
            for rr in response.rr:
                if rr.rtype == QTYPE.A:
                    ips.append(str(rr.rdata))
        except Exception:
            pass
        return ips

    def resolve(self, request, handler):
        qname = str(request.q.qname)
        qtype = request.q.qtype

        if self.on_query:
            clean = qname.rstrip(".")
            if "." in clean and not clean.endswith(".local") and not clean.startswith("_"):
                try:
                    self.on_query(clean)
                except Exception:
                    pass

        matched = self._matches(qname)

        if self.mode == MODE_WHITELIST:
            if not matched:
                logger.debug(f"[白名单拦截] {qname}")
                reply = request.reply()
                reply.header.rcode = RCODE.NXDOMAIN
                return reply

            # AAAA / IPv6 查询：返回空答案（NOERROR 无记录），强制浏览器走 IPv4
            # 否则浏览器拿到 IPv6 地址但路由表只有 IPv4 路由，会死等超时
            if qtype == QTYPE.AAAA:
                return request.reply()

            # A 查询：转发上游 → 把返回的 IP 加进路由表 → 同步返回给浏览器
            response = self._forward(request)
            if self.on_resolved_ips and response.header.rcode == RCODE.NOERROR:
                ips = self._extract_a_records(response)
                if ips:
                    try:
                        # 同步调用：路由必须加完再把响应给浏览器，否则浏览器先建连接会失败
                        self.on_resolved_ips(ips)
                    except Exception as e:
                        logger.warning(f"动态加路由失败 ({qname}): {e}")
            return response

        else:  # MODE_BLACKLIST
            if matched:
                logger.debug(f"[黑名单拦截] {qname}")
                reply = request.reply()
                reply.header.rcode = RCODE.NXDOMAIN
                return reply
            return self._forward(request)


class LocalDNSServer:
    def __init__(self, domains: list[str], upstream_dns: str = "114.114.114.114",
                 mode: str = MODE_WHITELIST,
                 bind_addr: str = "127.0.0.1", port: int = 53,
                 on_query: Callable[[str], None] | None = None,
                 on_resolved_ips: Callable[[list[str]], None] | None = None):
        self.resolver = FilterResolver(domains, upstream_dns, mode, on_query, on_resolved_ips)
        self.bind_addr = bind_addr
        self.port = port
        self._server: DNSServer | None = None
        self._thread: threading.Thread | None = None
        self.running = False

    def start(self):
        if self.running:
            return
        try:
            self._server = DNSServer(self.resolver,
                                     address=self.bind_addr,
                                     port=self.port,
                                     tcp=False)
            self._thread = threading.Thread(target=self._server.start, daemon=True)
            self._thread.start()
            self.running = True
            logger.info(f"DNS服务器已启动: {self.bind_addr}:{self.port} 模式={self.resolver.mode}")
        except Exception as e:
            logger.error(f"DNS服务器启动失败: {e}")
            raise

    def stop(self):
        if self._server and self.running:
            try:
                self._server.stop()
            except Exception:
                pass
            self.running = False
            logger.info("DNS服务器已停止")

    def update_domains(self, domains: list[str]):
        self.resolver.update_domains(domains)
