"""内嵌图片支持：把书内资源统一转换为 ``data:`` URI 内联进章节 HTML。

为什么统一用 data URI：

* 渲染端 ``QTextEdit`` / ``QTextDocument`` 可以直接解析 ``data:`` URI，
  不需要为文档设置 base URL；
* 自包含，Nuitka 打包（含 onefile）后依然有效；
* 不受临时目录生命周期影响 —— ``ArchiveReader`` / ``MobiReader`` 在
  ``close()`` 时会删除解压出来的临时目录，相对路径届时会失效。

对外主要提供两个函数：

* :func:`to_data_uri` —— 字节流 -> data URI
* :func:`inline_images` —— 把 HTML 里的 ``<img>`` / SVG ``<image>``
  逐个交给 ``resolver`` 解析后替换为 data URI

另提供排版辅助函数 :func:`isolate_block_images`：让每张图片独占一个段落
（含 ``</p><img/><p>`` 这种没写在块里的散装图片），避免行内图片撑高所在
行的行距。
"""

import base64
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..logger import logger

# 单张图片内联上限（超过则跳过，避免章节 HTML 过大导致界面卡顿）
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# 单个章节内联图片的总体积上限
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024

# 扩展名 -> MIME
MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.jpe': 'image/jpeg',
    '.jfif': 'image/jpeg',
    '.png': 'image/png',
    '.apng': 'image/png',
    '.gif': 'image/gif',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    '.avif': 'image/avif',
    '.jxl': 'image/jxl',
}

# 魔数 -> MIME（优先于扩展名：扩展名与实际内容不一致时仍能正确渲染）
_MAGIC_SIGNATURES = (
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
    (b'II*\x00', 'image/tiff'),
    (b'MM\x00*', 'image/tiff'),
    (b'\x00\x00\x01\x00', 'image/x-icon'),
    (b'\x00\x00\x02\x00', 'image/x-icon'),
)

# 无需内联的引用（远程资源 / 已经是内联数据 / 锚点）
_EXTERNAL_PREFIXES = (
    'data:', 'http://', 'https://', '//', 'mailto:', 'javascript:', 'about:',
    'ftp://', 'file:///',
)

_TAG_RE = re.compile(r'<(?:\w+:)?(img|image)\b[^>]*>', re.IGNORECASE)


def _attr(tag, name):
    """读取标签属性值（兼容双引号 / 单引号 / 无引号写法）"""
    pattern = (r'\b' + re.escape(name) +
               r'''\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))''')
    match = re.search(pattern, tag, re.IGNORECASE)
    if not match:
        return ''
    for group in match.groups():
        if group is not None:
            return group
    return ''


def _first_attr(tag, names):
    """按优先级返回第一个存在的属性，形式为 ``(属性名, 取值)``"""
    for name in names:
        value = _attr(tag, name)
        if value:
            return name, value
    return '', ''


def _set_attr(tag, name, value):
    """只改写指定属性的取值，避免误伤标签里的其他同名文本"""
    pattern = re.compile(
        r'(\b' + re.escape(name) +
        r'''\s*=\s*)(?:"[^"]*"|'[^']*'|[^\s"'>]+)''', re.IGNORECASE)
    return pattern.sub(lambda match: match.group(1) + '"' + value + '"',
                       tag, count=1)


def clean_reference(reference):
    """去掉引用中的 URL 编码、查询串与锚点，返回相对/绝对路径"""
    if not reference:
        return ''
    text = reference.strip().strip('\'"').replace('\\', '/')
    if not text:
        return ''
    split = urlsplit(text)
    path = unquote(split.path or '')
    return path.strip()


def is_external_reference(reference):
    """判断引用是否无需内联（远程地址、data URI、锚点等）"""
    text = (reference or '').strip().lower()
    if not text or text.startswith('#'):
        return True
    return text.startswith(_EXTERNAL_PREFIXES)


