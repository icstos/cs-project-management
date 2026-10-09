"""服务层：编排核心业务流程。

只依赖 :mod:`infra.ports` 里的抽象接口，不感知 SQLite、subprocess、git 命令行
或 flet CLI 的存在；对上层只暴露异步方法与 models 层的不可变对象。

* :class:`~service.project_service.ProjectService` —— 台账维护与仓库状态探测
* :class:`~service.commit_service.CommitService` —— 预览、提交与推送
* :class:`~service.report_service.ReportService` —— 历史采集与统计聚合
* :class:`~service.build_service.BuildService` —— 打包参数推导、体检与执行
"""

from service.build_service import BuildService
from service.commit_service import CommitService
from service.project_service import ProjectService
from service.report_service import ReportService

__all__ = ["BuildService", "CommitService", "ProjectService", "ReportService"]
