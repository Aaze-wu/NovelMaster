# -*- coding: utf-8 -*-
"""检查更新：问 GitHub 要最新版本、下载安装包。

只认**正式版**。GitHub 的 ``/releases/latest`` 接口本身就跳过 draft 与
pre-release，这里仍会核一遍字段 —— 将来万一换成「列出全部 release」的接口，
不至于悄悄把 beta 当成正式版推给用户。

检查走标准库 ``urllib``；安装包交给 :mod:`enm.managers.download` 下 ——
那边会先给所有候选地址（直连 / 镜像，见 :data:`MIRROR_PREFIXES`）同时测个速，
再按实测速度决定分几条连接并发拉（国内单连接拿 GitHub release 资产常常只有
几十 KB/s，瓶颈在单连接上）：

* 支持 ``Range`` 断点续传，没下完的留成 ``xxx.exe.part`` 与
  ``xxx.exe.part.json``（分段下到哪儿记在里面），下次接着下；
* 下载可以取消，取消后 ``.part`` 也留着。

还有一条与「怎么更新」一样重要的规则：**便携版不自动下载安装包**。安装程序
装出来的是 ``Program Files`` 下的第二份，跟便携版并排躺着，用户只会以为更新
没生效。是不是安装版由 :func:`is_installed_copy` 判断（看 ``unins*.exe``），
便携版应该引导用户去发布页拿 zip。

这个模块只依赖标准库 + PyQt5 的 ``QObject`` / ``QProcess``（给界面提供后台
线程和启动安装程序），界面在 :mod:`enm.ui.update_dialog`。
"""

import json
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from .. import i18n
from ..constants import APP_ROOT, DATA_PATH, VERSION
from ..logger import logger
from .download import (CACHED, CANCELLED, MIRROR_PREFIXES, download_file,
                       mirror_urls)

# ---------------- 更新来源 ----------------

#: 更新来源仓库
REPO = "Aaze-wu/NovelMaster"
#: 仓库主页 / 发布页
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases/latest"
#: 「最新正式版」接口
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"

#: 自动检查的最小间隔（秒）。每次启动都联网问一遍太吵，同一天只问一次。
AUTO_CHECK_INTERVAL = 24 * 3600

# ---------------- 数据结构 ----------------

#: 一个可下载的发布资产
#: ``name`` 文件名 / ``url`` 下载地址 / ``size`` 字节数
ReleaseAsset = namedtuple("ReleaseAsset", "name url size")

#: 一个新版本
#: ``version`` 去掉 ``v`` 的版本号 / ``tag`` 原始标签 / ``name`` 发布标题
#: ``notes`` 更新说明（Markdown）/ ``published`` 发布日期 / ``page`` 发布页地址
#: ``installer`` 安装程序资产 / ``portable`` 便携版资产（可能为 ``None``）
UpdateInfo = namedtuple(
    "UpdateInfo",
    "version tag name notes published page installer portable")


# ---------------- 版本号 ----------------