def guess_mime(extension='', data=None, default='image/jpeg'):
    """推断图片 MIME：优先看文件头，其次看扩展名"""
    if data:
        for signature, mime in _MAGIC_SIGNATURES:
            if data.startswith(signature):
                return mime
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        head = data[:1024].lstrip().lower()
        if head.startswith(b'<svg') or head.startswith(b'<?xml') and b'<svg' in head:
            return 'image/svg+xml'

    suffix = (extension or '').lower()
    if suffix and not suffix.startswith('.'):
        suffix = '.' + suffix
    return MIME_TYPES.get(suffix, default)


def looks_like_image(data):
    """粗略判断字节流是否为常见图片格式"""
    if not data or len(data) < 8:
        return False
    for signature, _mime in _MAGIC_SIGNATURES:
        if data.startswith(signature):
            return True
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    head = data[:1024].lstrip().lower()
    return head.startswith(b'<svg') or (head.startswith(b'<?xml') and b'<svg' in head)


def image_suffix(extension=''):
    """把扩展名规范成小写 ``.ext`` 形式"""
    suffix = (extension or '').lower()
    if suffix and not suffix.startswith('.'):
        suffix = '.' + suffix
    return suffix


def is_image_name(name):
    """按文件名判断是否为图片（用于识别压缩包 / EPUB 内的图片条目）"""
    return image_suffix(Path(name).suffix) in MIME_TYPES


def to_data_uri(data, mime=''):
    """把图片字节转成 data URI；失败返回空串"""
    if not data:
        return ''
    try:
        encoded = base64.b64encode(data).decode('ascii')
    except (TypeError, ValueError) as e:
        logger.log(f"图片编码失败: {e}", "WARN")
        return ''
    return f"data:{mime or guess_mime(data=data)};base64,{encoded}"


def resolve_zip_path(base_name, reference):
    """按 ZIP/EPUB 内部路径规则解析引用（处理 ``../`` 与 ``./``）

    :param base_name: 引用所在文档的内部路径，例如 ``OEBPS/Text/ch1.xhtml``
    :param reference: 文档里写的 ``src``，例如 ``../Images/a.png``
    """
    path = clean_reference(reference)
    if not path:
        return ''
    if path.startswith('/'):
        return posixpath.normpath(path.lstrip('/'))
    base_dir = posixpath.dirname((base_name or '').replace('\\', '/'))
    return posixpath.normpath(posixpath.join(base_dir, path))


def candidate_paths(base_name, reference):
    """给出一条引用在同一压缩包内可能的若干种路径（供查表使用）

    依次给出：按文档目录解析的结果、原样路径、去掉 ``../`` 前缀的路径，
    以及文件名本身。不同工具生成的电子书路径写法差异较大，逐级尝试可
    显著提高命中率。
    """
    raw = (reference or '').strip().replace('\\', '/')
    path = clean_reference(reference)
    results = []

    def add(value):
        if not value:
            return
        for variant in (value, unquote(value)):
            normalized = posixpath.normpath(variant)
            if normalized and normalized not in results:
                results.append(normalized)

    if path:
        add(resolve_zip_path(base_name, reference))
        add(path)
        stripped = path.lstrip('/')
        while stripped.startswith('../'):
            stripped = stripped[3:]
        add(stripped)
        add(posixpath.basename(path))

    if raw and raw not in results:
        results.append(raw)
    return results


def _resolve_with(resolver, reference):
    """调用 resolver 并规整返回值，返回 (data, mime) 或 None"""
    try:
        result = resolver(reference)
    except Exception as e:                       # 单个图片失败不影响整章渲染
        logger.log(f"解析内嵌图片失败（{reference}）: {e}", "WARN")
        return None
    if isinstance(result, tuple):
        data, mime = (list(result) + [''])[:2]
    else:
        data, mime = result, ''
    if not data:
        return None
    return data, mime or ''


