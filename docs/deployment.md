# GitHub Actions 与 Pages 部署

## 资源与规则核对

官方文档核对日期为 2026-11-11（北京时间）。

| 项目 | 核对结果 |
| --- | --- |
| 运行器 | 公开仓库的标准 `ubuntu-24.04` x64 虚拟机为 4 vCPU、16 GB RAM、14 GB 磁盘。私有仓库同标签的规格为 2 vCPU、8 GB RAM、14 GB 磁盘。任务里记录的镜像与工具版本仍是成绩比较条件。 [托管运行器](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) |
| 上限 | GitHub 托管 job 最长 6 小时，单矩阵上限 256 个 job，workflow 最长 35 天并计入等待时间。标准 runner 并发因套餐而异，Free 为 20。首版每批最多 128 个试次，同时执行最多 2 个。 [Actions 限制](https://docs.github.com/en/actions/reference/limits) |
| 费用 | 标准托管 runner 用于公开仓库和 Pages 的计算免费。私有仓库标准计算用量从套餐额度扣除。Artifacts 和缓存另按存储规则计量。模型供应商费用独立，免费 runner 与评测预算分别核算。 [Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| 权限 | 工作流按 job 授权。checkout 关闭凭据持久化，外部 PR 走 `pull_request`。第三方 Action 引用固定到完整提交 SHA，付费 job 依靠受保护环境和默认分支约束。 [安全使用 Actions](https://docs.github.com/en/actions/reference/security/secure-use) · [checkout](https://github.com/actions/checkout) · [环境保护](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments) |
| Pages | 站点由 Actions 构建静态文件。只有部署 job 拥有 `pages: write` 和 `id-token: write`，部署绑定 `github-pages` 环境。 [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) · [自定义发布流程](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) |

工作流采用固定版本的官方 Actions。升级时从 release 页面对应的 commit 链接核对完整 SHA。 [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) · [setup-python v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0) · [upload-artifact v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) · [download-artifact v8.0.2](https://github.com/actions/download-artifact/releases/tag/v8.0.2) · [upload-pages-artifact v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0) · [deploy-pages v5.0.1](https://github.com/actions/deploy-pages/releases/tag/v5.0.1)

## 首次启用

1. 选定已授权的公开 GitHub 仓库与默认分支，将源码和工作流提交到该分支。核对 `Settings → Actions` 允许使用固定的官方 Actions。默认分支应受保护，并要求评审工作流、任务加载、验收及归档改动。
2. 先检查 `公开校验`。它在 push 和 PR 上验证协议、运行离线测试及 Docker 公开对照，模型预算为零。公开对照经 `基准评测` 手动矩阵运行时可选择 `platform_validation`、`public-six`、`controls`、`zero`，再填写运行键和重复次数。公开对照环境 `benchmark-public` 留空。
3. 进入 `Settings → Pages`，将来源设置为 `GitHub Actions`。保护 `github-pages` 环境，只允许默认分支部署。运行 `发布排行榜` 后，在对应 job 环境链接打开页面并核对 `data.json`、分组、覆盖率和缺测标记。

`公开校验` 的手动入口提供 `harbor_smoke` 选项。启用后在独立的临时虚拟环境安装 Harbor 候选版本 `0.25.0`，通过 Harbor CLI 运行公开 SVG 的 oracle 与独立验收，检查产物回传和评分记录。该 job 依赖 PyPI 与 Docker 可用。候选版本尚待托管 smoke 验证，常规 CI 和预算受控评测当前走直接 Docker 路径。 [Harbor 0.25.0](https://pypi.org/project/harbor/0.25.0/) · [独立验收环境](https://docs.harborframework.com/tasks/separate-verifier)

## 受保护的模型评测

在公开框架仓库创建 `benchmark-protected` 环境。限定默认分支，设置指定评审者并禁止跳过保护规则。下表各项均使用环境 Secrets，使 GitHub 在公开日志中遮蔽凭据与私有仓库元数据。GitHub 会为未配置的环境名自动创建无保护环境，因此环境必须先由管理员配置，再加入凭据。 [环境保护配置](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

| 配置 | 类型 | 用途 |
| --- | --- | --- |
| `OPENAI_API_KEY` | Secret | 受信模型适配器使用，采用独立项目及供应商侧额度。 |
| `BENCH_EVIDENCE_REPO` | Secret | 专用私有证据仓库，写作 `owner/name`。先初始化默认分支，保留私有可见性。 |
| `BENCH_EVIDENCE_TOKEN` | Secret | 仅限上述证据仓库的细粒度 Contents 读写凭据。默认分支须允许该身份追加证据。 |
| `BENCH_TASKS_REPO` | Secret | 正式评测的独立私有题库快照仓库。 |
| `BENCH_TASKS_REF` | Secret | 审核后的完整 40 位任务快照提交 SHA。 |
| `BENCH_TASKS_TOKEN` | Secret | 仅限上述题库快照仓库的细粒度 Contents 只读凭据。 |

试跑使用 `pilot`、`public-six`、`pilot-two`、`pilot` 预算和 `2` 次重复，共 24 个试次。它只需前三项配置，维护者须先核对预算档、供应商价格与账户中的模型可用性。正式评测使用 `official`、`private`、已审核的模型组与正预算。只有正式模式读取题库仓库。私有仓库的 `tasks/<task-id>/` 使用与公开样例相同的任务包结构，包含 `task.json`、`prompt.md`、`checks.py`、`starter/`、`oracle/` 和 `wrong/`。正式题的状态设为 `active`，固定来源版本和评分器版本，题库快照只存本轮获授权使用的材料。

维护者通过 `workflow_dispatch` 在默认分支启动评测，指定本轮稳定 `run_key`。该输入在 Actions 可见，使用无敏感含义的短标识，例如 `pilot-20261111-01`。重新提交同一付费批次时保留原键，证据仓库中的原子占用会拒绝重复派发。GitHub 的整批重跑及失败 job 重跑均受付费运行限制，协议内的重试另建记录。先检查私有归档和供应商用量，再决定是否启动一轮新的独立评测。

计划冻结后，各 job 以相同框架提交和题库提交重建清单，检查 SHA-256 后再执行或恢复。矩阵只传试次 ID。当前示例按一个完整比较单元派发，超过 128 个试次须按模型配置拆开。36 家族、4 个模型、3 次重复可组织成 4 个单模型批次，每批 108 个试次，统一题集、预算、环境、评分器与重复规则后再比较。多个批次在同一并发组排队，各自核算预算，派发前须核对授权总额。试次 job 限时 25 分钟，模型本身由更短的试次时限和预算控制，留出验收和归档时间。 [工作流排队规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)

## 归档恢复与发布

付费试次在专用私有仓库写入按 `run_id`、`trial_id` 与尝试编号定位的记录。对象大小和路径由控制侧限制，读取时验证摘要。job 异常退出时，已成功写入的占用、预算预留或尝试记录仍可恢复。平台无法找回虚拟机强制终止前尚未归档的数据。缺少试次时汇总保留 `provisional`。

收集 job 从私有仓库恢复证据，按照冻结计划生成公开报告。框架提交中如有 `results/public/history.json`，收集时会合并经过校验的公开历史，并替换同一运行的旧公开行。公开 Actions 产物 `meguvizbench-public-results` 只包含经校验的 `data.json`，保留 7 天。公开校准另有受控对照证据，保留 3 天。付费运行的日志、提交物、题面、隐藏验收细节与私有归档始终在受信控制侧处理。workflow 不配置私有内容的 Actions 缓存。

发布时填写已审核的 `benchmark_run_id`。流程核对该运行来自同仓库默认分支上的手动 `基准评测`，读取公开产物并再校验一次。也可以把已审核的公开历史报告提交到 `results/public/history.json`，再留空 `benchmark_run_id` 发布。两个输入源各自应包含本次要展示的完整报告。第一次发布缺少任何报告时页面显示空状态。

维护者在私有环境中恢复证据，需使用原框架提交和清单。仅给恢复进程配置归档读取凭据，正式清单另传相同任务快照。以下是 Bash 示例，路径按实际存放位置修改。

```bash
export PYTHONPATH=src
python -m meguvizbench restore --plan /secure/run/plan.json --output /secure/run/restored \
  --private-tasks /secure/materials/tasks
python -m meguvizbench publish --plan /secure/run/plan.json --results /secure/run/restored \
  --private-tasks /secure/materials/tasks --output ./bench-public-site
python -m meguvizbench public-validate --input ./bench-public-site/data.json
```

## 运行故障

| 现象 | 排查 |
| --- | --- |
| job 显示跳过 | 核对派发 ref、默认分支、运行模式和 Actions 尝试编号。付费运行要求 GitHub 将本次 ref 标识为受保护。 [GitHub 上下文](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts) |
| 固定题库读取失败 | 核对仓库私有可见性、读取凭据及 40 位 SHA，确认该提交包含 `tasks/`。检查任务版本时保持试次使用同一份快照。 |
| 批次领取失败 | 核对保护规则、模型 Secret、证据仓库权限和可见性、Docker 和已有占用记录。公开日志只给阶段错误，必要时在可信工作区重做离线预检。 |
| 证据收集缺项 | 恢复已有记录并对照冻结清单，查看归档失败、超时、审批或取消状态。已领取的付费试次可能有未结算的在途费用。 |
| Pages 发布失败 | 检查 `Settings → Pages` 的 Actions 来源、`github-pages` 环境保护、输入运行编号和公开产物保留期。 |

本地协议与页面构建、Actions 运行、Docker 隔离、私有存取、模型试跑、Pages 实际部署分别验收。仓库中没有附实际 Actions run URL 或 Pages 地址时，以未取得对应托管证据为准。
