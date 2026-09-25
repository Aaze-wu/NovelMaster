# -*- coding: utf-8 -*-
"""离线神经音色模型：清单、下载、解压、删除。

神经音色（sherpa-onnx 的 Piper / Kokoro 模型）**不随安装包分发** —— 安装包会
从 40 MB 涨到 200 MB 以上。改成第一次用到时在程序里下载：

* 进度回调（字节级）+ 可取消；
* **断点续传**：没下完的存成 ``xxx.tar.bz2.part``，下次接着下（服务器支持
  ``Range`` 时只拉剩下的部分）；
* **镜像回退**：GitHub 直连不通（国内常见）时自动换镜像重试；
* 模型放在 ``%APPDATA%\\NovelMaster\\tts_models\\<model_id>\\``，随时能删。

下载来的都是 ``tar.bz2``，解开后单层目录会被「削掉」，让 ``*.onnx`` 直接躺在
``<model_id>`` 目录里，:func:`model_files` 再按文件名把 sherpa-onnx 需要的几个
路径挑出来。

这个模块只依赖标准库 + PyQt5 的 ``QObject``（给界面提供下载工作线程），
**不 import sherpa-onnx**，所以没装神经依赖时也能正常加载。
"""

import os
import queue
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple

from PyQt5.QtCore import QObject, pyqtSignal

from .. import i18n
from ..constants import DATA_PATH
from ..logger import logger

# ---------------- 模型清单 ----------------

#: 一个可下载的离线模型
#:
#: * ``model_id`` —— 本地目录名，也是语音 id 的前半段；
#: * ``engine`` —— ``vits``（Piper）/ ``kokoro``，决定怎么装配 sherpa-onnx；
#: * ``asset`` —— GitHub release 里的文件名；
#: * ``size_mb`` —— 下载体积（按实测 ``Content-Length`` 填，只用于界面显示）；
#: * ``disk_mb`` —— 解压后大约占多少（同样只用于显示）；
#: * ``voices`` —— ``(sid, 名字, locale, 性别)``；Piper 模型都是单说话人；
#: * ``note`` —— 界面上那句话的补充说明。
ModelInfo = namedtuple(
    "ModelInfo",
    "model_id engine name asset size_mb disk_mb voices license note")

#: 模型文件都从 GitHub 的 ``tts-models`` tag 下载
_RELEASE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/")

#: 直连不通时的镜像前缀。``{url}`` 会被换成上面的完整地址。
#: 顺序即尝试顺序：先直连，失败再走镜像。
MIRROR_PREFIXES = (
    "",
    "https://gh-proxy.com/",
)

#: Kokoro v1.1 的说话人共 103 个，编号是**连号**的：
#: ``0~2`` 英文女声、``3~57`` 中文女声、``58~102`` 中文男声。
#: 名字按上游的 ``zf_xxx`` / ``zm_xxx`` 规律还原（``3`` 就是 ``zf_001``）。
KOKORO_GROUPS = ((0, 2, "en", "female", "af/bf"),
                 (3, 57, "zh", "female", "zf"),
                 (58, 102, "zh", "male", "zm"))


def _kokoro_voices():
    """Kokoro 的 103 个说话人 → ``[(sid, 名字, locale, 性别), ...]``"""
    voices = []
    for start, end, _lang, gender, prefix in KOKORO_GROUPS:
        if "/" in prefix:                       # 英文区是 af_maple / af_sol / bf_vale
            english = (("af_maple", "female"), ("af_sol", "female"),
                       ("bf_vale", "female"))
            for offset, (name, sex) in enumerate(english):
                if start + offset > end:
                    break
                voices.append((start + offset, name, "en_US", sex))
            continue
        for sid in range(start, end + 1):
            voices.append((sid, f"{prefix}_{sid - start + 1:03d}",
                           "zh_CN", gender))
    return voices


