"""阅读器通用工具与基类（不依赖任何具体格式）。"""

import html as html_lib
import re
import shutil

import chardet

from ..logger import logger
from .images import isolate_block_images


# 新增的阅读器都遵循与 EpubReader / TxtReader 相同的章节接口：
#   get_chapter_count() / get_chapter_title(i) / get_chapter_content(i) / current_chapter
# 章节内容统一返回 HTML 片段，由主窗口使用 setHtml() 渲染。

class ReaderError(Exception):
    """阅读器错误：携带面向用户的中文提示信息"""


def escape_html(text):
    """转义 HTML 特殊字符"""
    if text is None:
        return ""
    return html_lib.escape(str(text))


def text_to_html(text):
    """把纯文本转换为安全的 HTML 片段（保留空行分段与行内换行）"""
    if not text:
        return ""

    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = []
    for paragraph in re.split(r'\n[ \t]*\n', normalized):
        if not paragraph.strip():
            continue
        blocks.append("<p>%s</p>" % escape_html(paragraph).replace(chr(10), '<br/>'))

    if not blocks:
        return "<p>%s</p>" % escape_html(normalized)
    return ''.join(blocks)


def strip_tags(text):
    """去掉 HTML 标签，返回纯文本"""
    if not text:
        return ""
    return html_lib.unescape(re.sub(r'<[^>]*>', '', text)).strip()


_HEAD_BLOCK_RE = re.compile(r'<head\b.*?</head>', re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r'<(script|style)\b.*?</\1>', re.IGNORECASE | re.DOTALL)
_BODY_BLOCK_RE = re.compile(r'<body\b[^>]*>(.*?)</body>', re.IGNORECASE | re.DOTALL)
_MBP_TAG_RE = re.compile(r'</?mbp:[^>]*>', re.IGNORECASE)
_HEADING_RE = re.compile(r'<h([1-6])\b[^>]*>(.*?)</h\1>', re.IGNORECASE | re.DOTALL)

# 正文开头的噪声（XML 声明 / DOCTYPE / 注释）与紧随其后的第一个标题
_LEADING_NOISE_RE = re.compile(
    r'(?:\s*(?:<\?[^>]*\?>|<!DOCTYPE[^>]*>|<!--.*?-->))*\s*', re.IGNORECASE | re.DOTALL)
_LEADING_HEADING_RE = re.compile(r'<h([1-6])\b[^>]*>(.*?)</h\1>',
                                 re.IGNORECASE | re.DOTALL)
_HEADING_SPACE_RE = re.compile(r'[\s\u3000\xa0]+')


def clean_html_content(raw_html):
    """清理 HTML 片段：去掉 head/script/style 以及 MOBI 私有标签"""
    if not raw_html:
        return ""

    text = _HEAD_BLOCK_RE.sub('', raw_html)
    text = _SCRIPT_STYLE_RE.sub('', text)
    text = _MBP_TAG_RE.sub('', text)

    body_match = _BODY_BLOCK_RE.search(text)
    if body_match:
        text = body_match.group(1)

    return text.strip()


def _comparable_heading(text):
    """把标题文本规整成可比较的形式（去标签、去全部空白）"""
    return _HEADING_SPACE_RE.sub('', strip_tags(text or ''))


def _is_same_heading(heading_text, title_text):
    """判断两个标题是否指同一个标题（完全相同，或短的是长的前缀）"""
    if not heading_text or not title_text:
        return False
    if heading_text == title_text:
        return True
    short, long = sorted((heading_text, title_text), key=len)
    return len(short) >= 3 and long.startswith(short)


def strip_duplicate_title(body, title):
    """去掉正文开头那个与章节标题重复的标题行

    EPUB / FB2 / HTML 的原文常常自带 ``<h1>第1章 …</h1>``，标题栏已经用
    ``<h3>`` 显示同一个标题；不处理的话正文里会把标题显示第二遍，
    所以这里把重复的开头标题整行删掉。
    """
    title_text = _comparable_heading(title)
    if not body or not title_text:
        return body

    noise = _LEADING_NOISE_RE.match(body)
    start = noise.end() if noise else 0
    match = _LEADING_HEADING_RE.match(body, start)
    if not match:
        return body

    heading_text = _comparable_heading(match.group(2))
    if not _is_same_heading(heading_text, title_text):
        return body
    return body[match.end():].lstrip()


def format_chapter_html(title, content):
    """把章节标题与内容组合成可直接 setHtml() 的 HTML 片段

    内容如果已经是 HTML（EPUB/FB2/DOCX 等）则清理后直接使用，
    纯文本（TXT 等）则按空行分段转成 <p>。
    正文开头如果自带与章节标题相同的标题行，会被去掉，避免标题显示两遍。
    """
    safe_title = escape_html(title or "")
    body = content or ""

    looks_like_html = bool(re.search(
        r'</?(p|div|br|h[1-6]|img|span|html|body|table|ul|ol|li)\b',
        body, re.IGNORECASE))

    if looks_like_html:
        body = clean_html_content(body)
        body = isolate_block_images(strip_duplicate_title(body, title))
    else:
        body = text_to_html(body)

    return f"<h3>{safe_title}</h3>\n{body}"


def split_html_by_headings(html_text):
    """按 h1~h6 标题切分 HTML，返回 [(标题或 None, HTML 片段), ...]"""
    if not html_text:
        return []

    matches = list(_HEADING_RE.finditer(html_text))
    if not matches:
        return []

    chapters = []

    prefix = html_text[:matches[0].start()].strip()
    if strip_tags(prefix):
        chapters.append((None, prefix))

    for i, match in enumerate(matches):
        title = strip_tags(match.group(2))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html_text)
        fragment = html_text[match.start():end].strip()
        if fragment:
            chapters.append((title or None, fragment))

    return chapters


