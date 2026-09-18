"""多语言管理（``lang/*.json``）。

语言文件是**嵌套字典**，读取时用点号路径，例如::

    {
        "menu": {"file": "文件"},
        "msg": {"load_file_failed": "加载文件失败: {error}"}
    }

    tr("menu.file")                              -> "文件"
    tr("msg.load_file_failed", error="坏文件")   -> "加载文件失败: 坏文件"

查找规则：

1. 先查当前语言，再查默认语言（``DEFAULT_LANG``），两者都没有才回退；
2. 回退时返回调用方给的 ``default``；没给就返回键本身，
   这样界面上会直接显示 ``menu.file`` 这种漏翻的键，便于排查；
3. 缺键会记录到 :attr:`LanguageManager.missing_keys`，调试模式下写一条日志。

语言文件可以**直接往 ``lang/`` 目录里放**：启动时会扫描该目录，读 ``lang.name``
登记语言，按语系插到内置语言（``BUILTIN_LANGUAGES``）旁边，不需要改代码。

界面上的 ``—``、``、`` 这类标点也放在语言文件里（``common.*``），
英文版才能换成 ASCII 写法。
"""

import json
import os

from ..constants import LANG_PATH, PROJECT_NAME
from ..logger import logger

# 默认（兜底）语言：当前语言缺键时用它的文案
DEFAULT_LANG = "zh_CN"

# 内置语言：即使语言文件缺失也会出现在语言菜单里
BUILTIN_LANGUAGES = (
    ("zh_CN", "简体中文"),
    ("en_US", "English"),
)


def base_code(lang_code):
    """取语言代码的语系部分，如 ``zh_TW`` -> ``zh``"""
    return str(lang_code).split("_")[0].lower()


