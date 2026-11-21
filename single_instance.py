"""单实例守卫：原子判定「我是不是唯一的那一个」，并把已经跑着的实例叫回前台。

为什么它待在仓库根、而不是 ``enm/`` 里：``enm/__init__.py`` 一被导入就会连带导入
``enm/constants.py``，而后者在**导入期**就做旧数据目录迁移、建目录等副作用。
单实例判定必须早于这些副作用（否则第二个进程在退出前已经动过共享目录了），
所以本模块只依赖标准库 + PyQt5 的 ``QtNetwork``，绝不 import ``enm``。

两道机制各司其职：

* **Win32 命名互斥体**：原子地回答「是不是已经有一个活着的实例」。互斥体归内核所有，
  进程怎么死（崩溃 / 被结束）都由内核回收，不存在需要手工清理、也可能被误留的锁文件。
  名字带 ``Local\\`` 前缀 ⇒ 作用域就是**当前登录会话**，两个用户各跑各的不互相干扰。
* **``QLocalServer`` 命名管道**：后启动的那一个靠它把「有人又点了一次」告诉先启动的实例。
  Windows 上命名管道随最后一个句柄一起消失，不会像 Unix socket 文件那样残留。

用法（顺序有讲究，见各方法注释）::

    guard = SingleInstance()
    if not guard.claim():          # 纯 ctypes，不创建任何 Qt 对象
        guard.wake_primary()       # 只能拿到 QLocalSocket，不需要 QCoreApplication
        sys.exit(0)
    app = QApplication(sys.argv)   # 互斥体判定之后才建 QApplication
    guard.serve(window.restore_and_activate)   # 管道在 QApplication 之后才开
"""

import ctypes
import sys
import time

APP_ID = "NovelMaster"

#: ``CreateMutexW`` 通过 ``GetLastError`` 报告「同名互斥体已经存在」
_ERROR_ALREADY_EXISTS = 183

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    _kernel32.CreateMutexW.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    _kernel32.CloseHandle.restype = ctypes.c_int
    _kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
    _kernel32.ProcessIdToSessionId.argtypes = (
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    )
    _kernel32.ProcessIdToSessionId.restype = ctypes.c_int
else:  # pragma: no cover - 目标平台是 Windows，其余平台走管道探活的退路
    _kernel32 = None


def session_id():
    """当前进程所在的登录会话号（拿不到就返回 0）。"""
    if not _IS_WINDOWS:
        return 0
    sid = ctypes.c_ulong(0)
    try:
        ok = _kernel32.ProcessIdToSessionId(
            _kernel32.GetCurrentProcessId(), ctypes.byref(sid)
        )
    except Exception:  # noqa: BLE001 - 取不到就当 0，不影响同会话内互斥
        return 0
    return sid.value if ok else 0


class SingleInstance:
    """单实例判定 + 唤醒通道。

    生命周期约定：一个进程只建一个，并且要活到进程退出（管道与互斥体都挂在它身上）。
    """

    def __init__(self, app_id=APP_ID):
        self.app_id = app_id
        self.is_primary = False
        self._mutex = None
        self._server = None
        self._activate = None
        self._connections = []

    # ------------------------------------------------------------------
    # 命名
    # ------------------------------------------------------------------
    def _mutex_name(self):
        # Local\ ⇒ 会话局部命名空间，天然做到「当前用户会话内唯一」
        return "Local\\%s-single-instance" % self.app_id

    def _pipe_name(self):
        # 命名管道是机器全局的，所以把会话号拼进名字，避免多用户共用一个名字。
        # （互斥体把不同用户的实例分成两拨，管道名也必须跟着分开。）
        return "%s-single-instance-%d" % (self.app_id, session_id())

    # ------------------------------------------------------------------
    # 阶段一：判定
    # ------------------------------------------------------------------
    def claim(self):
        """判定本进程是不是主实例，返回 ``True`` 表示「由我来当主实例」。

        这一步**不创建任何 Qt 对象**，因此可以安全地放在 ``QApplication``
        和数据目录迁移之前。
        """
        if _IS_WINDOWS:
            self._mutex = _kernel32.CreateMutexW(None, 0, self._mutex_name())
            if not self._mutex:
                # 连互斥体都建不出来（理论上不会发生）：宁可让人打开程序，
                # 也不要变成「双击了没反应」。
                self.is_primary = True
                return True
            self.is_primary = ctypes.get_last_error() != _ERROR_ALREADY_EXISTS
            return self.is_primary
        # 非 Windows：没有等价的原子原语，退化成「管道名字有没有人在听」
        self.is_primary = not self._pipe_alive()
        return self.is_primary

    def _pipe_alive(self):
        from PyQt5.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(self._pipe_name())
        alive = bool(sock.waitForConnected(200))
        sock.abort()
        return alive

    # ------------------------------------------------------------------
    # 阶段二：主实例开启管道（必须在 QApplication 建好之后调用）
    # ------------------------------------------------------------------
    def serve(self, activate):
        """开启命名管道；每收到一次连接就调用 ``activate()``。

        ``activate`` 就是「把窗口叫回前台」的回调。客户端连上来这一事实本身就是
        激活信号，所以这里不依赖读到的内容（收到什么都丢掉），
        命令行的转发留给以后需要时再解析。
        """
        from PyQt5.QtNetwork import QLocalServer

        self._activate = activate
        server = QLocalServer()
        # 主实例是新起的：清掉可能残留的 socket 文件（Windows 上是空操作，
        # 命名管道随进程消失，不会残留）。
        server.removeServer(self._pipe_name())
        if not server.listen(self._pipe_name()):
            server = None
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def _on_new_connection(self):
        while True:
            conn = self._server.nextPendingConnection()
            if conn is None:
                break
            self._connections.append(conn)
            conn.readyRead.connect(lambda c=conn: self._drain(c))
            conn.disconnected.connect(lambda c=conn: self._forget(c))
            self._drain(conn)
        if self._activate is not None:
            self._activate()

    def _drain(self, conn):
        try:
            conn.readAll()
        except RuntimeError:  # 连接已经被删掉了
            pass

    def _forget(self, conn):
        if conn in self._connections:
            self._connections.remove(conn)
        conn.deleteLater()

    # ------------------------------------------------------------------
    # 阶段三：从进程唤醒主实例
    # ------------------------------------------------------------------
    def wake_primary(self, timeout_ms=1500):
        """把「有人又启动了一次」告诉主实例，返回是否送达。

        主实例从 ``claim()`` 到 ``serve()`` 之间有一小段管道还没开的空隙
        （中间要建 ``QApplication``），所以这里按 ``timeout_ms`` 重试，
        既覆盖这段空隙，也覆盖「用户连点两下」的情况。
        """
        from PyQt5.QtNetwork import QLocalSocket

        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            sock = QLocalSocket()
            sock.connectToServer(self._pipe_name())
            if sock.waitForConnected(200):
                sock.write(b"activate\n")
                sock.flush()
                sock.waitForBytesWritten(300)
                sock.disconnectFromServer()
                return True
            sock.abort()
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    # ------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------
    def close(self):
        """释放命名管道与互斥体（进程正常退出时由内核兜底，这里只是干净一些）。"""
        if self._server is not None:
            try:
                self._server.close()
            except RuntimeError:
                pass
            self._server = None
        for conn in list(self._connections):
            self._forget(conn)
        if self._mutex:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None
        self.is_primary = False