#: 全部可选模型。顺序即界面顺序：小模型在前，方便「先下个小的试试」。
MODELS = (
    ModelInfo("piper-chaowen", "vits", "超文（Piper 中文小模型）",
              "vits-piper-zh_CN-chaowen-medium-int8.tar.bz2",
              13.4, 21.0,
              ((0, "超文", "zh_CN", ""),),
              "CC0 / 见模型卡",
              "音色清亮，体积最小，合成速度约为实时的 6 倍"),
    ModelInfo("piper-xiao_ya", "vits", "小雅（Piper 中文小模型）",
              "vits-piper-zh_CN-xiao_ya-medium-int8.tar.bz2",
              13.4, 21.0,
              ((0, "小雅", "zh_CN", ""),),
              "CC0 / 见模型卡",
              "超文的原始音色，语气更柔和"),
    ModelInfo("piper-huayan", "vits", "华言（Piper 中文中模型）",
              "vits-piper-zh_CN-huayan-medium.tar.bz2",
              64.1, 74.0,
              ((0, "华言", "zh_CN", ""),),
              "见模型卡",
              "体积大一些，音质比小模型更自然"),
    ModelInfo("kokoro-multi-lang", "kokoro", "Kokoro 多语言（103 个音色）",
              "kokoro-int8-multi-lang-v1_1.tar.bz2",
              140.2, 174.0,
              tuple(_kokoro_voices()),
              "Apache-2.0",
              "100 个中文（55 女 / 45 男）+ 3 个英文音色，最自然但合成较慢"),
)

#: ``model_id`` → :class:`ModelInfo`
MODEL_INDEX = {info.model_id: info for info in MODELS}


def model_info(model_id):
    """按 id 取模型信息（没有返回 ``None``）"""
    return MODEL_INDEX.get(model_id)


def models_dir():
    """模型根目录（不存在就建）``%APPDATA%\\NovelMaster\\tts_models``"""
    path = DATA_PATH / "tts_models"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.log(f"创建模型目录失败: {exc}", "ERROR")
    return path


def model_dir(model_id):
    """某个模型的目录（不一定存在）"""
    return models_dir() / model_id


def model_urls(info):
    """模型的全部下载地址（直连在前，镜像在后）"""
    url = _RELEASE + info.asset
    return [prefix + url for prefix in MIRROR_PREFIXES]


def is_installed(model_id):
    """模型是否已经下载并解压好（看关键文件在不在，不看目录存不存在）"""
    return model_files(model_id) is not None


def installed_models():
    """:data:`MODELS` 里已经装好的那些"""
    return [info for info in MODELS if is_installed(info.model_id)]