#: 从任意文本里抠出 ``1.4.3`` 这样的数字段（``v1.4.3`` / ``1.4.3-beta.1`` 都认）
_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(text):
    """``"v1.4.3"`` / ``"1.4.3-beta.1"`` → ``(1, 4, 3)``（缺的位不补）

    返回空元组表示认不出来。位数不齐时按 Python 的元组比较规则走，
    ``(1, 4) < (1, 4, 3)`` —— 也就是 ``1.4`` 比 ``1.4.3`` 老，符合直觉。
    """
    match = _VERSION_RE.search(str(text or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.groups() if part is not None)


def is_newer(latest, current):
    """``latest`` 是不是比 ``current`` 新（认不出来的版本号一律算「不新」）

    认不出来就不提示更新，宁可漏报也别把用户引到错误的下载上。
    """
    candidate = parse_version(latest)
    if not candidate:
        return False
    return candidate > parse_version(current)


# ---------------- 运行环境 ----------------


def _frozen():
    """是不是打包后的可执行文件（Nuitka）"""
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def is_installed_copy():
    """当前跑的是不是 Inno 装出来的版本。

    判据是可执行文件所在目录里有没有 Inno 生成的 ``unins*.exe``：安装版有，
    便携版（zip 解压）与源码运行都没有。便携版不该自动下载安装包 ——
    装出来是 ``Program Files`` 下的另一份，用户会以为更新没生效。
    """
    if not _frozen():
        return False
    try:
        return any(APP_ROOT.glob("unins*.exe"))
    except OSError:
        return False


def update_dir():
    """安装包下载到这里（不存在就建）``%APPDATA%\\NovelMaster\\update``

    放数据目录而不是 ``%TEMP%``：下到一半的 ``.part`` 能被下次启动接着用，
    也不会被系统清理工具顺手删掉。
    """
    path = DATA_PATH / "update"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.log(f"创建更新目录失败: {exc}", "ERROR")
    return path


# ---------------- 检查 ----------------


def _fetch_json(url, timeout=15):
    """GET 一个 JSON 接口（GitHub 强制要求 ``User-Agent``）"""
    request = urllib.request.Request(url, headers={
        "User-Agent": "NovelMaster",
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _pick_assets(raw_assets):
    """从发布资产里挑出安装程序与便携版 ``(installer, portable)``"""
    installer = portable = None
    for item in raw_assets or ():
        name = str(item.get("name") or "")
        url = str(item.get("browser_download_url") or "")
        if not name or not url:
            continue
        asset = ReleaseAsset(name, url, int(item.get("size") or 0))
        lower = name.lower()
        if lower.endswith(".exe"):
            installer = asset
        elif lower.endswith(".zip"):
            portable = asset
    return installer, portable


def check_for_update(current=VERSION, timeout=15):
    """检查有没有新版本。

    返回 ``(状态, 结果)``，状态取值：

    * ``"update"`` —— 有新版本，结果是 :class:`UpdateInfo`
    * ``"latest"`` —— 已经是最新（结果是 ``None``）
    * ``"error"`` —— 检查失败，结果是给用户看的一句话
    """
    try:
        data = _fetch_json(LATEST_API, timeout)
    except urllib.error.HTTPError as exc:
        logger.log(f"检查更新失败: HTTP {exc.code}", "WARN")
        if exc.code == 404:
            return "error", i18n.t("update.no_release",
                                   default="发布页上还没有正式版本。")
        if exc.code == 403:
            return "error", i18n.t(
                "update.rate_limited",
                default="GitHub 接口暂时拒绝访问（同一出口 IP 请求过多），"
                        "请稍后再试。")
        return "error", i18n.t("update.check_failed",
                               default="检查更新失败：{error}",
                               error=f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 - 断网 / 超时 / DNS 失败都走这里
        logger.log(f"检查更新失败: {exc}", "WARN")
        return "error", i18n.t(
            "update.offline",
            default="网络不可用，检查更新失败。请检查网络后重试。")

    # 接口本该只返回正式版，这里再核一遍，免得接口换了以后把 beta 推出去
    if data.get("draft") or data.get("prerelease"):
        logger.log("最新的 release 是草稿或预发布版，按「已是最新」处理", "WARN")
        return "latest", None

    tag = str(data.get("tag_name") or "")
    if not is_newer(tag, current):
        return "latest", None

    parts = parse_version(tag)
    version = ".".join(str(part) for part in parts) or tag.lstrip("v")
    installer, portable = _pick_assets(data.get("assets"))
    info = UpdateInfo(
        version,
        tag,
        str(data.get("name") or f"NovelMaster {version}"),
        str(data.get("body") or ""),
        str(data.get("published_at") or ""),
        str(data.get("html_url") or RELEASES_URL),
        installer,
        portable)
    logger.log(f"发现新版本 {version}（当前 {current}）", "INFO")
    return "update", info


# ---------------- 自动检查的节流 ----------------


def should_auto_check(last_check):
    """距离上次自动检查是否已经超过 :data:`AUTO_CHECK_INTERVAL`"""
    try:
        elapsed = time.time() - float(last_check or 0)
    except (TypeError, ValueError):
        return True
    return elapsed >= AUTO_CHECK_INTERVAL


# ---------------- 下载 ----------------

#: 给界面看的状态文案：:mod:`enm.managers.download` 只递代码，这里翻成人话
_STATUS_TEXTS = {
    "probing": ("update.probing", "正在测速，挑个最快的下载地址…"),
    "connections": ("update.connections", "正在用 {count} 个连接下载…"),
    "resume": ("update.resume", "接着上次下到的地方继续…"),
    "no_segments": ("update.no_segments",
                    "这个地址不支持分段下载，已改用单连接。"),
    "mirror": ("update.mirror", "直连下载失败，换镜像重试…"),
    "proxy_off": ("update.proxy_off", "代理连不通，已丢掉代理直连重试…"),
}


def _status_text(code, **kwargs):
    """状态代码 → 给用户看的话；认不出来的代码返回空串"""
    key, default = _STATUS_TEXTS.get(code, ("", ""))
    if not key:
        return ""
    return i18n.t(key, default=default, **kwargs)


def _download_status(status):
    """把界面的 ``status(文案)`` 包成下载引擎要的 ``status(代码, **参数)``"""
    if status is None:
        return None
    return lambda code, **kwargs: status(_status_text(code, **kwargs))


def download_installer(url, dest, custom_mirror="", expected=0, progress=None,
                       status=None, cancel=None):
    """把安装包下到 ``dest``，返回 ``(是否成功, 说明文字, 文件路径)``。

    真正下载的是 :func:`enm.managers.download.download_file`（竞速挑地址 +
    多连接分段 + 分段续传）；这里只把它给出的结果翻成界面看的话。

    :param expected: GitHub 报的文件大小，用来认出「下完了但对不上」的残缺文件
    :param progress: ``progress(已下字节, 总字节)``（总字节未知时是 0）
    :param status: ``status(说明文字)``，用于「测速 / 换地址」这类进度之外的提示
    :param cancel: ``cancel()`` 返回 ``True`` 就中断（``.part`` 留着续传）
    """
    result = download_file(url, dest,
                           custom_mirror=custom_mirror,
                           expected=expected,
                           progress=progress,
                           status=_download_status(status),
                           cancel=cancel)

    if result.ok and result.reason == CACHED:
        message = i18n.t("update.down_cached", default="安装包已经下载好了。")
    elif result.reason == CANCELLED:
        message = i18n.t("update.cancelled", default="已取消下载。")
    elif result.ok:
        message = i18n.t("update.down_done", default="安装包下载完成。")
    else:
        message = i18n.t("update.down_failed",
                         default="下载失败：{error}",
                         error=result.error or "未知错误")
    return result.ok, message, result.path


# ---------------- 启动安装程序 ----------------


def launch_installer(path):
    """启动安装程序，返回是否成功（调用方随后要退出自己）。

    ``/CLOSEAPPLICATIONS`` 让安装程序顺手关掉还占着文件的进程；正常情况下
    我们已经退干净了，这是保险。用 ``startDetached`` 是为了让安装程序不受
    我们的进程树约束 —— 我们马上就退，它得接着跑完。
    """
    try:
        started = QProcess.startDetached(str(path), ["/CLOSEAPPLICATIONS"])
    except Exception as exc:  # noqa: BLE001
        logger.log(f"启动安装程序失败: {exc}", "ERROR")
        return False
    # PyQt5 的不同小版本这里返回 bool 或 (bool, pid)
    if isinstance(started, tuple):
        started = started[0]
    if not started:
        logger.log("启动安装程序失败：startDetached 返回 False", "ERROR")
        return False
    logger.log(f"已启动安装程序，准备退出: {Path(path).name}", "INFO")
    return True


# ---------------- 界面用的后台线程 ----------------


class UpdateWorker(QObject):
    """在后台线程里检查 / 下载（界面只连信号，不碰网络）。

    一次跑一个任务：下载动辄几十 MB，跟检查更新并发没有意义，排队反而更好
    预测 —— 自动检查刚跑完、用户紧接着点「检查更新」时，第二个请求会等在
    队列里，而不是两份结果互相覆盖。
    """

    #: ``(状态, 结果)``。状态 ``update`` / ``latest`` / ``error``；
    #: ``update`` 时结果是 :class:`UpdateInfo`，其余是给用户看的说明
    checked = pyqtSignal(str, object)
    #: ``(已下字节, 总字节, 速度 KB/s)``。总字节未知时是 0
    progress = pyqtSignal(int, int, float)
    #: ``(是否成功, 说明文字, 文件路径)``
    downloaded = pyqtSignal(bool, str, str)
    #: 过程中的说明（换镜像重试等）
    status = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = queue.Queue()
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._busy = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop,
                                        name="NovelMaster-update",
                                        daemon=True)
        self._thread.start()

    # ---------------- 对外 ----------------

    def submit_check(self):
        """排队检查更新（已经有任务在跑就不排）

        检查走直连的 GitHub API，不套镜像：常见的加速前缀只代理文件下载，
        拿它去套 API 只会白白多等一轮超时。
        """
        return self._submit("check")

    def submit_download(self, url, dest, expected=0, mirror=""):
        """排队下载安装包"""
        return self._submit("download", url, dest, expected, mirror)

    def _submit(self, kind, *payload):
        with self._lock:
            if self._busy:
                return False
            self._busy = kind
        self._cancel.clear()
        self._jobs.put((kind, payload))
        self._wake.set()
        return True

    def cancel(self):
        """取消正在跑的任务（下载会留下 ``.part``）"""
        with self._lock:
            if not self._busy:
                return False
        self._cancel.set()
        return True

    def busy(self):
        """正在跑的任务类型（空闲返回空串）"""
        with self._lock:
            return self._busy

    def shutdown(self):
        """退出线程（关窗口时调用）"""
        self._cancel.set()
        self._jobs.put(None)
        self._wake.set()
        self._thread.join(timeout=3.0)

    # ---------------- 线程 ----------------

    def _loop(self):
        while True:
            if self._jobs.empty():
                self._wake.wait()
                self._wake.clear()
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                continue
            if job is None:
                return

            kind, payload = job
            try:
                if kind == "check":
                    state, result = check_for_update()
                    self.checked.emit(state, result)
                else:
                    self._run_download(*payload)
            except Exception as exc:  # noqa: BLE001 - 兜底，别把异常甩给界面线程
                logger.log(f"更新线程异常: {exc}", "ERROR")
                if kind == "check":
                    self.checked.emit("error", i18n.t(
                        "update.check_failed",
                        default="检查更新失败：{error}").format(error=exc))
                else:
                    self.downloaded.emit(False, i18n.t(
                        "update.down_failed",
                        default="下载失败：{error}").format(error=exc), "")
            finally:
                with self._lock:
                    self._busy = ""

    def _run_download(self, url, dest, expected, mirror):
        started = time.time()

        def on_progress(done, total):
            elapsed = max(time.time() - started, 1e-3)
            self.progress.emit(int(done), int(total),
                               done / 1024.0 / elapsed)

        ok, message, path = download_installer(
            url, dest,
            custom_mirror=mirror,
            expected=expected,
            progress=on_progress,
            status=lambda text: self.status.emit(text),
            cancel=self._cancel.is_set)
        self.downloaded.emit(ok, message, str(path) if ok else "")


__all__ = ["AUTO_CHECK_INTERVAL", "LATEST_API", "MIRROR_PREFIXES",
           "RELEASES_URL", "REPO", "REPO_URL", "ReleaseAsset", "UpdateInfo",
           "UpdateWorker", "check_for_update", "download_installer",
           "is_installed_copy", "is_newer", "launch_installer", "mirror_urls",
           "parse_version", "should_auto_check", "update_dir"]