def inline_images(html_text, resolver, max_bytes=MAX_IMAGE_BYTES,
                  max_total_bytes=MAX_TOTAL_IMAGE_BYTES,
                  keep_unresolved=False):
    """把 HTML 中的 ``<img>`` / SVG ``<image>`` 替换成 data URI

    :param resolver: ``resolver(src)`` -> ``bytes`` 或 ``(bytes, mime)``，
        返回空值时表示解析失败
    :param keep_unresolved: 解析失败时是否保留原始标签（默认丢弃，避免
        阅读器里出现破损图片图标）
    """
    if not html_text or resolver is None:
        return html_text

    if not _TAG_RE.search(html_text):
        return html_text

    cache = {}
    state = {'total': 0, 'missing': 0, 'oversized': 0}

    def replace(match):
        tag = match.group(0)
        name = match.group(1).lower()

        if name == 'img':
            attr_name, reference = _first_attr(tag, ('src', 'lowsrc'))
        else:
            attr_name, reference = _first_attr(tag, ('xlink:href', 'href', 'src'))

        if not reference or is_external_reference(reference):
            return tag

        key = reference.strip()
        if key in cache:
            uri = cache[key]
        else:
            resolved = _resolve_with(resolver, reference)
            uri = ''
            if resolved:
                data, mime = resolved
                if len(data) > max_bytes:
                    state['oversized'] += 1
                    logger.log(f"内嵌图片过大已跳过（{len(data)} 字节）: {reference}",
                               "WARN")
                elif state['total'] + len(data) > max_total_bytes:
                    state['oversized'] += 1
                else:
                    state['total'] += len(data)
                    uri = to_data_uri(data, mime)
            cache[key] = uri

        if not uri:
            state['missing'] += 1
            return tag if keep_unresolved else ''
        return _set_attr(tag, attr_name, uri)

    result = _TAG_RE.sub(replace, html_text)

    if state['missing'] or state['oversized']:
        logger.log(f"内嵌图片处理完成：跳过 {state['missing']} 张（无法解析）、"
                   f"{state['oversized']} 张（超过体积限制）", "WARN")

    return result


# --------------------------------------------------------------------------
# 排版规范化：把与文字混排的图片拆成独立段落
# --------------------------------------------------------------------------

# 块级容器（li/td 内拆分容易破坏表格与列表结构，故不处理）
_BLOCK_START_RE = re.compile(r'<(p|div)\b([^>]*)>', re.IGNORECASE | re.DOTALL)
_BLOCK_CLOSE_RE = re.compile(r'</(?:p|div)\s*>', re.IGNORECASE)
# 单个图片标签（含 SVG 的 image 以及带命名空间前缀的写法）
_IMAGE_TAG_RE = re.compile(r'(<(?:[\w-]+:)?(?:img|image)\b[^>]*/?>)',
                           re.IGNORECASE)
_TAG_TOKEN_RE = re.compile(r'<(/?)([\w:.-]+)[^>]*?(/?)>')
_NBSP_RE = re.compile(r'&nbsp;|&#160;|&#xa0;|\u00a0', re.IGNORECASE)
# 块首尾多余的换行与空白
_EDGE_BREAK_RE = re.compile(r'^(?:\s|<br\s*/?>)+|(?:\s|<br\s*/?>)+$',
                            re.IGNORECASE)

_VOID_TAGS = frozenset({
    'br', 'hr', 'img', 'image', 'input', 'meta', 'link', 'source', 'wbr',
    'col', 'area', 'base', 'embed', 'param', 'track',
})


def _plain_text(fragment):
    """取片段中的可见文字（去掉标签与 &nbsp; 等占位空格）"""
    return _NBSP_RE.sub('', re.sub(r'<[^>]*>', '', fragment)).strip()


