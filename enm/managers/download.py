# -*- coding: utf-8 -*-
"""多连接分段下载。

单条 TCP 连接在国内拿 GitHub release 资产（Azure 前置 CDN）和各类加速镜像
（Cloudflare Worker）时常年几十到几百 KB/s —— 瓶颈在单连接，不在带宽。这里
把文件切成若干字节区间并发下：一条连接一段，各自写进 ``xxx.exe.part`` 的对应
偏移（同一个文件，互不重叠的区间），每段下到哪儿记在 ``xxx.exe.part.json``
里，中断后照着它接着下。

一趟下载分三步：

1. **竞速**：对每个候选地址（直连 → 内置镜像 → 用户自定义前缀，见
   :func:`mirror_urls`）同时发一个 ``Range: bytes=0-<探测上限-1>`` 的请求，
   读满一小段时间就掐掉，谁读到的字节多谁快。直连「不报错但龟速」时不必白
   等一轮失败再换镜像。
2. **定并发**：竞速本身就给出了速度，据此决定分几段。已经够快就老实一条连接
   下完 —— 分段不是白给的：多次握手、对服务器也更凶。
3. **分段下**：剩下的交给 N 条线程，谁空谁上；某段出错就重试，整趟不行就换
   下一个候选地址，进度还留着，接着下。

代理不用自己读注册表：Windows 上 ``urllib.request.getproxies()`` 本来就会从
环境变量回落到「Internet 选项」里的设置（``ProxyEnable`` / ``ProxyServer`` /
``ProxyOverride``）。只有整条路都走不通时，才丢掉代理直连重来一遍。

本模块只用标准库，不碰 Qt、不碰 i18n：给界面看的话由
:func:`~enm.managers.update.download_installer` 翻译（``status`` 回调收到的是
``(代码, 参数)``，不是成品文案）。
"""

import json
import math
import threading
import time
import urllib.request
from collections import namedtuple
from pathlib import Path

from ..logger import logger

#: 候选地址前缀：第一个是直连，后面是内置镜像；用户自定义的前缀接在最后
MIRROR_PREFIXES = (
    "",
    "https://gh-proxy.com/",
)

#: 正常下载时一次读多少字节写盘
READ_CHUNK = 256 * 1024

#: 正常下载的超时（秒）。这是「一次 recv 最多等多久」，不是整趟下载的上限
TIMEOUT = 20

#: 竞速探测：最多读多久、最多读多少字节、等最慢的那个多久
PROBE_WINDOW = 1.0
PROBE_MAX_BYTES = 1536 * 1024
PROBE_GRACE = 0.8
PROBE_TIMEOUT = 12
#: 一个地址都没按时收工时再多等一会儿（给「建连慢但确实活着」的地址留点机会）
PROBE_SLOW = 5.0

#: 单连接跑得比这快就不分段了（多半是直连没被卡）
FAST_SPEED = 4 * 1024 * 1024
#: 分段时想凑到的总速度；用它除以实测速度就是想要的连接数
TARGET_SPEED = 8 * 1024 * 1024
#: 连接数上限
MAX_CONNECTIONS = 16
#: 一段至少多大；比这还小的文件不值得切
MIN_SEGMENT = 1024 * 1024
#: 同一段下载失败重试几次
SEGMENT_RETRY = 3
#: 候选地址列表整个重来几轮
_ROUNDS = 3

#: 进度文件的版本与后缀（挂在 ``xxx.exe.part`` 后面，即 ``xxx.exe.part.json``）
META_VERSION = 1
META_SUFFIX = ".json"

#: 结果里的 ``reason``
DONE = "done"
CACHED = "cached"
CANCELLED = "cancelled"
FAILED = "failed"

#: :func:`download_file` 的返回值
DownloadResult = namedtuple(
    "DownloadResult", "ok reason error path total connections mirror speed")


class DownloadCancelled(Exception):
    """用户点了取消（进度留着，下次接着下）"""


class DownloadFailed(Exception):
    """下载失败；``str()`` 可以直接塞进「下载失败：{error}」给用户看"""


# ---------------- 地址 ----------------