def installed_size_mb(model_id):
    """某个模型在磁盘上占多少 MB（没装返回 ``0``）"""
    total = 0
    for root, _dirs, files in os.walk(model_dir(model_id)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total / (1024.0 * 1024.0)


def model_files(model_id):
    """在模型目录里挑出 sherpa-onnx 要用的文件（缺关键文件返回 ``None``）。

    返回 ``{"model", "tokens", "lexicon", "voices", "data_dir", "dict_dir",
    "rule_fsts"}``；用不到的键是空串。``lexicon`` / ``rule_fsts`` 是多文件
    逗号拼接后的字符串（sherpa-onnx 就吃这种写法）。
    """
    root = model_dir(model_id)
    if not root.is_dir():
        return None

    onnx, tokens, lexicon, voices = [], [], [], []
    for path in _walk_files(root):
        base = os.path.basename(path).lower()
        if base.endswith(".onnx"):
            onnx.append(path)
        elif base == "tokens.txt":
            tokens.append(path)
        elif base.startswith("lexicon") and base.endswith(".txt"):
            lexicon.append(path)
        elif base == "voices.bin":
            voices.append(path)

    onnx.sort(key=lambda p: (0 if "int8" in os.path.basename(p).lower() else 1,
                             len(p)))
    lexicon.sort(key=lambda p: (0 if "en" in os.path.basename(p).lower() else 1,
                                len(p)))
    model = onnx[0] if onnx else ""
    token_file = tokens[0] if tokens else ""
    if not model or not token_file:
        return None

    data_dir = root / "espeak-ng-data"
    dict_dir = root / "dict"
    rules = [path for path in _walk_files(root)
             if os.path.basename(path).lower().endswith(".fst")
             and os.path.basename(path).lower().split(".")[0]
             in ("date", "number", "date-zh", "number-zh",
                 "date-en", "number-en")]
    rules.sort(key=lambda p: os.path.basename(p).lower())
    return {
        "model": model,
        "tokens": token_file,
        "lexicon": ",".join(lexicon),
        "voices": voices[0] if voices else "",
        "data_dir": str(data_dir) if data_dir.is_dir() else "",
        "dict_dir": str(dict_dir) if dict_dir.is_dir() else "",
        "rule_fsts": ",".join(rules),
    }


def _walk_files(root):
    for base, _dirs, files in os.walk(root):
        for name in files:
            yield os.path.join(base, name)


# ---------------- 删除 ----------------


def delete_model(model_id):
    """删掉某个模型（成功返回 ``True``）。Windows 上杀软/索引可能占文件，
    删不掉时退避重试几次。"""
    path = model_dir(model_id)
    if not path.exists():
        return True
    for attempt in range(4):
        try:
            shutil.rmtree(str(path))
            return True
        except OSError as exc:
            logger.log(f"删除模型 {model_id} 失败（第 {attempt + 1} 次）: {exc}", "WARN")
            time.sleep(0.3 * (attempt + 1))
    return not path.exists()


# ---------------- 下载 ----------------


class _Cancelled(Exception):
    """用户取消下载"""


#: 每次读多少字节写盘
_CHUNK = 256 * 1024

#: 同一个地址失败后重试几次
_RETRY = 3


def _open(url, offset=0, timeout=20):
    """发一个（可带 Range 的）GET，返回响应对象"""
    headers = {"User-Agent": "NovelMaster", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                  timeout=timeout)


def _probe(url, timeout=15):
    """探一下地址通不通（返回 ``Content-Length`` / ``Content-Range`` 里的总长）"""
    try:
        with _open(url, 0, timeout) as resp:
            if resp.status == 206:
                total = resp.headers.get("Content-Range", "").split("/")[-1]
                return int(total) if total.isdigit() else 0
            return int(resp.headers.get("Content-Length") or 0)
    except Exception as exc:  # noqa: BLE001 - 探活失败就是换个镜像
        logger.log(f"下载地址不可用（{url[:60]}…）: {exc}", "WARN")
        return -1


def _fetch(url, part, info, progress, cancel, total_hint=0):
    """从 ``url`` 续传到 ``part``，返回已下字节数与总字节数"""
    done = part.stat().st_size if part.exists() else 0
    if total_hint and done > total_hint:
        part.unlink()
        done = 0
    resp = _open(url, done)
    resumed = resp.status == 206
    if not resumed and done:
        logger.log("服务器不支持断点续传，从头下载", "WARN")
        done = 0
    length = int(resp.headers.get("Content-Length") or 0)
    total = done + length if length else total_hint
    mode = "ab" if resumed else "wb"
    if not resumed:
        part.parent.mkdir(parents=True, exist_ok=True)
    with open(str(part), mode) as handle:
        while True:
            if cancel is not None and cancel():
                raise _Cancelled()
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total, "download")
    resp.close()
    return done, total