def discover_languages(builtin=BUILTIN_LANGUAGES):
    """扫描 ``lang/*.json``，把内置语言之外的语言文件登记进来。

    新增一种语言只需要把 ``<语言代码>.json`` 放进 ``lang/`` 目录（写上
    ``"lang": {"name": "显示名"}``），不需要改代码。自动发现的语言按**语系**
    插到内置语言旁边，同语系的排在一起（``zh_CN`` / ``zh_TW`` / ``en_US``）。

    语言文件读不出来、不是对象或缺 ``lang.name`` 时都不会影响启动：前者跳过
    该语言并写一条日志，后者退回用语言代码当显示名。

    :param builtin: 内置语言 ``((代码, 显示名), ...)``
    :return: 合并排序后的 ``((代码, 显示名), ...)``
    """
    families = []                       # 内置语言的语系顺序，如 ['zh', 'en']
    for code, _name in builtin:
        base = base_code(code)
        if base not in families:
            families.append(base)

    builtin_codes = {code for code, _name in builtin}
    entries = [(code, name, True) for code, name in builtin]

    for lang_file in sorted(LANG_PATH.glob("*.json")):
        code = lang_file.stem
        if code in builtin_codes:
            continue
        try:
            with open(lang_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.log(f"加载语言文件 {code} 失败: {e}", "ERROR")
            continue
        if not isinstance(data, dict) or not data:
            logger.log(f"语言文件格式不正确，已忽略: {lang_file}", "WARN")
            continue

        section = data.get("lang")
        name = section.get("name") if isinstance(section, dict) else None
        if not isinstance(name, str) or not name.strip():
            name = code                 # 没写 lang.name 就退回语言代码，至少菜单里认得出来
        entries.append((code, name.strip(), False))

    def order(entry):
        """同语系里内置语言排前面：zh_CN 在 zh_TW 之前，发现的排末尾"""
        code, _name, is_builtin = entry
        base = base_code(code)
        family = families.index(base) if base in families else len(families)
        return (family, 0 if is_builtin else 1, code)

    return tuple((code, name) for code, name, _flag in sorted(entries, key=order))


# 全部可用语言：内置语言 + lang/ 目录里自动发现的语言
LANGUAGES = discover_languages()

# 点号路径分隔符
SEPARATOR = "."


class LanguageManager:
    """语言文件的加载、查询与切换。"""

    def __init__(self, lang_code=DEFAULT_LANG):
        self.lang_path = LANG_PATH
        self.languages = dict(LANGUAGES)
        self.translations = {}
        self.missing_keys = set()
        self.language = lang_code
        self.load_translations()

    # ---------------- 加载 ----------------

    def load_translations(self):
        """读取所有语言文件到内存，缺失的会先写出一份骨架文件"""
        for lang_code in self.languages:
            lang_file = self.lang_path / f"{lang_code}.json"
            if not lang_file.exists():
                self.create_default_language_file(lang_code)

            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.translations[lang_code] = data if isinstance(data, dict) else {}
            except Exception as e:
                logger.log(f"加载语言文件 {lang_code} 失败: {e}", "ERROR")
                self.translations[lang_code] = {}

        # 当前语言的文件坏了就退回默认语言，避免界面全是键名
        if not self.translations.get(self.language) and self.language != DEFAULT_LANG:
            self.language = DEFAULT_LANG

    def create_default_language_file(self, lang_code):
        """语言文件丢失时写出一份最小骨架（正常安装包里不会走到这里）"""
        skeleton = {
            "lang": {"name": dict(LANGUAGES).get(lang_code, lang_code),
                     "code": lang_code},
            "app": {"name": PROJECT_NAME},
        }
        lang_file = self.lang_path / f"{lang_code}.json"
        try:
            self.lang_path.mkdir(parents=True, exist_ok=True)
            with open(lang_file, 'w', encoding='utf-8') as f:
                json.dump(skeleton, f, ensure_ascii=False, indent=2)
            self.translations[lang_code] = skeleton
            logger.log(f"语言文件不存在，已生成占位文件: {lang_file}", "WARN")
        except Exception as e:
            logger.log(f"创建语言文件 {lang_code} 失败: {e}", "ERROR")

    # ---------------- 语言列表与切换 ----------------

    def available_languages(self):
        """``{语言代码: 显示名}``，顺序与 :data:`LANGUAGES` 一致"""
        return dict(self.languages)

    def language_name(self, lang_code):
        """语言代码对应的显示名（未知代码原样返回）"""
        return self.languages.get(lang_code, lang_code)

    def set_language(self, lang_code):
        """切换当前语言，返回是否切换成功"""
        if lang_code not in self.languages:
            logger.log(f"未知的语言代码: {lang_code}", "WARN")
            return False
        if not self.translations.get(lang_code):
            logger.log(f"语言文件为空，无法切换: {lang_code}", "WARN")
            return False

        if lang_code == self.language:
            # 重复设置同一种语言（例如启动时按配置初始化）不再写日志，避免重复输出
            return True

        self.language = lang_code
        logger.log(f"界面语言已切换为: {self.language_name(lang_code)}（{lang_code}）")
        return True

    # ---------------- 查词 ----------------

    @staticmethod
    def _resolve(data, key):
        """在嵌套字典里按键取值，取不到返回 ``None``"""
        if not isinstance(data, dict) or not key:
            return None

        # 兼容扁平写法：整个键本身就是字典里的一级键
        if key in data:
            return data[key]

        node = data
        for part in key.split(SEPARATOR):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def lookup(self, key, lang_code=None):
        """按键取值（不做格式化），缺键返回 ``None``"""
        lang_code = lang_code or self.language
        for candidate in (lang_code, DEFAULT_LANG):
            value = self._resolve(self.translations.get(candidate), key)
            if value is not None:
                return value
        return None

    def has(self, key, lang_code=None):
        """该键在当前语言（或默认语言）里是否存在"""
        return self.lookup(key, lang_code) is not None

    def tr(self, key, default=None, lang_code=None, **kwargs):
        """按键取文案，并可选地用 ``str.format`` 填充占位符。

        :param key: 点号路径，如 ``"menu.open_file"``
        :param default: 缺键时的回退文案（不给就返回 ``key``）
        :param lang_code: 指定语言（默认当前语言）
        :param kwargs: 占位符的值，如 ``error="..."``
        """
        value = self.lookup(key, lang_code)
        if value is None:
            self.missing_keys.add(key)
            if default is None:
                return key
            value = default

        text = value if isinstance(value, str) else str(value)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError) as e:
                logger.log(f"语言文案格式化失败: {key} - {e}", "WARN")
        return text