def mirror_urls(url, custom=""):
    """一个地址的全部候选：直连 → 内置镜像 → 用户自定义的镜像前缀

    用户填的前缀排最后：内置的能用就不必麻烦他填的那个（自定义多半是某个专门
    的加速服务，作为最后的兜底更合适）。
    """
    prefixes = list(MIRROR_PREFIXES)
    custom = str(custom or "").strip()
    if custom and custom not in prefixes:
        prefixes.append(custom)

    seen = set()
    urls = []
    for prefix in prefixes:
        candidate = prefix + url
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _short(url, limit=90):
    """日志里的地址：太长的掐掉尾巴"""
    text = str(url)
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---------------- 代理 ----------------


def proxy_in_use():
    """当前会不会走代理

    不用自己读注册表：``urllib.request.getproxies()`` 在 Windows 上就是
    「环境变量优先，没有就回落到 Internet 选项」。
    """
    try:
        return bool(urllib.request.getproxies())
    except Exception:  # noqa: BLE001 - 注册表读不到就当没有
        return False


def proxy_description():
    """当前代理配置，给日志用"""
    try:
        proxies = urllib.request.getproxies()
    except Exception:  # noqa: BLE001
        return ""
    return ", ".join(f"{key}={value}" for key, value in sorted(proxies.items()))


_OPENERS = {}


def _opener(use_proxy=True):
    """拿一个 opener。

    ``use_proxy=False`` 时给一个空 ``ProxyHandler`` —— 这样连环境变量里的代理
    也不会被用上，不然「回退直连」根本回退不掉。
    """
    key = bool(use_proxy)
    opener = _OPENERS.get(key)
    if opener is None:
        if key:
            opener = urllib.request.build_opener()
        else:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
        _OPENERS[key] = opener
    return opener


def _request(url, offset=0, end=None):
    """构造 GET 请求；给了区间就带上 ``Range``"""
    headers = {"User-Agent": "NovelMaster", "Accept-Encoding": "identity"}
    if offset or end is not None:
        if end is None:
            headers["Range"] = f"bytes={offset}-"
        else:
            headers["Range"] = f"bytes={offset}-{end}"
    return urllib.request.Request(url, headers=headers)


# ---------------- 竞速 ----------------


class _Probe:
    """一个候选地址的探测结果。

    探测线程一边读一边更新这里的字段，所以主线程在它还没跑完时也读得到
    （只是可能不准）。``head`` 是「文件开头那截」，赢家那截可以直接顶进
    ``.part``，省得白下。
    """

    __slots__ = ("url", "use_proxy", "got", "elapsed", "head", "total",
                 "supports_range", "error", "finished", "response", "stop")

    def __init__(self, url, use_proxy=True):
        self.url = url
        self.use_proxy = use_proxy
        self.got = 0
        self.elapsed = 0.0
        self.head = []
        self.total = 0
        self.supports_range = False
        self.error = ""
        self.finished = False
        self.response = None
        self.stop = threading.Event()

    @property
    def ok(self):
        return self.finished and not self.error and self.got > 0

    @property
    def speed(self):
        """字节/秒"""
        return self.got / self.elapsed if self.elapsed > 0 else 0.0

    @property
    def data(self):
        return b"".join(self.head)


def _total_of(response, ranged):
    """从响应头里读文件总大小

    切了片（``206``）就看 ``Content-Range`` 的 ``/总大小``；没切片（``200``）
    则 ``Content-Length`` 就是整个文件。读不出来返回 0。
    """
    if ranged:
        content_range = response.headers.get("Content-Range") or ""
        if "/" in content_range:
            tail = content_range.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                return int(tail)
        return 0
    length = response.headers.get("Content-Length")
    if length and str(length).strip().isdigit():
        return int(length)
    return 0