def _tags_balanced(fragment):
    """判断片段的标签是否成对（不配对时不做拆分，避免破坏结构）"""
    stack = []
    for match in _TAG_TOKEN_RE.finditer(fragment):
        closing, name, self_closing = match.groups()
        name = name.lower()
        if self_closing or name in _VOID_TAGS:
            continue
        if closing:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def _enclosing_block(text, image_start, block_starts):
    """找出包住图片的最内层 p/div 块

    :param block_starts: ``[(start, name, attrs, content_start), ...]``，
        由 :func:`_scan_block_starts` 顺序给出
    :return: ``(start, end, name, attrs, inner)``，找不到时返回 ``None``；
        块若缺少结束标签，则以「下一个块标签之前」为界
    """
    chosen = None
    for item in reversed(block_starts):
        if item[0] > image_start:
            continue
        # 该块在图片之前就已经闭合，说明图片并不属于它，继续往外找
        if _BLOCK_CLOSE_RE.search(text, item[3], image_start):
            continue
        chosen = item
        break

    if chosen is None:
        return None

    start, name, attrs, content_start = chosen
    close = _BLOCK_CLOSE_RE.search(text, image_start)
    following = next((item for item in block_starts if item[0] > image_start),
                     None)
    if following is not None and (close is None or following[0] < close.start()):
        # 块未闭合：到下一个块标签为止
        return start, following[0], name, attrs, text[content_start:following[0]]
    if close is not None:
        return start, close.end(), name, attrs, text[content_start:close.start()]
    # 既没有结束标签也不是最后一个块：放弃，交给阅读器原样渲染
    if following is None:
        return start, len(text), name, attrs, text[content_start:]
    return None


def _split_block(name, attrs, inner):
    """把块内容拆成「文字块 + 图片块」，不需要拆分时返回 ``None``"""
    pieces = _IMAGE_TAG_RE.split(inner)
    if len(pieces) < 2:
        return None
    # 只有图片（或只有占位空格）：保持原样，交给阅读区自适应宽度处理
    if not any(_plain_text(_EDGE_BREAK_RE.sub('', piece))
               for piece in pieces[0::2]):
        return None

    blocks = []
    for index, piece in enumerate(pieces):
        if index % 2:
            blocks.append('<p>%s</p>' % piece)
            continue
        trimmed = _EDGE_BREAK_RE.sub('', piece)
        if not _plain_text(trimmed):
            continue
        block = '<%s%s>%s</%s>' % (name, attrs, trimmed, name)
        # 只校验文字块的标签配对：图片片段是单个自闭合标签，且扫描大体积
        # 的 data URI 会明显变慢
        if not _tags_balanced(block):
            return None
        blocks.append(block)

    if len(blocks) < 2:
        return None
    return ''.join(blocks)


def isolate_block_images(html_text):
    """让每张图片独占一个段落，避免行内图片撑大所在行的行距

    ``QTextDocument`` 里行内图片会把所在行撑到图片高度，导致图片附近的文字
    出现明显的大行距。这里分两种情况处理：

    * 图片在 ``p`` / ``div`` 里与文字混排 —— 把该块拆成「文字段 + 图片段」；
    * 图片直接写在块外面（``</p><img/><p>`` 这种写法在电子书里非常常见）
      —— 它会被排进前一个块，因此给图片补一个自己的 ``p``。

    只有确认拆分不会破坏标签配对时才生效；且逐张图片定位所在块，避免扫描
    整个章节正文（图片经 data URI 内联后动辄数兆）。
    """
    if not html_text:
        return html_text

    images = list(_IMAGE_TAG_RE.finditer(html_text))
    if not images:
        return html_text

    block_starts = [(match.start(), match.group(1).lower(), match.group(2),
                     match.end())
                    for match in _BLOCK_START_RE.finditer(html_text)]

    edits = []
    handled = set()
    for image in images:
        bounds = _enclosing_block(html_text, image.start(), block_starts)
        if bounds is None:
            # 不在任何 p/div 内的散装图片：单独包一层段落
            edits.append((image.start(), image.end(),
                          '<p>%s</p>' % image.group(0)))
            continue
        if bounds[0] in handled:
            continue
        handled.add(bounds[0])
        replacement = _split_block(bounds[2], bounds[3], bounds[4])
        if replacement:
            edits.append((bounds[0], bounds[1], replacement))

    for start, end, replacement in reversed(edits):     # 从后往前替换，索引不失效
        html_text = html_text[:start] + replacement + html_text[end:]
    return html_text