def decode_bytes(raw, default='utf-8'):
    """尽量正确地解码字节内容（BOM -> charset 声明 -> 常见编码 -> chardet）"""
    if not raw:
        return ""

    for bom, encoding in ((b'\xef\xbb\xbf', 'utf-8-sig'),
                          (b'\xff\xfe', 'utf-16'),
                          (b'\xfe\xff', 'utf-16')):
        if raw.startswith(bom):
            return raw.decode(encoding, errors='replace')

    candidates = []
    declared = re.search(rb'charset\s*=\s*["\']?\s*([A-Za-z0-9_\-]+)', raw[:4096])
    if declared:
        candidates.append(declared.group(1).decode('ascii', 'ignore'))
    candidates.extend([default, 'utf-8', 'gb18030', 'big5', 'cp1252'])

    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue

    try:
        guessed = chardet.detect(raw).get('encoding')
        if guessed:
            return raw.decode(guessed, errors='replace')
    except Exception as e:
        logger.log(f"编码识别失败: {e}", "ERROR")

    return raw.decode('utf-8', errors='replace')


def palmdoc_decompress(data):
    """PalmDOC (LZ77 变体) 解压，用于 MOBI 正文记录"""
    output = bytearray()
    index = 0
    total = len(data)

    while index < total:
        byte = data[index]
        index += 1

        if byte == 0:                       # 原样输出的 0
            output.append(0)
        elif byte <= 8:                     # 直接复制后面的 N 个字节
            end = min(index + byte, total)
            output.extend(data[index:end])
            index = end
        elif byte < 0x80:                   # ASCII
            output.append(byte)
        elif byte < 0xC0:                   # 距离/长度对
            if index >= total:
                break
            pair = (byte << 8) | data[index]
            index += 1
            distance = (pair >> 3) & 0x07FF
            repeat = (pair & 0x07) + 3
            start = max(0, len(output) - distance)
            for _ in range(repeat):
                output.append(output[start] if start < len(output) else 0x20)
                start += 1
        else:                               # 空格 + 去掉高位的字符
            output.append(0x20)
            output.append(byte ^ 0x80)

    return bytes(output)


def local_name(tag):
    """取出 XML 标签的本地名（忽略命名空间）"""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit('}', 1)[-1]


def xml_text(element):
    """取 XML 元素内的全部文本"""
    if element is None:
        return ""
    return ''.join(element.itertext()).strip()


def is_docx_heading(paragraph):
    """判断 DOCX 段落是否使用了标题样式"""
    style = getattr(paragraph, 'style', None)
    if style is None:
        return False
    name = getattr(style, 'name', '') or ''
    if not name:
        return False
    return bool(re.match(r'^(Heading|标题)\s*\d*', name, re.IGNORECASE))


# ==================== 多格式支持：阅读器基类 ====================

class BaseReader:
    """阅读器基类，所有格式的阅读器都继承它，保证对外接口一致

    约定：

    * 章节内容统一为 HTML 片段（由主窗口 ``setHtml()`` 渲染）；
    * 章节访问使用 :meth:`get_chapter_count` / :meth:`get_chapter_title` /
      :meth:`get_chapter_content`，当前章节位置放在 ``current_chapter``；
    * 书籍信息用 ``book_title`` / ``book_author`` 保存，由
      :meth:`get_book_info` 以 ``{'title': ..., 'author': ...}`` 返回；
    * 临时资源（如压缩包解压目录）交给 :meth:`close` 释放。
    """

    def __init__(self, file_path):
        self.file_path = str(file_path)
        self.chapters = []
        self.current_chapter = 0
        self.book_title = ""
        self.book_author = ""

    # ---------------- 统一对外接口 ----------------

    def get_chapter_count(self):
        return len(self.chapters)

    def get_chapter_title(self, index):
        if 0 <= index < len(self.chapters):
            return self.chapters[index]['title']
        return ""

    def get_chapter_content(self, index):
        if 0 <= index < len(self.chapters):
            return self.chapters[index]['content']
        return ""

    def get_book_info(self):
        """附加书籍信息（用于窗口标题栏），返回 {'title', 'author'}"""
        return {'title': self.book_title, 'author': self.book_author}

    def close(self):
        """释放资源（例如压缩包解压出来的临时目录）"""
        temp_dir = getattr(self, '_temp_dir', None)
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._temp_dir = None

    # ---------------- 内部辅助 ----------------

    def _set_book_info(self, title=None, author=None):
        """记录书籍标题 / 作者（空白值不会覆盖已有内容）"""
        if title and not self.book_title:
            self.book_title = str(title).strip()
        if author and not self.book_author:
            self.book_author = str(author).strip()

    def _add_chapter(self, title, content, fallback_title=None):
        content = content or ""
        if not strip_tags(content) and '<img' not in content.lower():
            return
        if not title:
            title = fallback_title or f"第{len(self.chapters) + 1}章"
        self.chapters.append({'title': title, 'content': content})

    def _add_text_chapter(self, title, text, fallback_title=None):
        self._add_chapter(title, text_to_html(text), fallback_title)

    def _append_html(self, html):
        if self.chapters:
            self.chapters[-1]['content'] += html
        else:
            self._add_chapter(None, html, '正文')

    def _finish(self, default_title="全文"):
        if not self.chapters:
            self.chapters.append({'title': default_title,
                                  'content': '<p>（没有可显示的内容）</p>'})
        self.current_chapter = 0
