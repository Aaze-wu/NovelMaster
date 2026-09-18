"""主题管理器对话框：一个地方管完所有主题。

以前自定义主题只能「新建/导入」，建完就再也选不到——主题菜单里只有浅色和
深色两项，删也没法删（``ThemeManager.delete_theme`` 根本没有调用者）。这个
对话框把这些补齐：列表 + 实时预览 + 新建 / 修改 / 复制 / 重命名 / 删除 /
导入 / 导出，内置主题只读（不能改、不能删）。

约定：对话框自己不落盘、也不改主窗口，只在 ``applied_theme`` 里留下「关闭后
该应用哪套主题」，由主窗口统一处理。

``titlebar_theme`` 为空 = 不给原生标题栏上色（对应「标题栏跟随主题」关闭）；
预览区会按主题自带的排版画字号 / 行距，没带的就用 ``font_family`` /
``font_size`` / ``line_spacing`` 几个参数里的当前全局设置。
"""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                             QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QVBoxLayout, QWidget)

from .. import i18n
from ..managers.theme import DEFAULT_THEME, sanitize_theme_name
from .theme_dialog import (ThemeEditorDialog, ThemePreviewWidget,
                           describe_theme_errors, theme_display_label)
from .theme_qss import build_style_sheet
from .titlebar import apply_to_widget


def _has_code(errors, code):
    """错误列表里是否有某个错误码"""
    return any(item_code == code for item_code, _ in errors)


