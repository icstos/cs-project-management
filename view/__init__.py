"""视图层：纯 Flet 组件渲染与事件分发。

本层只认识 :mod:`flet`、:mod:`models`、:mod:`viewmodel` 与自身的构件模块，
**不导入** :mod:`service` / :mod:`infra` —— 界面因此不感知任何业务规则与技术实现，
只负责"把状态画出来"和"把动作转给视图模型"。

* :mod:`view.design` —— 设计令牌与全局主题
* :mod:`view.widgets` —— 通用构件（按钮、卡片、标签、弹窗…）
* :mod:`view.view_platform` —— 剪贴板/文件选择器/快捷键的接入钩子
* :mod:`view.guard` —— 渲染错误边界
* :mod:`view.app` —— 应用外壳与四个页面
"""

from view.app import App, AppShell

__all__ = ["App", "AppShell"]