def download_model(model_id, progress=None, status=None, cancel=None):
    """下载并解压一个模型，返回 ``(是否成功, 给用户看的结果说明)``。

    :param progress: ``progress(已下字节, 总字节, 阶段)``；阶段是 ``download`` /
    ``unpack``，总字节未知时传 ``0``
    :param status: ``status(说明文字)``，用于「正在从镜像下载 / 正在解压」
    :param cancel: ``cancel()`` 返回 ``True`` 就中断（会保留 ``.part`` 以便续传）
    """
    info = model_info(model_id)
    if info is None:
        return False, i18n.t("tts.model.unknown", default="没有这个模型。")

    if is_installed(model_id):
        return True, i18n.t("tts.model.already", default="模型已经下载好了。")

    urls = model_urls(info)
    part = models_dir() / (info.asset + ".part")
    total_hint = 0

    try:
        ordered = []
        for url in urls:
            size = _probe(url)
            if size >= 0:
                ordered.append(url)
                total_hint = max(total_hint, size)
        if not ordered:
            return False, i18n.t("tts.model.offline",
                                 default="网络不可用，下载失败。请检查网络后重试。")
        if status is not None:
            status(i18n.t("tts.model.downloading",
                          default="正在下载模型…"))

        last_error = ""
        for index, url in enumerate(ordered):
            if index:
                if status is not None:
                    status(i18n.t("tts.model.mirror", default="直连下载失败，换镜像重试…"))
                logger.log(f"改用镜像下载模型 {model_id}: {url[:60]}…", "WARN")
            for attempt in range(_RETRY):
                try:
                    done, total = _fetch(url, part, info, progress, cancel, total_hint)
                    if total and done < total:
                        raise IOError(f"只下到 {done}/{total} 字节")
                    return _unpack(info, part, progress, status, cancel)
                except _Cancelled:
                    logger.log(f"用户取消下载模型 {model_id}", "INFO")
                    return False, i18n.t("tts.model.cancelled", default="已取消下载。")
                except Exception as exc:  # noqa: BLE001 - 换地址 / 重试
                    last_error = str(exc)
                    logger.log(f"下载模型 {model_id} 出错（第 {attempt + 1} 次）: {exc}",
                               "WARN")
                    if attempt + 1 < _RETRY:
                        time.sleep(0.5 * (attempt + 1))
        return False, i18n.t("tts.model.failed",
                             default="下载失败：{error}").format(error=last_error)
    except Exception as exc:  # noqa: BLE001 - 兜底，别把异常甩给界面线程
        logger.log(f"下载模型 {model_id} 异常: {exc}", "ERROR")
        return False, i18n.t("tts.model.failed",
                             default="下载失败：{error}").format(error=exc)


def _safe_name(raw):
    """tar 里的路径 → 干净的相对路径（绝对路径 / ``..`` / 盘符一律拒掉）"""
    text = str(raw).replace("\\", "/").lstrip("/")
    parts = [item for item in text.split("/") if item not in ("", ".")]
    if any(item == ".." for item in parts):
        return ""
    if parts and ":" in parts[0]:
        return ""
    return "/".join(parts)


