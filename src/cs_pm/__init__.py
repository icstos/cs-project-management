"""cs-project-management 的应用包。

五层结构统一收在此包之下：:mod:`cs_pm.models`（数据模型）、
:mod:`cs_pm.infra`（基础设施）、:mod:`cs_pm.service`（业务服务）、
:mod:`cs_pm.viewmodel`（界面状态）与 :mod:`cs_pm.view`（界面）。

只放文档、不做重导出：``cs_pm.infra`` 导入时会连数据库，统一入口会
把这份副作用带给所有使用者。src 布局因此只有一个顶层包，editable 安装
与隔离打包的路径配置都收敛到一处。
"""
