"""
通信协议定义 - 主控端与被控端之间的消息格式
"""
import json

# ── 消息类型 ─────────────────────────────────────────────────────
MSG_REGISTER        = "register"
MSG_HEARTBEAT       = "heartbeat"
MSG_STATUS          = "status"
MSG_UPDATE_RULES    = "update_rules"
MSG_GET_STATUS      = "get_status"
MSG_SET_FILTER      = "set_filter"
MSG_DISCONNECT      = "disconnect"
MSG_RECONNECT       = "reconnect"
MSG_ACK             = "ack"
MSG_BROWSING_UPDATE = "browsing_update"   # 被控端 → 主控端：DNS 查询日志

# ── 过滤模式 ─────────────────────────────────────────────────────
MODE_WHITELIST = "whitelist"
MODE_BLACKLIST = "blacklist"

# ── 网络状态 ─────────────────────────────────────────────────────
NET_NORMAL     = "normal"
NET_WHITELIST  = "whitelist"
NET_BLACKLIST  = "blacklist"
NET_DISCONNECT = "disconnect"


def make_msg(msg_type: str, **kwargs) -> str:
    return json.dumps({"type": msg_type, **kwargs}, ensure_ascii=False)


def parse_msg(raw: str) -> dict:
    return json.loads(raw)


# ── 被控端 → 主控端 ─────────────────────────────────────────────

def msg_register(hostname: str, ip: str, mac: str) -> str:
    return make_msg(MSG_REGISTER, hostname=hostname, ip=ip, mac=mac)

def msg_heartbeat(filter_active: bool, net_state: str = NET_NORMAL) -> str:
    return make_msg(MSG_HEARTBEAT, filter_active=filter_active, net_state=net_state)

def msg_status(filter_active: bool, dns_running: bool,
               rule_count: int, net_state: str = NET_NORMAL) -> str:
    return make_msg(MSG_STATUS, filter_active=filter_active,
                    dns_running=dns_running, rule_count=rule_count,
                    net_state=net_state)

def msg_browsing_update(domains: list) -> str:
    """domains: [{"domain": str, "ts": str}, ...]"""
    return make_msg(MSG_BROWSING_UPDATE, domains=domains)

def msg_ack(ok: bool, message: str = "") -> str:
    return make_msg(MSG_ACK, ok=ok, message=message)

# ── 主控端 → 被控端 ─────────────────────────────────────────────

def msg_update_rules(domains: list[str], lan_subnets: list[str],
                     controller_ip: str, upstream_dns: str,
                     mode: str = MODE_WHITELIST,
                     tray_pwd_hash: str = "",
                     unlock_pwd_hash: str = "") -> str:
    return make_msg(MSG_UPDATE_RULES,
                    domains=domains,
                    lan_subnets=lan_subnets,
                    controller_ip=controller_ip,
                    upstream_dns=upstream_dns,
                    mode=mode,
                    tray_pwd_hash=tray_pwd_hash,
                    unlock_pwd_hash=unlock_pwd_hash)

def msg_set_filter(enabled: bool, mode: str = MODE_WHITELIST) -> str:
    return make_msg(MSG_SET_FILTER, enabled=enabled, mode=mode)

def msg_disconnect() -> str:
    return make_msg(MSG_DISCONNECT)

def msg_reconnect() -> str:
    return make_msg(MSG_RECONNECT)

def msg_get_status() -> str:
    return make_msg(MSG_GET_STATUS)
