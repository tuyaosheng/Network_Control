"""
主控端 HTTP 控制接口 - 供外部程序调用，实现「一键开网 / 一键禁网」

设计要点：
- 用 Python 标准库 http.server，独立 daemon 线程运行，零额外依赖。
- 不直接操作 WebSocket / DB，而是通过回调把动作转交给 Qt 主线程执行，
  与项目既有的「跨线程用信号」模型保持一致，避免 sqlite 跨线程和并发问题。
- 回调本身只负责「触发」（emit 信号），动作是异步完成的，因此接口立即返回
  202 Accepted，不等待被控端真正切换完成。
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("api_server")


class ControlAPIServer:
    """对外 HTTP 控制接口。

    Args:
        host:       监听地址，默认 127.0.0.1（仅本机调用）。需局域网其他机器调用改 0.0.0.0。
        port:       监听端口，默认 8770。
        token:      访问令牌，非空时所有写操作需携带（Header 或 query），空则不校验。
        on_enable:     开网回调（无参），线程安全（内部应只 emit 信号）。
        on_disable:    禁网回调（无参），同上。
        on_enable_ip:  按 IP 开单台回调（参数为 IP 字符串），同上。供学习平台使用。
        on_disable_ip: 按 IP 禁单台回调（参数为 IP 字符串），同上。供学习平台同步状态使用。
        get_status:    返回状态的回调，返回可 JSON 序列化对象（如被控端列表）。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8770, token: str = "",
                 on_enable: Optional[Callable[[], None]] = None,
                 on_disable: Optional[Callable[[], None]] = None,
                 on_enable_ip: Optional[Callable[[str], None]] = None,
                 on_disable_ip: Optional[Callable[[str], None]] = None,
                 get_status: Optional[Callable[[], object]] = None):
        self.host          = host
        self.port          = port
        self.token         = token
        self.on_enable     = on_enable
        self.on_disable    = on_disable
        self.on_enable_ip  = on_enable_ip
        self.on_disable_ip = on_disable_ip
        self.get_status    = get_status
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread]   = None

    def start(self):
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="control-api", daemon=True)
        self._thread.start()
        logger.info(f"控制接口已启动: http://{self.host}:{self.port}  "
                    f"(token={'已启用' if self.token else '未设置'})")

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ── 内部 ──────────────────────────────────────────────────────

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            # 把 http.server 的标准 stderr 日志接到项目 logger
            def log_message(self, fmt, *args):
                logger.info("API %s %s", self.address_string(), fmt % args)

            def _send(self, code: int, payload: dict):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                # 不再下发 Access-Control-Allow-Origin: *
                # 否则任意网页都能跨源读取 /api/status（全班 IP / 主机名 / 浏览记录）
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self, query: dict) -> bool:
                if not outer.token:
                    return True
                if self._token_in_header():
                    return True
                if query.get("token", [""])[0] == outer.token:
                    return True
                return False

            def _token_in_header(self) -> bool:
                """令牌是否通过请求头提供。<img>/<form> 这类 CSRF 载体无法设置自定义头，
                因此「头里带对令牌」可以直接认定不是 CSRF。query 里的令牌不算。"""
                if not outer.token:
                    return False
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer ") and auth[7:].strip() == outer.token:
                    return True
                if self.headers.get("X-API-Token", "").strip() == outer.token:
                    return True
                return False

            def _csrf_reason(self) -> str:
                """识别「浏览器发起的跨站请求」——CSRF 的必要特征。返回拦截原因，空串表示放行。

                背景：接口默认无令牌且绑 127.0.0.1，但绑本机挡不住 CSRF——请求正是从老师
                自己的浏览器发出的。老师只要打开一个恶意网页，页面里一行
                    <img src="http://127.0.0.1:8770/api/network/disable">
                就能让全班断网（同源策略拦的是「读响应」，不是「发请求」）。

                判据用 Fetch Metadata（Chrome 76+/Edge/Firefox 90+ 均发送）：
                  - 地址栏直接访问 → Sec-Fetch-Site: none,       Sec-Fetch-Dest: document  → 放行
                  - <img> 加载      → Sec-Fetch-Site: cross-site, Sec-Fetch-Dest: image     → 拦截
                  - 跨站 fetch/表单 → Sec-Fetch-Site: cross-site（且通常带 Origin）        → 拦截
                  - curl / PowerShell / Python requests → 这些头一个都不发                 → 放行
                """
                origin = (self.headers.get("Origin") or "").strip()
                if origin:
                    allowed = {
                        f"http://{outer.host}:{outer.port}",
                        f"http://127.0.0.1:{outer.port}",
                        f"http://localhost:{outer.port}",
                    }
                    if origin not in allowed:
                        return f"跨源 Origin: {origin}"
                site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
                if site and site not in ("none", "same-origin"):
                    return f"Sec-Fetch-Site: {site}"
                dest = (self.headers.get("Sec-Fetch-Dest") or "").strip().lower()
                if dest and dest not in ("document", "empty"):
                    return f"Sec-Fetch-Dest: {dest}"
                return ""

            def _dispatch(self):
                parsed = urlparse(self.path)
                path   = parsed.path.rstrip("/") or "/"
                query  = parse_qs(parsed.query)

                # 健康检查 / 状态查询无需鉴权
                if path in ("/api/health", "/health", "/"):
                    self._send(200, {"ok": True, "service": "network_control"})
                    return

                if path in ("/api/status", "/status"):
                    data = []
                    if outer.get_status:
                        try:
                            data = outer.get_status()
                        except Exception as e:
                            logger.warning(f"获取状态失败: {e}")
                    self._send(200, {"ok": True, "agents": data})
                    return

                # 写操作：先挡 CSRF，再鉴权。
                # 令牌通过请求头提供时跳过——能设自定义头就说明不是 <img>/<form> 型 CSRF。
                if not self._token_in_header():
                    reason = self._csrf_reason()
                    if reason:
                        logger.warning(
                            f"已拦截疑似 CSRF 请求 [{self.address_string()}] "
                            f"{self.command} {path} （{reason}）"
                        )
                        self._send(403, {"ok": False, "error": "cross-site request blocked",
                                         "detail": reason})
                        return

                if not self._authorized(query):
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return

                if path in ("/api/network/enable", "/api/enable", "/enable"):
                    if outer.on_enable:
                        outer.on_enable()
                    self._send(202, {"ok": True, "action": "enable",
                                     "message": "已下发『全部允许上网』指令"})
                    return

                if path in ("/api/network/disable", "/api/disable", "/disable"):
                    if outer.on_disable:
                        outer.on_disable()
                    self._send(202, {"ok": True, "action": "disable",
                                     "message": "已下发『禁止上网』指令"})
                    return

                # 按 IP 开单台（供学习平台：某学生完成课程后开网）
                if path in ("/api/network/enable_ip", "/api/enable_ip", "/enable_ip"):
                    ip = (query.get("ip", [""])[0] or "").strip()
                    if not ip:
                        self._send(400, {"ok": False, "error": "missing ip"})
                        return
                    if outer.on_enable_ip:
                        outer.on_enable_ip(ip)
                    self._send(202, {"ok": True, "action": "enable_ip", "ip": ip,
                                     "message": f"已下发『允许上网』指令: {ip}"})
                    return

                # 按 IP 禁单台（供学习平台：手动同步未完成学生的禁网状态）
                if path in ("/api/network/disable_ip", "/api/disable_ip", "/disable_ip"):
                    ip = (query.get("ip", [""])[0] or "").strip()
                    if not ip:
                        self._send(400, {"ok": False, "error": "missing ip"})
                        return
                    if outer.on_disable_ip:
                        outer.on_disable_ip(ip)
                    self._send(202, {"ok": True, "action": "disable_ip", "ip": ip,
                                     "message": f"已下发『禁止上网』指令: {ip}"})
                    return

                self._send(404, {"ok": False, "error": "not found", "path": path})

            # 同时支持 GET 与 POST，方便 curl / 浏览器 / 其他语言调用
            def do_GET(self):
                self._dispatch()

            def do_POST(self):
                # 读掉请求体（即便不使用），避免连接复用问题
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    try:
                        self.rfile.read(length)
                    except Exception:
                        pass
                self._dispatch()

            def do_OPTIONS(self):
                # 不下发任何 Access-Control-* 头 → 浏览器跨源预检失败，跨站脚本无法调用本接口。
                # 服务端调用方（curl / PowerShell / Python / 学习平台 exe）不受同源策略约束，不受影响。
                self.send_response(204)
                self.send_header("Allow", "GET, POST, OPTIONS")
                self.end_headers()

        return Handler
