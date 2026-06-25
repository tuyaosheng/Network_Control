"""
Windows 服务包装器 - 以 SYSTEM 权限运行被控端
安装: CTR.exe install
启动: CTR.exe start
卸载: CTR.exe remove
锁屏: CTR.exe --lock <hash>
"""
import sys
import os
import hashlib
import logging
import servicemanager
import win32event
import win32service
import win32serviceutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

SERVICE_NAME    = "NetControlAgent"
SERVICE_DISPLAY = "网络控制-被控端"
SERVICE_DESC    = "局域网网络访问控制被控端服务"

logger = logging.getLogger("service")


class AgentService(win32serviceutil.ServiceFramework):
    _svc_name_         = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY
    _svc_description_  = SERVICE_DESC
    _svc_startType_    = win32service.SERVICE_AUTO_START
    # 等 TCP/IP 栈和 DNS 客户端就绪后再启动，避免开机时网络未就绪崩溃
    _svc_deps_         = ['Tcpip', 'Dnscache']

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._agent = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        if self._agent:
            self._agent.stop()

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, "")
        )
        try:
            self._run()
        except Exception as e:
            import traceback
            err = traceback.format_exc()
            logger.error(f"服务主循环异常退出: {err}")
            servicemanager.LogErrorMsg(f"NetControlAgent 异常退出: {e}\n{err}")

    def _run(self):
        import asyncio
        from agent.main import AgentCore
        self._agent = AgentCore()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._agent.run())
        finally:
            loop.close()


def _configure_failure_recovery():
    import subprocess
    subprocess.run([
        "sc", "failure", SERVICE_NAME,
        "reset=", "86400",
        "actions=", "restart/30000/restart/30000/restart/30000"
    ], capture_output=True)
    # 立即自启（auto）：开机随其它自启服务一起启动，配合服务依赖 Tcpip/Dnscache，
    # 网络栈就绪即启，消除开机 1~2 分钟空挡（被控端启动后会立刻默认断网锁住）。
    subprocess.run([
        "sc", "config", SERVICE_NAME, "start=", "auto"
    ], capture_output=True)
    print("已配置失败自动重启策略 + 开机立即自启（auto）")


if __name__ == "__main__":
    # 锁屏模式：CTR.exe --lock <hash>
    if len(sys.argv) >= 2 and sys.argv[1] == "--lock":
        hash_val = (sys.argv[2] if len(sys.argv) > 2
                    else hashlib.sha256(b"admin123").hexdigest())
        from agent.ui.lock_screen import run_lock_screen
        run_lock_screen(hash_val)

    elif len(sys.argv) == 1:
        # SCM 分发模式
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AgentService)
        servicemanager.StartServiceCtrlDispatcher()

    else:
        win32serviceutil.HandleCommandLine(AgentService)
        if sys.argv[1].lower() == "install":
            _configure_failure_recovery()