def _unpack(info, part, progress, status, cancel):
    """把 ``.part`` 里的 ``tar.bz2`` 解开到模型目录（单层顶层目录会被削掉）"""
    if status is not None:
        status(i18n.t("tts.model.unpacking", default="正在解压…"))
    dest = model_dir(info.model_id)
    temp = dest.parent / (".unpack-" + info.model_id)
    if temp.exists():
        shutil.rmtree(str(temp), ignore_errors=True)
    temp.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(str(part), "r:bz2") as archive:
            members = [item for item in archive.getmembers()
                       if item.isfile() or item.isdir()]
            names = [_safe_name(item.name) for item in members]
            files = [name for item, name in zip(members, names)
                     if item.isfile() and name]
            # 压缩包里通常套一层以模型名命名的目录，把它削掉，让文件直接躺在
            # 模型目录里（外层目录本身解析成空名字，会被跳过）
            strip = bool(files) and all("/" in name for name in files)
            total = sum(item.size for item in members if item.isfile()) or 1
            done = 0
            for item, name in zip(members, names):
                if cancel is not None and cancel():
                    raise _Cancelled()
                if not name:
                    continue
                if strip:
                    name = name.split("/", 1)[1] if "/" in name else ""
                if not name:
                    continue
                target = temp / name
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(item)
                if source is None:
                    continue
                with open(str(target), "wb") as handle:
                    while True:
                        chunk = source.read(512 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                        if progress is not None:
                            progress(done, total, "unpack")
    except _Cancelled:
        shutil.rmtree(str(temp), ignore_errors=True)
        return False, i18n.t("tts.model.cancelled", default="已取消下载。")
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(str(temp), ignore_errors=True)
        logger.log(f"解压模型 {info.model_id} 失败: {exc}", "ERROR")
        return False, i18n.t("tts.model.unpack_failed",
                             default="模型解压失败：{error}").format(error=exc)

    if dest.exists():
        shutil.rmtree(str(dest), ignore_errors=True)
    try:
        shutil.move(str(temp), str(dest))
    except OSError as exc:
        shutil.rmtree(str(temp), ignore_errors=True)
        logger.log(f"移动模型目录失败: {exc}", "ERROR")
        return False, i18n.t("tts.model.unpack_failed",
                             default="模型解压失败：{error}").format(error=exc)

    try:
        part.unlink()
    except OSError:
        pass

    if not is_installed(info.model_id):
        return False, i18n.t("tts.model.broken",
                             default="模型文件不完整，请删除后重新下载。")
    logger.log(f"模型 {info.model_id} 下载完成（"
               f"{installed_size_mb(info.model_id):.1f} MB）", "INFO")
    return True, i18n.t("tts.model.done", default="下载完成。")


# ---------------- 界面用的下载线程 ----------------


class ModelDownloadWorker(QObject):
    """在后台线程里下载 / 解压模型（界面只连信号，不碰文件）。

    一次只跑一个任务：模型动辄上百 MB，同时下几个只会互相抢带宽。
    """

    #: ``(model_id, 阶段, 已处理字节, 总字节)``；阶段是 ``download`` / ``unpack``
    progress = pyqtSignal(str, str, int, int)
    #: ``(model_id, 说明文字)``
    status = pyqtSignal(str, str)
    #: ``(model_id, 是否成功, 结果说明)``
    finished = pyqtSignal(str, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = queue.Queue()
        self._wake = threading.Event()
        self._cancel = threading.Event()
        self._busy = ""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop,
                                        name="NovelMaster-tts-model",
                                        daemon=True)
        self._thread.start()

    # ---------------- 对外 ----------------

    def submit(self, model_id):
        """排队下载一个模型（已经在下的会被忽略）"""
        with self._lock:
            if self._busy:
                return False
            self._busy = model_id
        self._cancel.clear()
        self._jobs.put(model_id)
        self._wake.set()
        return True

    def cancel(self, model_id=None):
        """取消当前下载（``.part`` 会留着，下次续传）"""
        with self._lock:
            if not self._busy or (model_id and model_id != self._busy):
                return False
        self._cancel.set()
        return True

    def busy(self):
        """正在下载的模型 id（空闲返回空串）"""
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
                model_id = self._jobs.get_nowait()
            except queue.Empty:
                continue
            if model_id is None:
                return
            try:
                ok, message = download_model(
                    model_id,
                    progress=lambda done, total, phase, mid=model_id:
                        self.progress.emit(mid, phase, int(done), int(total)),
                    status=lambda text, mid=model_id: self.status.emit(mid, text),
                    cancel=self._cancel.is_set)
            except Exception as exc:  # noqa: BLE001
                logger.log(f"下载线程异常: {exc}", "ERROR")
                ok, message = False, str(exc)
            with self._lock:
                self._busy = ""
            self.finished.emit(model_id, ok, message)


__all__ = ["KOKORO_GROUPS", "MIRROR_PREFIXES", "MODELS", "MODEL_INDEX",
           "ModelDownloadWorker", "ModelInfo", "delete_model",
           "download_model", "installed_models", "installed_size_mb",
           "is_installed", "model_dir", "model_files", "model_info",
           "model_urls", "models_dir"]