class ThemeManagerDialog(QDialog):
    """主题管理：列表、预览、新建、修改、复制、重命名、删除、导入、导出"""

    def __init__(self, manager, current_theme, parent=None, ui_theme=None,
                 titlebar_theme=None, font_family=None, font_size=None,
                 line_spacing=None):
        super().__init__(parent)
        self.manager = manager
        self.current_theme = current_theme
        #: 关闭对话框后主窗口需要应用的主题；None 表示不用动
        self.applied_theme = None
        #: 本对话框自己的标题栏用哪套配色（showEvent 里才会真正套上去）
        self._titlebar_theme = titlebar_theme
        #: 新建主题时「排版」组的默认值（一般来自当前阅读设置）
        self._typography_defaults = {
            "font_family": font_family,
            "font_size": font_size,
            "line_spacing": line_spacing,
        }

        if ui_theme:
            self.setStyleSheet(build_style_sheet(ui_theme))

        self.setWindowTitle(i18n.t("theme_manager.title"))
        self.setModal(True)
        self.setMinimumSize(760, 500)
        self.setup_ui()
        self.refresh_list(select=current_theme)

    def showEvent(self, event):
        """窗口真正显示之后才给标题栏上色（此刻 winId 才拿到有效句柄）"""
        super().showEvent(event)
        apply_to_widget(self, self._titlebar_theme)

    def open_editor(self, theme=None, name=""):
        """统一构造主题编辑器（外壳配色 / 标题栏配色 / 排版默认值一起递进去）"""
        return ThemeEditorDialog(
            self.manager, theme=theme, name=name, parent=self,
            ui_theme=self.manager.get_theme(self.current_theme),
            titlebar_theme=self._titlebar_theme,
            **self._typography_defaults)

    # ------------------------------------------------------------------ 界面

    def setup_ui(self):
        """搭界面"""
        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(220)
        self.list_widget.currentItemChanged.connect(self.on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self.on_item_activated)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel(i18n.t("theme_manager.list_label")))
        left_layout.addWidget(self.list_widget, 1)

        self.selected_label = QLabel()
        self.preview = ThemePreviewWidget()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.selected_label)
        right_layout.addWidget(self.preview, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(left)
        body.addWidget(right, 1)

        # 操作按钮
        self.apply_btn = QPushButton(i18n.t("theme_manager.apply"))
        self.apply_btn.clicked.connect(self.apply_selected)
        self.new_btn = QPushButton(i18n.t("theme_manager.new"))
        self.new_btn.clicked.connect(self.create_theme)
        self.edit_btn = QPushButton(i18n.t("theme_manager.edit"))
        self.edit_btn.clicked.connect(self.edit_theme)
        self.copy_btn = QPushButton(i18n.t("theme_manager.duplicate"))
        self.copy_btn.clicked.connect(self.duplicate_theme)
        self.rename_btn = QPushButton(i18n.t("theme_manager.rename"))
        self.rename_btn.clicked.connect(self.rename_theme)
        self.delete_btn = QPushButton(i18n.t("theme_manager.delete"))
        self.delete_btn.clicked.connect(self.delete_theme)
        self.import_btn = QPushButton(i18n.t("theme_manager.import"))
        self.import_btn.clicked.connect(self.import_theme)
        self.export_btn = QPushButton(i18n.t("theme_manager.export"))
        self.export_btn.clicked.connect(self.export_theme)

        actions = QGridLayout()
        actions.setSpacing(6)
        for index, button in enumerate((self.apply_btn, self.new_btn, self.edit_btn,
                                        self.copy_btn, self.rename_btn,
                                        self.delete_btn, self.import_btn,
                                        self.export_btn)):
            actions.addWidget(button, index // 4, index % 4)

        hint = QLabel(i18n.t("theme_manager.hint"))
        hint.setWordWrap(True)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.button(QDialogButtonBox.Close).setText(i18n.t("common.close"))
        button_box.rejected.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(body, 1)
        layout.addLayout(actions)
        layout.addWidget(hint)
        layout.addWidget(button_box)

        self.on_selection_changed()

    def refresh_list(self, select=None):
        """重建列表（内置主题一组、自定义主题一组）"""
        target = select or self.current_theme
        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        for is_builtin in (True, False):
            names = (list(self.manager.builtin_themes) if is_builtin
                     else self.manager.custom_theme_names())
            header = QListWidgetItem(i18n.t(
                "theme_manager.group_builtin" if is_builtin
                else "theme_manager.group_custom"))
            header.setFlags(Qt.ItemIsEnabled)
            self.list_widget.addItem(header)

            if not names:
                empty = QListWidgetItem(i18n.t("theme_manager.no_custom"))
                empty.setFlags(Qt.ItemIsEnabled)
                self.list_widget.addItem(empty)
                continue

            for name in names:
                text = theme_display_label(self.manager, name, is_builtin)
                if name == self.current_theme:
                    text += " " + i18n.t("theme_manager.current_suffix")
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, name)
                item.setData(Qt.UserRole + 1, is_builtin)
                self.list_widget.addItem(item)
                if name == target:
                    self.list_widget.setCurrentItem(item)

        self.list_widget.blockSignals(False)
        self.on_selection_changed()

    def selected(self):
        """当前选中的 ``(主题键, 是否内置)``；分组标题上返回 ``None``"""
        item = self.list_widget.currentItem()
        if item is None:
            return None
        name = item.data(Qt.UserRole)
        if name is None:
            return None
        return name, bool(item.data(Qt.UserRole + 1))

    def on_selection_changed(self, *_args):
        """选中项变了：刷新预览与按钮可用状态"""
        info = self.selected()
        if info is None:
            self.selected_label.setText("")
            self.apply_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            self.copy_btn.setEnabled(False)
            self.rename_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            return

        name, is_builtin = info
        self.selected_label.setText(theme_display_label(self.manager, name, is_builtin))
        theme = self.manager.get_theme(name)
        # 主题自带排版时预览也按它的字号 / 行距画，否则看起来会比实际差一截
        self.preview.set_theme(
            theme,
            font_size=(theme.get("font_size")
                       or self._typography_defaults.get("font_size")),
            line_spacing=(theme.get("line_spacing")
                          or self._typography_defaults.get("line_spacing")))
        self.apply_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        # 内置主题只读：没有对应的文件可以改，也没得删
        self.edit_btn.setEnabled(not is_builtin)
        self.rename_btn.setEnabled(not is_builtin)
        self.delete_btn.setEnabled(not is_builtin)

    def on_item_activated(self, _item):
        """双击条目直接应用"""
        self.apply_selected()

    # ------------------------------------------------------------------ 操作

    def apply_selected(self):
        """把选中主题定为「关闭后应用」"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        self.applied_theme = info[0]
        self.current_theme = info[0]
        self.refresh_list(select=info[0])

    def create_theme(self):
        """新建主题"""
        editor = self.open_editor()
        if editor.exec_() != QDialog.Accepted:
            return

        theme = editor.get_theme_data()
        if theme is None:
            return
        key = sanitize_theme_name(theme["name"])
        if self.manager.is_custom(key) and not self.confirm_overwrite(key):
            return

        ok, errors, _ = self.manager.save_theme(key, theme, overwrite=True)
        if not ok:
            self.show_errors(errors)
            return
        self.refresh_list(select=key)
        self.info(i18n.t("theme_manager.saved", name=theme["name"]))

    def edit_theme(self):
        """修改选中主题（改名也算修改）"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        name, is_builtin = info
        if is_builtin:
            self.warn(i18n.t("theme_manager.builtin_readonly"))
            return

        editor = self.open_editor(theme=self.manager.get_theme(name), name=name)
        if editor.exec_() != QDialog.Accepted:
            return

        theme = editor.get_theme_data()
        if theme is None:
            return
        new_key = sanitize_theme_name(theme["name"])
        if new_key != name:
            if self.manager.exists(new_key) and not self.confirm_overwrite(new_key):
                return
            ok, errors, _ = self.manager.save_theme(new_key, theme, overwrite=True)
            if not ok:
                self.show_errors(errors)
                return
            self.manager.delete_theme(name)
        else:
            ok, errors, _ = self.manager.save_theme(name, theme, overwrite=True)
            if not ok:
                self.show_errors(errors)
                return

        if name == self.current_theme:
            # 正在用的主题被改名了，配置也得跟着走，否则下次启动就找不到
            self.current_theme = new_key
            self.applied_theme = new_key
        self.refresh_list(select=new_key)
        self.info(i18n.t("theme_manager.saved", name=theme["name"]))

    def duplicate_theme(self):
        """复制主题（内置主题也能复制成自定义主题）"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        name, is_builtin = info
        base = i18n.t("theme_manager.copy_suffix",
                      name=theme_display_label(self.manager, name, is_builtin))
        new_name, accepted = QInputDialog.getText(
            self, i18n.t("theme_manager.duplicate_title"),
            i18n.t("theme_manager.duplicate_label"),
            text=self.manager.next_available_name(base))
        if not accepted or not new_name.strip():
            return

        ok, new_key, errors = self.manager.duplicate_theme(name, new_name.strip())
        if not ok:
            self.show_errors(errors)
            return
        self.refresh_list(select=new_key)
        self.info(i18n.t("theme_manager.duplicate_done",
                         name=theme_display_label(self.manager, new_key)))

    def rename_theme(self):
        """重命名主题"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        name, is_builtin = info
        if is_builtin:
            self.warn(i18n.t("theme_manager.builtin_readonly"))
            return

        new_name, accepted = QInputDialog.getText(
            self, i18n.t("theme_manager.rename_title"),
            i18n.t("theme_manager.rename_label"),
            text=self.manager.display_name(name))
        if not accepted or not new_name.strip():
            return

        ok, new_key, errors = self.manager.rename_theme(name, new_name.strip())
        if not ok:
            self.show_errors(errors)
            return
        if name == self.current_theme:
            self.current_theme = new_key
            self.applied_theme = new_key
        self.refresh_list(select=new_key)
        self.info(i18n.t("theme_manager.rename_done",
                         name=theme_display_label(self.manager, new_key)))

    def delete_theme(self):
        """删除主题（要确认；删的是正在用的主题就退回默认主题）"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        name, is_builtin = info
        if is_builtin:
            self.warn(i18n.t("theme_manager.builtin_readonly"))
            return

        label = theme_display_label(self.manager, name, is_builtin)
        answer = QMessageBox.question(
            self, i18n.t("theme_manager.delete_title"),
            i18n.t("theme_manager.delete_confirm", name=label),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        if not self.manager.delete_theme(name):
            self.show_errors([("theme_error.write_failed", {"error": name})])
            return

        if name == self.current_theme:
            self.current_theme = DEFAULT_THEME
            self.applied_theme = DEFAULT_THEME
        self.refresh_list(select=DEFAULT_THEME)
        self.info(i18n.t("theme_manager.delete_done", name=label))

    def import_theme(self):
        """从 JSON 文件导入主题（严格校验，坏文件直接说清楚哪儿不对）"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("dialog.import_theme"), "", i18n.t("common.theme_file_filter"))
        if not file_path:
            return

        ok, key, errors, _ = self.manager.import_theme_file(file_path)
        if not ok and _has_code(errors, "theme_error.name_exists"):
            if not self.confirm_overwrite(key):
                return
            ok, key, errors, _ = self.manager.import_theme_file(file_path, overwrite=True)
        if not ok and _has_code(errors, "theme_error.reserved_name"):
            # 内置主题名占了就不能用，让用户换个名字，免得导入了一个永远选不到的主题
            new_name, accepted = QInputDialog.getText(
                self, i18n.t("theme_manager.rename_title"),
                i18n.t("theme_manager.rename_label"),
                text=self.manager.next_available_name(Path(file_path).stem))
            if not accepted or not new_name.strip():
                return
            ok, key, errors, _ = self.manager.import_theme_file(
                file_path, name=new_name.strip())
        if not ok:
            self.show_errors(errors)
            return

        self.refresh_list(select=key)
        self.info(i18n.t("theme_manager.imported",
                         name=theme_display_label(self.manager, key)))

    def export_theme(self):
        """把选中主题导出成 JSON（内置主题也能导出，方便照着改）"""
        info = self.selected()
        if info is None:
            self.warn(i18n.t("theme_manager.no_selection"))
            return
        name, is_builtin = info
        label = theme_display_label(self.manager, name, is_builtin)

        file_path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("dialog.export_theme"), f"{label}.json",
            i18n.t("common.theme_file_filter"))
        if not file_path:
            return

        ok, errors = self.manager.export_theme_file(name, file_path, display_name=label)
        if not ok:
            self.show_errors(errors)
            return
        self.info(i18n.t("theme_manager.exported", path=file_path))

    # ------------------------------------------------------------ 提示与确认

    def confirm_overwrite(self, name):
        """问一句要不要覆盖同名主题"""
        answer = QMessageBox.question(
            self, i18n.t("theme_manager.overwrite_title"),
            i18n.t("theme_manager.overwrite_confirm", name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def warn(self, message):
        """提示（带标题）"""
        QMessageBox.warning(self, i18n.t("common.warning"), message)

    def info(self, message):
        """成功提示"""
        QMessageBox.information(self, i18n.t("common.success"), message)

    def show_errors(self, errors):
        """把校验错误原样翻译出来，别只说一句「失败」"""
        QMessageBox.critical(self, i18n.t("common.error"),
                             describe_theme_errors(errors))
