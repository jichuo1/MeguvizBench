# 进阶公开校准题

`public-challenges` 从项目中遇到的工程问题抽取可公开的行为约束。题面、事件、输入与实现均为独立编写的合成材料。每道题有参考解、起始版本和能通过常规场景的错误对照。D4 是作者依据跨模块状态、边界和恢复条件给出的初始分级，等待独立模型运行校准。

| 题目 | 主维度 | 独立评分项 | 区分行为 |
| --- | --- | ---: | --- |
| [跨页 Arena 回放与扫描凭证](arena-frontier-replay/prompt.md) | 底层系统与性能 | 12 | 对齐与页顺序、复位后前缀失效、借用期间的回收和可复算的扫描量 |
| [交付监督与恢复](delivery-watchdog/prompt.md) | 后端与状态一致性 | 13 | 重复进度、超时边界、原尝试退出、内容摘要、远端回执和不确定状态 |
| [半透明面板帧调度](backdrop-frame-coordinator/prompt.md) | 前端与图形 | 14 | 在途探测、失败锁存、重绑、陈旧回执、绘制目标隔离和同源采样预算 |

分配题使用工作量凭证，图形题使用帧调度状态。当前这两类证据分别覆盖算法行为和调度策略。主机耗时、Android 真机帧率和视觉结果留待相应环境测量。零预算对照验证评分器能否发现组合缺陷，区分真实模型的能力差异需用独立模型试次估计。

```powershell
$env:PYTHONPATH = 'src'
python -m meguvizbench self-check --taskset public-challenges --backend local --output .bench/challenge-check
```
