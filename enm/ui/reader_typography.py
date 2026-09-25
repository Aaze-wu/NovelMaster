"""阅读区排版：把行距 / 段间距**真正**套到 ``QTextDocument`` 上。

这个模块存在的原因是一个踩过的坑：**Qt 的样式表不支持 ``line-height``**。
实测同一段 16px 正文，``QTextEdit { line-height: 2.0; }`` 与完全不带样式
的文档高度一模一样（160.0 vs 160.0），也就是主题里那个「行距」以前只是
把数字存下来了，屏幕上什么都没变。行距只能落到**块格式**上：
``QTextBlockFormat.setLineHeight(百分比, ProportionalHeight)``（同一探针
里 180% → 文档高度 290.0，立刻见效）。

段间距同理。Qt 解析 ``<p>`` 时给块的上下边距各 12px（合计 24px），
``mergeBlockFormat`` 显式设置会**覆盖**它，所以「段间距 24px」正好等于
Qt 的默认外观——把默认值定成 24 就不会让老用户的书突然变挤。

实现上用**一次** ``mergeBlockFormat`` 改完整篇文档（比逐块设置快得多）。
代价是它也作用到 ``<table>`` 单元格里的段落——对小说排版来说无所谓，
换来的是实现足够短、不容易出错。
"""

from PyQt5.QtGui import QTextBlockFormat, QTextCursor

#: 行距倍数的换算基数：1.0 倍 = 100%
LINE_HEIGHT_UNIT = 100


def line_height_percent(line_spacing):
    """行距倍数 → 块格式用的百分比整数（1.8 → 180）"""
    return int(round(float(line_spacing) * LINE_HEIGHT_UNIT))


def apply_reader_typography(edit, line_spacing=None, paragraph_spacing=None):
    """把行距 / 段间距套到 ``edit`` 的整篇文档上。

    ``line_spacing`` 是倍数（1.0 = 单倍行距）；``paragraph_spacing`` 是
    相邻两段之间的空白总量（像素）——上下边距各分一半，所以两个正常段落
    之间的间隙正好是它。传 ``None`` 表示这一项保持文档自带的值。

    返回是否真的改动了文档（两个参数都是 ``None``、或文档还是空的时候
    返回 ``False``）。
    """
    block_format = QTextBlockFormat()
    touched = False

    if line_spacing is not None:
        block_format.setLineHeight(line_height_percent(line_spacing),
                                   QTextBlockFormat.ProportionalHeight)
        touched = True

    if paragraph_spacing is not None:
        half = max(0.0, float(paragraph_spacing)) / 2.0
        block_format.setTopMargin(half)
        block_format.setBottomMargin(half)
        touched = True

    document = edit.document()
    if not touched or document.isEmpty():
        return False

    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    cursor.mergeBlockFormat(block_format)
    return True
