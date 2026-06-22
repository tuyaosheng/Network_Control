"""
Windows 防火墙管理
使用 PowerShell New-NetFirewallRule / Remove-NetFirewallRule
防绕过策略：
  1. 封锁外部 DNS（防止学生换 DNS 绕过）
  2. 将网卡 DNS 强制设为 127.0.0.1
  3. 封锁所有出站（Internet），仅放行白名单 IP + 局域网 + 主控端
"""
import json
import os
import subprocess
import socket
import threading
import time
import logging
import ipaddress
from typing import Optional

logger = logging.getLogger("firewall")

RULE_PREFIX = "NC_"   # 所有规则名称前缀，便于批量清理


def _run_ps(cmd: str, timeout: int = 15) -> tuple[bool, str]:
    result = subprocess.run(
        ["powershell", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    ok = result.returncode == 0
    out = (result.stdout + result.stderr).strip()
    if not ok:
        logger.debug(f"PS命令失败: {cmd[:200]}\n{out}")
    return ok, out


def _ps_addr(addr: str) -> str:
    """
    把地址参数转成 PowerShell 形式：
      单个   -> "127.0.0.0/8"
      多个   -> "1.2.3.4","5.6.7.8"   （逗号分隔会拆成数组）
    """
    if "," in addr:
        parts = [p.strip() for p in addr.split(",") if p.strip()]
        return ",".join(f'"{p}"' for p in parts)
    return f'"{addr}"'


def _add_rule(name: str, direction: str, protocol: str,
              remote_addr: str = "Any", remote_port: str = "Any",
              local_port: str = "Any", action: str = "Allow") -> bool:
    full_name = RULE_PREFIX + name
    # 先删已有同名规则
    _run_ps(f'Remove-NetFirewallRule -DisplayName "{full_name}" -ErrorAction SilentlyContinue')
    cmd = (
        f'New-NetFirewallRule -DisplayName "{full_name}" '
        f'-Direction {direction} -Protocol {protocol} '
        f'-RemoteAddress {_ps_addr(remote_addr)} '
        f'-RemotePort "{remote_port}" '
        f'-LocalPort "{local_port}" '
        f'-Action {action} -Enabled True -Profile Any'
    )
    ok, out = _run_ps(cmd)
    if ok:
        logger.debug(f"规则已添加: {full_name}")
    else:
        logger.warning(f"规则添加失败: {full_name} -> {out}")
    return ok


def _set_default_outbound(action: str) -> bool:
    """
    设置防火墙默认出站策略。action = "Block" 或 "Allow"
    白名单/断网模式靠"默认封锁 + 只放行白名单"实现，
    因为 Windows 防火墙中封锁规则优先级高于放行规则，
    不能用"放行白名单 + 封锁全部"的写法（白名单会被一起封掉）。
    """
    cmd = f'Set-NetFirewallProfile -All -DefaultOutboundAction {action}'
    ok, out = _run_ps(cmd)
    if ok:
        logger.info(f"防火墙默认出站策略已设为: {action}")
    else:
        logger.warning(f"设置默认出站策略失败: {out}")
    return ok


def remove_all_rules():
    """恢复默认放行，并清除所有 NC_ 规则"""
    _set_default_outbound("Allow")
    cmd = f'Get-NetFirewallRule | Where-Object {{$_.DisplayName -like "{RULE_PREFIX}*"}} | Remove-NetFirewallRule -ErrorAction SilentlyContinue'
    ok, out = _run_ps(cmd)
    logger.info("已清除所有 NC_ 防火墙规则，默认出站已恢复")
    return ok


def resolve_domain_ips(domain: str) -> list[str]:
    """解析域名得到 IP 列表"""
    domain = domain.lstrip("*.").strip()
    try:
        infos = socket.getaddrinfo(domain, None)
        ips = list({info[4][0] for info in infos
                    if ":" not in info[4][0]})  # 只取 IPv4
        return ips
    except Exception:
        return []


def _add_common_allow_rules(lan_subnets: list[str], controller_ip: str):
    """添加所有模式都需要的放行规则：回环 + 局域网 + 主控端"""
    # 放行回环
    _add_rule("Allow_Loopback", "Outbound", "Any", remote_addr="127.0.0.0/8")

    # 放行局域网（保障内网通信不受影响）
    for subnet in lan_subnets:
        safe_name = subnet.replace("/", "_").replace(".", "_")
        _add_rule(f"Allow_LAN_{safe_name}", "Outbound", "Any", remote_addr=subnet)

    # 放行主控端（WebSocket 通信，主控端若在局域网内其实已被上面覆盖）
    if controller_ip:
        _add_rule("Allow_Controller", "Outbound", "Any", remote_addr=controller_ip)


def apply_whitelist_rules(whitelist_domains: list[str],
                          lan_subnets: list[str],
                          controller_ip: str,
                          upstream_dns: str):
    """
    应用白名单防火墙规则（默认封锁出站 + 只放行白名单）：
      - 放行回环 / 局域网 / 主控端
      - 解析白名单域名 IP 并放行
      - 放行上游 DNS（供本地 DNS 服务器转发查询用）
      - 默认出站策略设为封锁，其余 Internet 流量自动被拦
    """
    logger.info("开始应用白名单防火墙规则...")
    remove_all_rules()   # 先恢复默认放行 + 清空旧规则

    _add_common_allow_rules(lan_subnets, controller_ip)

    # 解析白名单域名 IP 并放行
    whitelist_ips: set[str] = set()
    for domain in whitelist_domains:
        bare = domain.lstrip("*").lstrip(".").strip()
        if not bare:
            continue
        ips = resolve_domain_ips(bare)
        whitelist_ips.update(ips)
        logger.debug(f"域名 {bare} 解析到 {ips}")

    if whitelist_ips:
        ip_list = ",".join(sorted(whitelist_ips))
        _add_rule("Allow_Whitelist_IPs", "Outbound", "Any", remote_addr=ip_list)
        logger.info(f"已放行 {len(whitelist_ips)} 个白名单 IP")

    # 放行上游 DNS（本地 DNS 服务器需要向它转发白名单域名查询）
    if upstream_dns:
        _add_rule("Allow_UpstreamDNS", "Outbound", "UDP",
                  remote_addr=upstream_dns, remote_port="53")

    # 默认出站封锁——上面没放行的 Internet 流量全部被拦
    _set_default_outbound("Block")

    logger.info("白名单防火墙规则应用完成")


def apply_disconnect_rules(lan_subnets: list[str], controller_ip: str):
    """已废弃，保留兼容。断网逻辑已移至 disconnect_internet()。"""
    logger.warning("apply_disconnect_rules() 已废弃，请使用 disconnect_internet()")
    disconnect_internet()


# ── 路由表断网（替代防火墙默认策略方案）──────────────────────────────────

_GW_BACKUP_FILE: str = ""  # 由 main.py 初始化后设置，或用模块级变量延迟设置


def _gw_backup_path() -> str:
    global _GW_BACKUP_FILE
    if not _GW_BACKUP_FILE:
        # 与 shared.paths 同逻辑，避免循环导入
        import sys
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _GW_BACKUP_FILE = os.path.join(base, "gw_backup.json")
    return _GW_BACKUP_FILE


def _get_default_gateways() -> list[dict]:
    """返回所有默认路由条目（NextHop + InterfaceIndex + RouteMetric）。"""
    cmd = (
        'Get-NetRoute -DestinationPrefix "0.0.0.0/0" '
        '| Select-Object NextHop, InterfaceIndex, RouteMetric '
        '| ConvertTo-Json -Compress'
    )
    ok, out = _run_ps(cmd)
    if not ok or not out.strip():
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        logger.debug(f"解析默认路由失败: {e} raw={out[:200]}")
        return []


def _ps_metric_arg(metric) -> str:
    """RouteMetric=0 表示 Windows 自动跃点，New-NetRoute 部分版本拒绝 0，省略以使用默认值。"""
    try:
        m = int(metric)
    except (TypeError, ValueError):
        return ""
    return f"-RouteMetric {m}" if m > 0 else ""


_whitelist_host_routes: set[str] = set()   # 记录已添加的白名单主机路由，用于清理
_cached_gateway: tuple[str, int] = ("", 0)  # 白名单模式下默认路由被删后用于动态添加主机路由的网关
_dynamic_routes_lock = threading.Lock()     # 保护并发写路由表


def _clean_whitelist_routes():
    """批量移除之前通过 apply_whitelist_routing/add_host_routes_dynamic 添加的所有 /32 主机路由。"""
    global _whitelist_host_routes, _cached_gateway
    with _dynamic_routes_lock:
        if not _whitelist_host_routes:
            _cached_gateway = ("", 0)
            return
        ips = list(_whitelist_host_routes)
        _whitelist_host_routes.clear()
        _cached_gateway = ("", 0)

    # 批量删除，避免一次开几百个 PowerShell 进程
    parts = [
        f'try {{ Remove-NetRoute -DestinationPrefix "{ip}/32" -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}};'
        for ip in ips
    ]
    script = " ".join(parts)
    _run_ps(script, timeout=60)
    logger.debug(f"已清除 {len(ips)} 条白名单主机路由")


def add_host_routes_dynamic(ips: list[str]) -> set[str]:
    """
    运行时把上游 DNS 返回的 IP 加进白名单路由表。
    由 DNS 服务器（dns_server.FilterResolver）在每次解析白名单域名后调用。

    返回本次新增的 IP（已去重过）。已存在的 IP 跳过，避免重复 PowerShell 调用。
    """
    global _whitelist_host_routes, _cached_gateway
    with _dynamic_routes_lock:
        gw_ip, gw_idx = _cached_gateway
        if not gw_ip:
            return set()
        new_ips = [ip for ip in ips if ip and ip not in _whitelist_host_routes]
        if not new_ips:
            return set()
        # 提前占位，防止并发查询重复添加
        _whitelist_host_routes.update(new_ips)

    added = _add_host_routes_bulk(new_ips, gw_ip, gw_idx)
    failed = set(new_ips) - added
    if failed:
        # 失败的从已记录集合里撤回，下次可以重试
        with _dynamic_routes_lock:
            _whitelist_host_routes.difference_update(failed)
    if added:
        logger.debug(f"动态添加主机路由 {len(added)} 条: {sorted(added)[:5]}{'...' if len(added) > 5 else ''}")
    return added


def _delete_default_route() -> bool:
    """
    只删除默认路由 + 备份网关。不动 whitelist 主机路由，也不动 _cached_gateway。
    供白名单模式建立时使用：Phase 2 已经设好基线路由和 _cached_gateway，
    Phase 3 要保留这些，仅删除默认路由让流量必须走主机路由。
    """
    gateways = _get_default_gateways()
    if not gateways:
        return True  # 已无默认路由，视为成功

    try:
        with open(_gw_backup_path(), "w", encoding="utf-8") as f:
            json.dump(gateways, f)
        logger.debug(f"网关信息已保存: {gateways}")
    except Exception as e:
        logger.warning(f"保存网关信息失败: {e}")

    ok, out = _run_ps('route DELETE 0.0.0.0 MASK 0.0.0.0')
    if ok:
        logger.info(f"已删除默认路由（共 {len(gateways)} 条），互联网已断开，局域网保留")
    else:
        logger.warning(f"删除默认路由失败: {out}")
    return ok


def disconnect_internet() -> bool:
    """
    彻底断网（用于状态切换：→ disconnect / → blacklist / → normal 前）：
    清理 whitelist 主机路由 + 删除默认路由。
    """
    _clean_whitelist_routes()   # 状态切换时才清理白名单路由
    return _delete_default_route()


def reconnect_internet() -> bool:
    """
    恢复默认网关路由，重新接入互联网。
    优先读取保存的网关文件；文件不存在则尝试 DHCP 续约。
    """
    _clean_whitelist_routes()   # 确保白名单主机路由已清理

    # 若默认路由已存在（如重复调用），直接返回，避免触发 DHCP 续约清空手动 DNS
    if _get_default_gateways():
        logger.info("默认路由已存在，无需恢复")
        return True

    backup = _gw_backup_path()
    if os.path.exists(backup):
        try:
            with open(backup, "r", encoding="utf-8") as f:
                gateways = json.load(f)
        except Exception as e:
            logger.warning(f"读取网关备份失败: {e}，将尝试 DHCP 续约")
            gateways = []
    else:
        gateways = []

    if gateways:
        success = True
        for gw in gateways:
            nh     = gw.get("NextHop", "")
            idx    = gw.get("InterfaceIndex", 0)
            metric = gw.get("RouteMetric", 0)   # Windows 自动跃点时为 0
            if not nh or nh in ("0.0.0.0", "::", ""):
                continue
            # 先删同接口的旧默认路由（幂等），再用 New-NetRoute 添加
            _run_ps(
                f'Remove-NetRoute -DestinationPrefix "0.0.0.0/0" '
                f'-InterfaceIndex {idx} -Confirm:$false -ErrorAction SilentlyContinue'
            )
            metric_arg = _ps_metric_arg(metric)
            ok, out = _run_ps(
                f'New-NetRoute -DestinationPrefix "0.0.0.0/0" '
                f'-NextHop "{nh}" -InterfaceIndex {idx} '
                f'{metric_arg} -ErrorAction Stop'
            )
            if ok:
                logger.info(f"已恢复默认路由: {nh} (IF {idx})")
            else:
                logger.warning(f"恢复路由失败: {out}")
                success = False
        # 验证：路由表中确实存在默认路由
        verify = _get_default_gateways()
        if verify:
            logger.info(f"路由表已确认存在 {len(verify)} 条默认路由")
        else:
            logger.warning("恢复后路由表中仍无默认路由！")
            success = False
        if success:
            try:
                os.remove(backup)
            except Exception:
                pass
        else:
            logger.warning("部分路由恢复失败，保留备份文件以供下次重试")
        return success
    else:
        # 兜底：触发 DHCP 续约让系统重新获取网关
        logger.info("无网关备份，尝试 DHCP 续约恢复路由...")
        ok, out = _run_ps(
            'Get-NetAdapter | Where-Object {$_.Status -eq "Up" -and $_.Name -notmatch "Loopback"} '
            '| ForEach-Object { ipconfig /renew $_.Name }'
        )
        return ok


def apply_whitelist_routing(whitelist_domains: list[str],
                             lan_subnets: list[str],
                             controller_ip: str,
                             upstream_dns: str) -> bool:
    """
    路由表白名单（动态加路由方案）：
      Phase 1: 确保默认路由存在（必要时 reconnect_internet 恢复）
      Phase 2: 缓存网关 → 加基线路由（upstream_dns + controller_ip）
               → 切网卡 DNS 到 127.0.0.1 → 删默认路由
      Phase 3: 不再预解析所有域名。后续 DNS 查询会由 dns_server 实时调用
               add_host_routes_dynamic 把上游返回的 IP 加进路由表。

    这样 CDN 每次返回不同 IP 都能跟得上，浏览器拿到的 IP 一定在路由表里。
    """
    global _whitelist_host_routes, _cached_gateway
    logger.info("配置路由表白名单（动态模式）...")

    _clean_whitelist_routes()

    # ── Phase 1: 确保默认路由可用（建基线路由需要它） ────────────────
    if not _get_default_gateways():
        logger.info("当前无默认路由，先恢复网络以便建基线路由")
        if not reconnect_internet():
            logger.error("默认路由恢复失败，白名单配置中止")
            return False
        time.sleep(0.5)

    gateways = _get_default_gateways()
    if not gateways:
        logger.error("默认路由恢复后仍不存在，白名单配置失败")
        return False

    gw     = gateways[0]
    gw_ip  = gw.get("NextHop", "")
    gw_idx = gw.get("InterfaceIndex", 0)
    if not gw_ip or gw_ip in ("0.0.0.0", "::", ""):
        logger.error(f"无效网关 IP '{gw_ip}'，白名单配置失败")
        return False

    # ── Phase 2: 加基线主机路由（DNS 转发需要能连上游 DNS） ──────────
    set_adapter_dns("127.0.0.1")

    baseline: set[str] = set()
    if upstream_dns:
        baseline.add(upstream_dns)
    if controller_ip:
        baseline.add(controller_ip)

    added = _add_host_routes_bulk(sorted(baseline), gw_ip, gw_idx)
    logger.info(f"基线主机路由已添加 {len(added)}/{len(baseline)} 条（上游 DNS + 主控端）")

    # 把网关信息缓存起来，供后续 dns_server 动态加路由使用
    with _dynamic_routes_lock:
        _whitelist_host_routes = set(added)
        _cached_gateway = (gw_ip, gw_idx)

    # ── Phase 3: 仅删默认路由（绝不动刚加的基线路由 & _cached_gateway）──
    _delete_default_route()

    _run_ps('Clear-DnsClientCache -ErrorAction SilentlyContinue')
    logger.info(f"路由表白名单就绪：基线 {len(added)} IP，余下按 DNS 查询动态添加")
    return True


def _add_host_routes_bulk(ips: list[str], gw_ip: str, gw_idx: int) -> set[str]:
    """批量添加 /32 主机路由（一次 PS 调用，减少总耗时）。"""
    if not ips:
        return set()
    # 构造一条 PowerShell 脚本，包含所有 Remove+New 操作
    parts = []
    for ip in ips:
        parts.append(
            f'try {{ Remove-NetRoute -DestinationPrefix "{ip}/32" -Confirm:$false -ErrorAction SilentlyContinue }} catch {{}};'
            f'try {{ New-NetRoute -DestinationPrefix "{ip}/32" -NextHop "{gw_ip}" '
            f'-InterfaceIndex {gw_idx} -RouteMetric 1 -ErrorAction Stop | Out-Null; '
            f'Write-Output "OK {ip}" }} catch {{ Write-Output "FAIL {ip} $($_.Exception.Message)" }};'
        )
    script = " ".join(parts)
    # 一次最多处理几百条路由，给充足超时
    ok, out = _run_ps(script, timeout=120)
    added: set[str] = set()
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("OK "):
            added.add(line[3:].strip())
        elif line.startswith("FAIL "):
            logger.warning(f"主机路由失败: {line[5:][:120]}")
    return added


def set_adapter_dns(dns_ip: str = "127.0.0.1"):
    """将活动网卡的 DNS 改为本地 DNS 服务器（只设一个，避免回退到外部 DNS）"""
    cmd = (
        'Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | ForEach-Object {'
        f'Set-DnsClientServerAddress -InterfaceAlias $_.Name -ServerAddresses "{dns_ip}"'
        '}'
    )
    ok, out = _run_ps(cmd)
    if ok:
        logger.info(f"网卡 DNS 已设置为 {dns_ip}")
    else:
        logger.warning(f"设置网卡 DNS 失败: {out}")
    return ok


def restore_adapter_dns():
    """恢复网卡为自动获取 DNS（DHCP）"""
    cmd = (
        'Get-NetAdapter | Where-Object {$_.Status -eq "Up"} | ForEach-Object {'
        'Set-DnsClientServerAddress -InterfaceAlias $_.Name -ResetServerAddresses'
        '}'
    )
    ok, out = _run_ps(cmd)
    if ok:
        logger.info("网卡 DNS 已恢复为自动获取")
    else:
        logger.warning(f"恢复网卡 DNS 失败: {out}")
    return ok
