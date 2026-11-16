"""视图模型层：持有界面状态，中转业务调用，驱动重渲染。

本层不出现任何 flet 控件 —— 需要界面配合的事情（剪贴板、系统目录选择、
保存文件、键盘事件）都以 :class:`~cs_pm.viewmodel.base.PlatformRequest` /
:class:`~cs_pm.viewmodel.base.Shortcut` 的形式进出，因此视图模型可以脱离界面单独测试。

* :class:`~cs_pm.viewmodel.app_vm.AppViewModel` —— 外壳：页签、全局项目列表、快捷键
* :class:`~cs_pm.viewmodel.projects_vm.ProjectsViewModel` —— 项目台账的增删改查与筛选
* :class:`~cs_pm.viewmodel.commit_vm.CommitViewModel` —— 提交与推送
* :class:`~cs_pm.viewmodel.reports_vm.ReportsViewModel` —— 统计与导出
* :class:`~cs_pm.viewmodel.build_vm.BuildViewModel` —— 打包
"""

from cs_pm.viewmodel.app_vm import AppState, AppViewModel, Tab
from cs_pm.viewmodel.base import (
    Notice,
    PlatformAction,
    PlatformRequest,
    Shortcut,
    ViewModel,
)

__all__ = [
    "AppState",
    "AppViewModel",
    "Notice",
    "PlatformAction",
    "PlatformRequest",
    "Shortcut",
    "Tab",
    "ViewModel",
]
