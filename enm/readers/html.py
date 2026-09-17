"""HTML / XHTML 阅读器。"""

from pathlib import Path

from .base import (BaseReader, clean_html_content, decode_bytes,
                   split_html_by_headings)
from .images import (MAX_IMAGE_BYTES, clean_reference, guess_mime,
                     inline_images, looks_like_image)


class HtmlReader(BaseReader):
    """HTML / XHTML 阅读器（无需第三方依赖）"""

    def __init__(self, file_path):
        super().__init__(file_path)
        self.load()

    def load(self):
        raw = Path(self.file_path).read_bytes()
        body = clean_html_content(decode_bytes(raw))
        body = inline_images(body, self._image_resolver())

        chapters = split_html_by_headings(body)
        if chapters:
            for title, fragment in chapters:
                self._add_chapter(title, fragment, '正文')
        else:
            self._add_chapter(None, body, '全文')

        self._finish()

    def _image_resolver(self):
        """解析与 HTML 同目录（及其子目录）下的本地图片"""
        base_dir = Path(self.file_path).parent

        def resolve(reference):
            path = clean_reference(reference)
            if not path:
                return None

            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = base_dir / candidate

            try:
                if not candidate.is_file():
                    return None
                if candidate.stat().st_size > MAX_IMAGE_BYTES:
                    return None
                data = candidate.read_bytes()
            except OSError:
                return None

            if not looks_like_image(data):
                return None
            return data, guess_mime(candidate.suffix, data[:64])

        return resolve
