# 半透明面板的帧调度

为一个拥有多个绘制目标的合成器实现帧调度。原生背景效果只有在来源语义、能力和裁剪同时匹配时才可用。首次尝试异步确认，待确认时继续使用兼容路径。同一帧的兼容采样共享预算。请提交 `solution.py`，从 stdin 读取一个 JSON 对象，向 stdout 写入一个 JSON 数组。只使用 Python 标准库。

## 输入

输入对象有 `events` 数组。按输入顺序处理，进程初始没有绑定。事件对象由 `op` 区分。

| 事件 | 字段 |
| --- | --- |
| `bind` | `surface`、`generation`、`target`、`source`、`revision`、`effect`、`rect`、`halo`、`opt_in`、`compatible`、`cost`、`priority` |
| `unbind` | `surface`、`generation` |
| `frame` | `frame`、`target`、`scene`、`viewport`、`hardware`、`native_available`、`budget` |
| `receipt` | `surface`、`generation`、`frame`、`ok` |

标识 `surface`、`target`、`source`、`scene` 为 ASCII 字符串。`source` 是兼容采样来源，`scene` 是当前目标可被原生效果读取的背景来源。`generation` 是同一 surface 内唯一的绑定编号，`revision` 区分同一 source 的不同版本。帧编号全局递增且唯一。`effect` 取 `frost`、`lens` 或 `tint`。`rect` 和 `viewport` 都是 `[left, top, right, bottom]` 整数坐标，宽高为正。`halo`、`cost`、`budget` 为非负整数，`priority` 是可为负的整数。其余标志为布尔值。测试输入最多 512 个事件，字段和类型均合法。回执和解绑事件可能过期或引用不存在的绑定。

## 绑定与原生效果

- `bind` 替换同名 surface 的旧绑定，新绑定从未确认状态开始。`unbind` 仅在编号匹配时移除绑定。
- 一帧只输出其目标上仍绑定的 surface。原生资格要求该帧支持原生且硬件加速，绑定明确开启、兼容、效果为 `frost`、`cost > 0`，并且 `source == scene`。把 rect 四边各扩张 halo 后，必须完全落在 viewport 内，允许边界相等。
- 每个未确认绑定最多有一个在途探测。第一帧符合资格时，输出 `probe: true` 并同时走兼容路径。探测在途时，后续帧仍走兼容路径且 `probe: false`。仅匹配 surface、generation 和在途帧编号的回执才生效，成功后进入已确认状态。
- 已确认绑定在符合资格的帧走 `native`，`probe` 为 false。此后只接受该绑定**最近一次**实际输出 `native` 的帧回执，新一次原生绘制会取代旧编号。已处理的回执编号立即失效，包括重复回执。
- 一个被接受的失败回执使原生在该绑定内持续停用。暂时失去资格时走兼容路径，保留探测、已确认和失败状态。重新绑定才重新初始化这些状态。

## 兼容采样与输出

- 每帧独立分配预算。对所有本帧未走 `native` 且 `cost > 0` 的绑定，按 `[source, revision]` 分组。组开销是组内最大 cost，优先级是组内最大 priority。
- 按优先级从高到低分配。优先级相同时，先按 source 升序，再按 revision 数值升序。如果一个组超过剩余预算，跳过它并继续评估后续组。
- 被分配的组内所有绑定使用 `sample`，其余绑定使用 `flat`。cost 为 0 的绑定始终使用 `flat`。
- 每个 `frame` 事件输出一个对象，其余事件无输出。结果形如 `{"frame":1,"layers":[{"surface":"panel","generation":1,"path":"sample","probe":true}],"captures":[["base",0]],"used":4}`。`layers` 按 surface 升序，`captures` 按实际分配顺序，`used` 是已分配组的总开销。空帧为 `layers: []`、`captures: []`、`used: 0`。

## 公开示例

先绑定 `panel` 到 `main`，generation 为 1，source 为 `base`，revision 为 0，effect 为 `frost`，rect 为 `[2,2,8,8]`，halo 为 2，opt_in 和 compatible 均为 true，cost 为 4，priority 为 3。

在 `main` 上提交 frame 1，scene 为 `base`，viewport 为 `[0,0,10,10]`，hardware 和 native_available 均为 true，budget 为 4。应输出上文的探测加采样结果。随后提供 `panel`、generation 1、frame 1、ok true 的回执。相同条件下提交 frame 2，此时应输出 `{"frame":2,"layers":[{"surface":"panel","generation":1,"path":"native","probe":false}],"captures":[],"used":0}`。
