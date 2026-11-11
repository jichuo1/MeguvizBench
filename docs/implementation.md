# 实施计划

| 阶段 | 交付与验收 | 进度 |
| --- | --- | --- |
| 1 | 空目录建工程，固定协议、依赖、命令入口 | 本地已验证 |
| 2 | 干净起点、提交、独立验收、分项成绩、证据保留和重算 | 本地闭环与 GitHub Docker 公开校验通过 |
| 3 | 参考解通过，错误对照和 Bug 原始状态被拒绝 | 基础六题与进阶三题均通过本地与托管对照 |
| 4 | 零预算 CI、手动矩阵、私有存取、发布字段限制 | 公开 Actions、Docker 探针与 Harbor smoke 通过，私有归档待验收 |
| 5 | 家族等权汇总、八维覆盖、区间、Pages 静态产物 | 已部署公开 Pages，Edge 实测通过 |
| 6 | 经许可从固定项目快照抽取真实任务，记录曝光和脱敏依据 | 等待任务材料与授权 |
| 7 | 两个真实模型配置在六家族各独立重复两次，共 24 次 | 等待真实 API、归档与预算授权 |

2026-11-11 初检发现工作区为空，未配置 Git 仓库及远端。Windows Python 3.13.15、uv 0.12.3 和 Node.js 可用。Docker CLI 缺失，WSL 没有可用发行版。核心平台用 Python 标准库。

## 首轮本地验证

| 验证 | 结果及工作区证据 |
| --- | --- |
| 六题平台闭环 | `.bench/final-validation-20261111/` 包含计划、12 个对照试次、两项无改动检查、分项证据和公开站点。六个 oracle 均为 100 分，wrong 为 49–75 分，两个原始 Bug 提交为 49、21 分。CLI 重算区间错误对照，与原记录一致，原始 85 分、封顶 75 分。 |
| 协议与防投机 | 11 项离线测试通过，包括额外奖励文件、路径校验、预算、API 响应与用量、归档只创建、摘要恢复、超时、家族权重和脱敏。私有 API 和归档采用离线替身测试。 |
| 工作流 | 4 个 YAML 解析和命令参数边界静态通过。本地实际生成矩阵、合并公开对照证据、导出并构建站点。真实 GitHub job 待运行。 |
| 页面 | Edge 实测桌面 1360 px 与移动 420 px，另测主题切换、类型筛选、空页、缺测、暂定批次与错误状态。最终截图和日志位于 `.bench/browser-check-20261111/`，文件名含 `final`。 |
| Harbor | 初次安装受系统临时目录写权限和 PyPI DNS 阻碍。将缓存、工具和临时目录移入工作区后，通过联网重试安装 0.25.0。版本及 CLI 帮助、真实 Task 加载和独立验收模式配置检查通过。Docker CLI 缺失使运行在预检阶段停止。证据位于 `.bench/harbor-cli-20261111/`。 |
| 试跑 | 两配置各重复两次的 24 个试次只生成计划，见 `.bench/dry-plan-final-20261111.json`。真实模型调用和支付为零。 |

受保护环境启用后，再验证专用私有仓库的权限、恢复和模型 API。导入正式任务前须确定任务快照、参考解授权、脱敏和 API 数据处理边界。

## 首次托管运行

2026-11-11，公开仓库在 `main` 上完成 Docker 校验与 Harbor 0.25.0 smoke。Harbor 的公开 SVG oracle 通过独立验收并回传提交产物，reward 为 1。公开六题在零预算矩阵完成 12 个对照试次，脱敏报告已发布到 Pages。 [公开仓库](https://github.com/jichuo1/MeguvizBench) · [Docker 与 Harbor](https://github.com/jichuo1/MeguvizBench/actions/runs/43009594941) · [六题矩阵](https://github.com/jichuo1/MeguvizBench/actions/runs/43009600036) · [首次 Pages 部署](https://github.com/jichuo1/MeguvizBench/actions/runs/43009968336)

三道进阶题的六个对照也在 GitHub Docker 中实跑，分项累计和封顶结果与本地一致。参考解均为 100 分，Arena、帧协调和交付监督的错误对照分别为 68、59、65 分。 [进阶题矩阵](https://github.com/jichuo1/MeguvizBench/actions/runs/43010547516) · [进阶题说明](../tasks/challenges/README.md)

`results/public/history.json` 保存两套经校验的公开成绩，共 18 个对照试次。每套题集保留各自版本和可比组。当前运行预算为零，私有材料未接入。 [公开 Pages](https://jichuo1.github.io/MeguvizBench/)
