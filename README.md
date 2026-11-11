# MeguvizBench

面向软件工程、算法与验证任务的评测平台。基础与进阶题集共有九个公开任务家族和 100 个独立评分项。每个题包包含参考解、错误对照和起始文件。公开校准与真实模型评测分开显示。

[公开评测报告](https://jichuo1.github.io/MeguvizBench/)

## 本地运行

需要 Python 3.12+。Python 核心无第三方依赖。以下是 PowerShell 命令，在仓库根目录运行。

```powershell
$env:PYTHONPATH = 'src'
python -m meguvizbench doctor
python -m meguvizbench validate
python -m unittest discover -s tests -v
python -m meguvizbench self-check --backend local --output .bench/local-check
python -m http.server 8000 --directory .bench/local-check/site
```

在浏览器打开 [本地报告](http://localhost:8000)。每次自检使用一个新的输出目录。使用 uv 时可先执行 `uv lock --check`，再用 `uv run --locked python -m meguvizbench …` 替代同一环境中的 Python 命令。

`local` 只用于受信的公开内置对照，程序直接在本机 Python 子进程执行。具备 Linux Docker 时运行：

```bash
export PYTHONPATH=src
python -m meguvizbench self-check --backend docker --output .bench/docker-check
```

报告的 `checks.json` 是自检摘要，`evidence/` 保留每次试验的原始分、条目证据和封顶记录，`site/` 只含静态页面和脱敏数据。

原六题保留在 `public-six`。[进阶公开校准题](tasks/challenges/README.md)使用 `public-challenges`，覆盖跨页分配、交付恢复与帧协调。用同一条自检命令加上 `--taskset public-challenges` 并换一个输出目录即可运行。两个题集独立汇总。

## 手动评测

先用零预算的 `platform_validation` 检查托管环境。启用真实模型后，手动运行 GitHub Actions 的「基准评测」，选择 `pilot / public-six / pilot-two / 2 / pilot`，填写新的稳定运行键。该组合计划 24 个试次。私有正式题集另用 `official / private` 和经审核的私有任务快照。

部署、模型和私有归档配置见 [部署说明](docs/deployment.md)。现有题面、目录和对照结果见 [公开校准任务](tasks/examples/README.md)。分值、试次、预算、重评分及安全边界见 [评测协议](docs/protocol.md)。任务制作见 [任务制作指南](docs/task-authoring.md)。验证记录及未完成项见 [实施计划](docs/implementation.md)。