def _probe(probe):
    """在一个候选地址上读一小会儿，量出速度、顺带问清支不支持分段"""
    started = time.time()
    try:
        response = _opener(probe.use_proxy).open(
            _request(probe.url, 0, PROBE_MAX_BYTES - 1), timeout=PROBE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - 连不上就是连不上
        probe.error = str(exc) or exc.__class__.__name__
        probe.elapsed = max(time.time() - started, 1e-3)
        probe.finished = True
        return

    probe.response = response
    try:
        status = getattr(response, "status", 200)
        probe.supports_range = status == 206
        probe.total = _total_of(response, probe.supports_range)
        deadline = started + PROBE_WINDOW
        while probe.got < PROBE_MAX_BYTES:
            if probe.stop.is_set():
                break
            if probe.got and time.time() >= deadline:
                break
            chunk = response.read(min(64 * 1024, PROBE_MAX_BYTES - probe.got))
            if not chunk:
                break
            probe.head.append(chunk)
            probe.got += len(chunk)
            probe.elapsed = max(time.time() - started, 1e-3)
    except Exception as exc:  # noqa: BLE001 - 被掐掉 / 读断了都算探测结束
        if not probe.stop.is_set():
            probe.error = str(exc) or exc.__class__.__name__
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
        probe.elapsed = max(time.time() - started, 1e-3)
        probe.finished = True


def _close_quietly(response):
    try:
        response.close()
    except Exception:  # noqa: BLE001
        pass


def _socket_of(response):
    """挖出响应底下那个真 socket（找不到返回 ``None``）"""
    fp = getattr(response, "fp", None)
    for node in (getattr(fp, "raw", None), fp, response):
        if node is None:
            continue
        for name in ("_sock", "sock", "_socket"):
            sock = getattr(node, name, None)
            if sock is not None:
                return sock
    return None


def _kill_socket(response):
    """把响应底下的连接真掐断（让卡在 ``read()`` 里的线程立刻醒）

    坑：光 ``sock.close()`` 不算数。``http.client`` 的响应体是用
    ``sock.makefile()`` 包出来的，只要那个 ``BufferedReader`` 还活着
    （``_io_refs > 0``），``socket.close()`` 就只是把对象标成已关闭、**不真关
    fd**，卡在 ``recv`` 的线程照样不醒（实测照样卡满整个超时）。必须再关一次
    ``fp.raw``（那个 ``SocketIO``），把 ``makefile`` 借的引用还回去，fd 这才真
    关掉，``recv`` 立刻抛 ``WinError 10038``。也别改成关整个 ``response``：
    ``BufferedReader`` 自己有锁，容易卡在调用方这边。
    """
    sock = _socket_of(response)
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    killed = False
    if sock is not None:
        try:
            sock.close()
            killed = True
        except Exception:  # noqa: BLE001 - 已经关了
            pass
    if raw is not None and raw is not sock:
        try:
            raw.close()
            killed = True
        except Exception:  # noqa: BLE001
            pass
    return killed


def _abort(probe):
    """掐掉一个还在跑的探测

    这里不能直接 ``close()`` 响应：对面「连上了但一个字节都不发」时，探测线程
    正卡在 ``read()`` 里并握着缓冲区的锁，``close()`` 会跟着一起卡（实测能卡到
    socket 超时）——「正在测速」就这么白等十几秒。所以改掐底层连接（见
    :func:`_kill_socket`）：它一断，``read()`` 立刻抛错，探测线程自己走到收尾。
    实在拿不到 socket 才把 ``close()`` 丢给一个小线程慢慢收尾，总之不能拖住
    调用方。
    """
    probe.stop.set()
    response = probe.response
    if response is None:
        return
    if not _kill_socket(response):
        threading.Thread(target=_close_quietly, args=(response,), daemon=True,
                         name="download-abort").start()


def race(urls, use_proxy=True, cancel=None):
    """同时探所有候选地址，返回按速度从快到慢排好的成功结果

    慢的那些顺手掐掉，别让它们在后台接着占带宽。
    """
    probes = [_Probe(url, use_proxy) for url in urls]
    threads = []
    for probe in probes:
        thread = threading.Thread(target=_probe, args=(probe,),
                                  name="download-probe", daemon=True)
        thread.start()
        threads.append(thread)

    deadline = time.time() + PROBE_WINDOW + PROBE_GRACE
    for thread in threads:
        remaining = deadline - time.time()
        if remaining > 0:
            thread.join(remaining)

    if not any(not thread.is_alive() for thread in threads):
        # 一个都没跑完：多半是「连上了不发数据」的坏地址，再给它一小会儿
        # （建连慢但活着的地址还有机会），到点就掐，别把「正在测速」拖长
        hard = time.time() + PROBE_SLOW
        while time.time() < hard:
            if any(not thread.is_alive() for thread in threads):
                break
            time.sleep(0.05)

    for probe, thread in zip(probes, threads):
        if thread.is_alive():
            _abort(probe)

    if cancel is not None and cancel():
        raise DownloadCancelled()

    for probe in probes:
        if not probe.ok:
            logger.log(f"下载地址测速没成（{probe.error or '没读到数据'}）: "
                       f"{_short(probe.url)}", "WARN")

    ready = [probe for probe in probes if probe.ok]
    ready.sort(key=lambda probe: probe.speed, reverse=True)
    for probe in ready:
        logger.log(f"测速 {probe.speed / 1024.0:.0f} KB/s"
                   f"{'（支持分段）' if probe.supports_range else '（不支持分段）'}"
                   f": {_short(probe.url)}", "INFO")
    return ready


# ---------------- 分段 ----------------


class _Segment:
    """一个字节区间 ``[start, end]``（两端都含）与「已经写到哪」"""

    __slots__ = ("start", "end", "done")

    def __init__(self, start, end, done=None):
        self.start = start
        self.end = end
        #: 已写好的位置（不含），即下一段要从 ``done`` 接着下
        self.done = start if done is None else done

    @property
    def size(self):
        return self.end - self.start + 1

    @property
    def finished(self):
        return self.done > self.end


def choose_connections(total, speed):
    """按实测速度决定分几段

    已经够快就一条连接了事（分段有代价）；慢则按「想凑到的总速度」倒推，再按
    文件大小封顶 —— 48 MB 的文件切 16 段，一段也有 3 MB。
    """
    if total < MIN_SEGMENT * 2:
        return 1
    if speed >= FAST_SPEED:
        return 1
    wanted = int(math.ceil(TARGET_SPEED / max(float(speed), 1.0)))
    wanted = max(2, min(MAX_CONNECTIONS, wanted))
    return max(1, min(wanted, max(1, total // MIN_SEGMENT)))


def _plan_segments(total, connections):
    """把 ``[0, total)`` 均分成 ``connections`` 段（最后一段吃掉余数）"""
    connections = max(1, min(int(connections), total))
    step = total // connections
    segments = []
    start = 0
    for index in range(connections):
        end = total - 1 if index == connections - 1 else start + step - 1
        segments.append(_Segment(start, end))
        start = end + 1
    return segments


def _meta_path(part):
    return part.parent / (part.name + META_SUFFIX)


def _load_meta(part, url, total):
    """读回上次的分段进度；不可信（缺文件 / 换了版本 / 换了大小的文件）就返回 None

    ``.part.json`` 是唯一的「下到哪儿了」的依据：分段写盘会先把 ``.part``
    撑到完整大小，光看文件长度分辨不出下了多少。
    """
    meta = _meta_path(part)
    try:
        raw = json.loads(meta.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != META_VERSION:
        return None
    if raw.get("url") != url or int(raw.get("size") or 0) != int(total):
        return None
    if not part.exists() or part.stat().st_size != total:
        return None

    segments = []
    try:
        for item in raw.get("segments") or ():
            start = int(item["start"])
            end = int(item["end"])
            done = int(item["done"])
            if not 0 <= start <= end < total:
                return None
            segments.append(_Segment(start, end, min(max(done, start), end + 1)))
    except (KeyError, TypeError, ValueError):
        return None
    if not segments:
        return None
    return segments


def _save_meta(part, url, total, segments):
    """把分段进度写回 ``.part.json``（先写临时文件再改名，别写坏）"""
    meta = _meta_path(part)
    payload = {
        "version": META_VERSION,
        "url": url,
        "size": int(total),
        "updated": int(time.time()),
        "segments": [{"start": segment.start, "end": segment.end,
                      "done": segment.done} for segment in segments],
    }
    temp = meta.with_name(meta.name + ".tmp")
    try:
        temp.write_text(json.dumps(payload), "utf-8")
        temp.replace(meta)
    except OSError as exc:
        logger.log(f"写入下载进度失败: {exc}", "WARN")


def _prepare_part(part, total):
    """建好 ``.part`` 并确保长度是 ``total``（不够就补零占位）"""
    try:
        part.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    size = part.stat().st_size if part.exists() else 0
    if size == total:
        return
    with open(str(part), "r+b" if size else "wb") as handle:
        handle.truncate(total)


def _write_at(part, offset, data):
    """往 ``.part`` 的 ``offset`` 处写一截"""
    if not data:
        return
    with open(str(part), "r+b") as handle:
        handle.seek(offset)
        handle.write(data)


def _discard(part):
    """把 ``.part`` 和它的进度一起扔掉（内容不可信时用）"""
    for path in (_meta_path(part), part):
        try:
            path.unlink()
        except OSError:
            pass


def _discard_meta(part):
    try:
        _meta_path(part).unlink()
    except OSError:
        pass


# ---------------- 一条连接 ----------------


def _stream(probe, part, progress, cancel, total):
    """一条连接从头（或从 ``.part`` 已有的长度）下到尾，返回 ``(已下, 总)``"""
    offset = part.stat().st_size if part.exists() else 0
    if total and offset > total:
        offset = 0
    if offset and not probe.supports_range:
        offset = 0

    response = _opener(probe.use_proxy).open(
        _request(probe.url, offset), timeout=TIMEOUT)
    try:
        status = getattr(response, "status", 200)
        resumed = status == 206
        if not resumed and offset:
            logger.log("服务器不支持断点续传，从头下载", "WARN")
            offset = 0
        if not total:
            length = int(response.headers.get("Content-Length") or 0)
            total = offset + length if length else 0
        with open(str(part), "ab" if resumed else "wb") as handle:
            while True:
                if cancel is not None and cancel():
                    raise DownloadCancelled()
                chunk = response.read(READ_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                offset += len(chunk)
                if progress is not None:
                    progress(offset, total)
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass

    if total and offset < total:
        raise DownloadFailed(f"只下到 {offset}/{total} 字节")
    return offset, total


def _pull(probe, part, segment, lock, state, report, cancel, stop, live):
    """拉 ``segment`` 还没下的那截，直接写进 ``part`` 的对应偏移

    ``live`` 里登记着正在用的响应，好让外面要收工时能把卡住的连接直接掐掉。
    """
    offset = segment.done
    if offset > segment.end:
        return

    response = _opener(probe.use_proxy).open(
        _request(probe.url, offset, segment.end), timeout=TIMEOUT)
    with lock:
        live.append(response)
    try:
        if getattr(response, "status", 200) != 206:
            raise DownloadFailed("服务器没有按分段给数据")
        with open(str(part), "r+b") as handle:
            handle.seek(offset)
            while offset <= segment.end:
                if stop.is_set():
                    return
                if cancel is not None and cancel():
                    raise DownloadCancelled()
                chunk = response.read(
                    min(READ_CHUNK, segment.end - offset + 1))
                if not chunk:
                    break
                handle.write(chunk)
                offset += len(chunk)
                with lock:
                    segment.done = offset
                    state["done"] += len(chunk)
                report()
        if offset <= segment.end and not stop.is_set():
            raise DownloadFailed(f"这一段只下到 {offset - segment.start}"
                                 f"/{segment.size} 字节")
    finally:
        with lock:
            try:
                live.remove(response)
            except ValueError:
                pass
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass


def _run_segments(probe, part, origin, total, segments, progress, cancel):
    """并发把各段没下的部分下完，返回「已下字节」

    某一段彻底失败就吹哨让大家都撤 —— 进度已经落盘，换下一个地址接着下比硬撑
    划算。已经下到的字节都算数，重试不会重复计数。
    """
    lock = threading.Lock()
    stop = threading.Event()
    live = []
    state = {"done": sum(min(segment.done, segment.end + 1) - segment.start
                         for segment in segments)}
    problems = []
    cancelled = []
    last = [0.0, 0]

    def report(force=False):
        if progress is None:
            return
        now = time.time()
        done = state["done"]
        if not force and now - last[0] < 0.06 and done - last[1] < 1024 * 1024:
            return
        last[0] = now
        last[1] = done
        progress(done, total)

    def worker(segment):
        for attempt in range(SEGMENT_RETRY):
            if stop.is_set():
                return
            try:
                _pull(probe, part, segment, lock, state, report, cancel, stop,
                      live)
                return
            except DownloadCancelled:
                with lock:
                    cancelled.append(True)
                stop.set()
                return
            except Exception as exc:  # noqa: BLE001 - 换个时机再试
                message = str(exc) or exc.__class__.__name__
                if attempt + 1 >= SEGMENT_RETRY:
                    with lock:
                        problems.append(message)
                    stop.set()
                    return
                if stop.is_set():
                    # 别人已经吹哨了（或外面取消了），别再白试
                    return
                logger.log(f"第 {segment.start}-{segment.end} 段出错"
                           f"（第 {attempt + 1} 次）: {message}", "WARN")
                time.sleep(0.4 * (attempt + 1))

    try:
        threads = []
        for segment in segments:
            if segment.finished:
                continue
            thread = threading.Thread(target=worker, args=(segment,),
                                      name="download-segment", daemon=True)
            thread.start()
            threads.append(thread)
        while True:
            pending = [thread for thread in threads if thread.is_alive()]
            if not pending:
                break
            for thread in pending:
                thread.join(0.25)
            if cancel is not None and cancel():
                stop.set()
            if stop.is_set():
                # 该收工了：卡着不动的连接直接掐掉，不然要等到 socket 超时
                with lock:
                    stuck = list(live)
                for response in stuck:
                    _kill_socket(response)
    finally:
        report(True)
        _save_meta(part, origin, total, segments)

    if cancelled or (cancel is not None and cancel()):
        raise DownloadCancelled()
    if problems:
        raise DownloadFailed(problems[0])
    if stop.is_set():
        raise DownloadFailed("下载中断")
    return state["done"]


def _notify(status, code, **kwargs):
    """给界面递一条状态（``code`` 由上层翻成人话）"""
    if status is None:
        return
    try:
        status(code, **kwargs)
    except TypeError:
        status(code)


# ---------------- 一趟完整下载 ----------------


def _fetch(probe, origin, part, expected, progress, status, cancel):
    """用 ``probe`` 把 ``part`` 下完，返回 ``(已下字节, 总字节, 连接数)``"""
    total = int(probe.total or expected or 0)

    if not probe.supports_range or not total:
        if total and not probe.supports_range:
            _notify(status, "no_segments")
        done, total = _stream(probe, part, progress, cancel, total)
        return done, total, 1

    segments = _load_meta(part, origin, total)
    if segments:
        if any(segment.done > segment.start for segment in segments):
            _notify(status, "resume")
        _prepare_part(part, total)
    else:
        connections = choose_connections(total, probe.speed)
        _prepare_part(part, total)
        segments = _plan_segments(total, connections)
        # 探测拿到的那截就是文件开头，直接顶进去，别白下
        head = probe.data[:total]
        if head:
            _write_at(part, 0, head)
            segments[0].done = min(total, max(segments[0].done, len(head)))
        _save_meta(part, origin, total, segments)

    connections = len(segments)
    if connections > 1:
        _notify(status, "connections", count=connections)
    done = _run_segments(probe, part, origin, total, segments, progress, cancel)
    return done, total, connections


def _download_with(urls, origin, dest, part, expected, progress, status, cancel,
                   use_proxy):
    """在一套传输方式下（走代理 / 丢开代理）把文件下完"""
    _notify(status, "probing")
    probes = race(urls, use_proxy, cancel)
    if not probes:
        raise DownloadFailed("所有下载地址都连不上")

    last_error = ""
    give_up = False
    for round_index in range(_ROUNDS):
        if give_up:
            break
        if round_index:
            logger.log(f"整个重来（第 {round_index + 1} 轮）", "WARN")
            time.sleep(0.5 * round_index)
        for index, probe in enumerate(probes):
            if index:
                _notify(status, "mirror")
                logger.log(f"改用其他下载地址: {_short(probe.url)}", "WARN")
            try:
                done, total, connections = _fetch(
                    probe, origin, part, expected, progress, status, cancel)
            except DownloadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 换地址 / 整轮重来
                last_error = str(exc) or exc.__class__.__name__
                logger.log(f"用 {_short(probe.url)} 下载失败: {last_error}",
                           "WARN")
                continue

            if expected and part.stat().st_size != expected:
                # 大小对不上不是偶发：换完地址还这样就没必要再来一轮
                last_error = (f"文件大小对不上（{part.stat().st_size} "
                              f"!= {expected}）")
                logger.log(last_error, "WARN")
                _discard(part)
                give_up = True
                break

            part.replace(dest)
            _discard_meta(part)
            logger.log(f"安装包下载完成: {dest.name}（{done / 1048576.0:.1f} MB，"
                       f"{connections} 连接，{_short(probe.url)}）", "INFO")
            return DownloadResult(True, DONE, "", dest, total, connections,
                                  probe.url, probe.speed)

    raise DownloadFailed(last_error or "下载失败")


def download_file(url, dest, *, custom_mirror="", expected=0, progress=None,
                  status=None, cancel=None):
    """把 ``url`` 下到 ``dest``，返回 :class:`DownloadResult`。

    :param expected: 远端报的文件大小，用来认出「下完了但对不上」的残缺文件
    :param progress: ``progress(已下字节, 总字节)``（总字节未知时是 0）
    :param status: ``status(代码, **参数)`` —— 换地址 / 改并发这类进度之外的
        提示；代码是 ``probing`` / ``connections`` / ``resume`` /
        ``no_segments`` / ``mirror`` / ``proxy_off``
    :param cancel: ``cancel()`` 返回 ``True`` 就中断（进度留着，下次接着下）
    """
    dest = Path(dest)
    part = dest.parent / (dest.name + ".part")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.log(f"创建下载目录失败: {exc}", "ERROR")
        return DownloadResult(False, FAILED, str(exc), part, 0, 0, "", 0.0)

    # 上次下完但用户点了「稍后」：文件还在就直接用
    if dest.exists() and (not expected or dest.stat().st_size == expected):
        return DownloadResult(True, CACHED, "", dest, dest.stat().st_size,
                              0, "", 0.0)

    urls = mirror_urls(url, custom_mirror)
    logger.log(f"开始下载安装包（{len(urls)} 个候选地址）: {_short(url)}",
               "INFO")

    has_proxy = proxy_in_use()
    if has_proxy:
        logger.log(f"检测到代理，先走代理: {proxy_description()}", "INFO")

    last_error = ""
    for use_proxy in ([True, False] if has_proxy else [True]):
        if not use_proxy:
            _notify(status, "proxy_off")
            logger.log("代理这条路走不通，丢掉代理直连重试", "WARN")
        try:
            return _download_with(urls, url, dest, part, expected, progress,
                                  status, cancel, use_proxy)
        except DownloadCancelled:
            logger.log("用户取消下载安装包", "INFO")
            return DownloadResult(False, CANCELLED, "", part, 0, 0, "", 0.0)
        except DownloadFailed as exc:
            last_error = str(exc)
            logger.log(f"下载失败（{'走代理' if use_proxy else '直连'}）: "
                       f"{last_error}", "WARN")
        except Exception as exc:  # noqa: BLE001 - 别的意外也别炸给界面看
            last_error = str(exc) or exc.__class__.__name__
            logger.log(f"下载出错（{'走代理' if use_proxy else '直连'}）: "
                       f"{last_error}", "ERROR")
            break

    return DownloadResult(False, FAILED, last_error, part, 0, 0, "", 0.0)


__all__ = ["CACHED", "CANCELLED", "DONE", "DownloadCancelled",
           "DownloadFailed", "DownloadResult", "FAILED", "MAX_CONNECTIONS",
           "META_SUFFIX", "MIN_SEGMENT", "MIRROR_PREFIXES", "READ_CHUNK",
           "TARGET_SPEED", "choose_connections", "download_file",
           "mirror_urls", "proxy_description", "proxy_in_use", "race"]
