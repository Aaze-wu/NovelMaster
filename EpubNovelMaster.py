#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EpubNovelMaster 程序入口。

实现代码已经按职责拆分到 :mod:`enm` 包中：

============================  ====================================
``enm.constants``             全局常量与资源路径
``enm.logger``                日志
``enm.managers``              配置 / 阅读进度 / 主题 / 语言
``enm.readers``               各格式阅读器、格式注册表与工厂
``enm.ui``                    主窗口与对话框
============================  ====================================

运行方式::

    python EpubNovelMaster.py            # 正常启动
    python EpubNovelMaster.py --debug    # 打开调试日志
"""

import sys

from PyQt5.QtWidgets import QApplication

from enm.constants import AUTHOR_NAME, PROJECT_NAME, VERSION
from enm.ui.main_window import EpubNovelMaster


def main():
    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName(PROJECT_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName(AUTHOR_NAME)

    # 创建主窗口
    window = EpubNovelMaster()
    window.show()

    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
