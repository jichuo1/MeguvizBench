# 跨页 Arena 回放与扫描凭证

实现一个确定性的 Arena 模拟器。提交 `solution.py` 和 `arena.py`，仅使用 Python 标准库。程序读取一个 JSON 对象，输出一个 `{"events":[...]}`。不访问网络，不跨进程保留状态。

## 输入和状态

`pages` 是按发布顺序排列的 `[base, capacity]` 列表，可以为空。基址为非负整数，容量为正整数。页面的地址区间不重叠，基址可不对齐，发布顺序可以与地址顺序不同。每个页面起始游标为 0。`ops` 是按顺序执行的操作数组。输入保证操作名称、页面参数、参数个数和 ID 类型有效。只有 `alloc` 的尺寸、对齐参数可能不符合取值要求。

| 操作 | 成功事件和效果 | 其他事件 |
| --- | --- | --- |
| `["alloc", id, size, alignment]` | `{"status":"ok","page":i,"offset":p,"scan_from":k}`。按发布顺序找到第一个合适页面，取使 `(base+p) % alignment == 0` 且 `p >= cursor` 的最小偏移。仅在 `p + size <= capacity` 时可用。成功后游标为 `p + size`，ID 成为新所有者。 | 无合适页面时为 `{"status":"no_space","scan_from":k}`。尺寸须为正整数，对齐须为 1 至 256 的 2 的幂，布尔值不算整数。参数非法时返回 `invalid_shape`。形状有效但 ID 尚未完全排空时返回 `in_use`。 |
| `["pin", id]` | 活跃所有者增加一个借用，返回 `ok`。 | 所有者已释放但仍有借用时为 `not_live`，无该 ID 时为 `unknown`。 |
| `["release", id]` | 释放所有权，返回 `ok`。有借用时转为待排空，没有借用时立即删除 ID。游标不回退。 | 对待排空 ID 为 `not_live`，无该 ID 为 `unknown`。 |
| `["unpin", id]` | 归还一个借用，返回 `ok`。待排空 ID 的最后一个借用归还后删除 ID。 | ID 存在但没有借用时为 `not_pinned`，无该 ID 为 `unknown`。 |
| `["reset"]` | 当没有活跃或待排空 ID 时，将所有游标归零并清除扫描凭证，保留页面，返回 `ok`。 | 有活跃或待排空 ID 时返回 `busy`，任何状态均不变。 |
| `["append", base, capacity]` | 追加一个新页面，游标为 0，返回 `ok`。 | 输入保证与已有页面地址区间不重叠。 |
| `["inspect"]` | 返回 `{"status":"ok","cursors":[...],"live":N,"retiring":M,"pins":P}`，三个计数分别是活跃 ID 数、待排空 ID 数和借用总数。 | 无。 |

表中只写状态的事件返回 `{"status":"<对应状态>"}`。ID 是字符串。除成功分配和成功复位外，已有游标不会变化。每一步都需要输出事件。

## 扫描凭证

最近一次形状有效且 ID 可用的分配请求产生一个凭证 `(size, alignment, bound)`。成功时 `bound` 为选中的页面索引，无空间时为该次尝试时的页面数。这个凭证证明更早的页面都无法满足该形状。

新请求只有在尺寸与对齐**都不小于**该凭证的形状时，才应从其 `bound` 开始扫描，事件的 `scan_from` 等于该值。其他请求应从 0 开始。`scan_from` 记录此协议的扫描起点，与实际耗时无关。成功或无空间后用新请求的凭证替换旧值。非法形状、重复 ID、追加页面、所有权或借用变化、检查、失败复位均保留原凭证。只有成功复位清除它。

## 示例

输入：

```json
{"pages":[[3,5],[40,20]],"ops":[["alloc","a",8,4],["alloc","b",8,4],["inspect"]]}
```

输出：

```json
{"events":[{"status":"ok","page":1,"offset":0,"scan_from":0},{"status":"ok","page":1,"offset":8,"scan_from":1},{"status":"ok","cursors":[0,16],"live":2,"retiring":0,"pins":0}]}
```
