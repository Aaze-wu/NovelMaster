#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NovelMaster 程序入口。

实现代码已经按职责拆分到 :mod:`enm` 包中：

============================  ====================================
``enm.constants``             全局常量与资源路径
``enm.logger``                日志
``enm.managers``              配置 / 阅读进度 / 主题 / 语言
``enm.readers``               各格式阅读器、格式注册表与工厂
``enm.ui``                    主窗口与对话框
============================  ====================================

运行方式::

    python NovelMaster.py                # 正常启动
    python NovelMaster.py --debug        # 打开调试日志
"""

import sys


def main():
    # 单实例守卫放在最前面，顺序不能挪：
    #   1. 早于 QApplication —— 第二个实例连窗口都不该建；
    #   2. 早于任何 enm 导入 —— ``enm/__init__`` 会连带导入 ``enm.constants``，
    #      而后者在**导入期**就做旧数据目录迁移和建目录，那些副作用不能让
    #      一个马上就要退出的进程去碰。
    # 下面几个 import 因此都写在函数里，而不是模块顶部。
    from single_instance import SingleInstance

    guard = SingleInstance()
    if not guard.claim():
        # 已经有一个实例在跑：把它叫回前台，然后安静退出
        guard.wake_primary()
        sys.exit(0)

    from PyQt5.QtWidgets import QApplication

    from enm.constants import AUTHOR_NAME, PROJECT_NAME, VERSION
    from enm.logger import logger
    from enm.ui.main_window import NovelMaster

    app = QApplication(sys.argv)

    # 设置应用程序信息
    app.setApplicationName(PROJECT_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName(AUTHOR_NAME)

    # 创建主窗口
    window = NovelMaster()
    window.show()

    # 命名管道要等 QApplication 建好才开（Qt 的套接字通知器依赖事件分发器），
    # 之后每一次「又有人启动了本程序」都会把窗口叫回前台。
    def activate_existing():
        logger.log("检测到重复启动，唤回已有窗口")
        window.restore_and_activate()

    if not guard.serve(activate_existing):
        logger.log("单实例唤醒通道未能启动：再次启动本程序不会唤回已有窗口", "WARN")

    # 运行应用程序
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
