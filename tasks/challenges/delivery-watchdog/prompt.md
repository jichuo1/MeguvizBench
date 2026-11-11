# 数据包传送监督器

修复三个 Python 模块组成的逻辑时钟监督器。它读取一段执行记录，决定何时允许新的传送尝试、何时停止旧尝试，以及何时可以承认已交付。运行环境无网络，无真实进程。只使用 Python 标准库，保留现有文件名和 JSON 协议。

## 输入

`solution.py` 从 stdin 读取一个 JSON 对象，向 stdout 输出一个 JSON 对象。

- `digest` 是本轮唯一认可的内容标识。它是非空字符串，且不是保留字 `missing`、`unavailable`。
- `size`、`stall`、`max_attempts` 为正整数，`backoff` 为非负整数。
- `events` 按非递减逻辑时间排列。每个事件有整数 `t` 和操作 `op`。同一时刻按输入顺序处理。
- `probe` 附带 `local` 与 `remote`。前者是读取到的当前本地内容标识；后者是远端缺失 `missing`、查询不确定 `unavailable`，或者已确认的远端内容标识。
- `progress` 附带 `attempt`、`phase` 与 `count`。阶段由早到晚为 `encode`、`transfer`、`verify`。计数值可能无效。
- `exit` 附带 `attempt`，表示该尝试已确认退出。
- `confirmed` 附带 `attempt` 和 `digest`，表示当前传送的远端读回已经确认。
- `tick` 为心跳。 `cancel` 为用户取消。两者无其他字段。

## 调度规则

1. 初始状态为 `await_probe`，尚未尝试。仅在 `await_probe`，或在 `backoff` 且达到允许时刻时处理 `probe`。
2. 处理探测时先核对本地内容，变更时进入 `failed`，原因为 `digest_changed`。本地内容一致时，远端 `unavailable` 保留当前状态；远端已有内容且一致则进入 `succeeded`，原因为 `verified`；远端已有不同内容则进入 `failed`，原因为 `remote_conflict`。只有确认缺失时才可启动。如果已耗尽尝试预算，则进入 `failed`，原因为 `attempts_exhausted`。成功读回仍可在预算耗尽后被承认。
3. 开始尝试后进入 `running`，尝试编号从 1 递增。其进度初始为 `(encode, 0)`，期限为开始时刻加 `stall`。只处理当前尝试的进度。先检查 `count` 是整数、非布尔值，且介于 0 和 `size` 之间，再比较阶段和计数。阶段向前或同阶段计数严格增加才更新高水位并将期限改为当前时间加 `stall`。阶段回退、计数回退、重复报告、无效计数和心跳均无效。
4. 除取消外，`t` 严格晚于期限时，应在处理该事件前发出一次停止动作并进入 `draining`。恰好等于期限时先处理事件，随后若仍处于 `running` 且期限未更新，发出停止动作并进入 `draining`。同一尝试最多发出一次停止动作。此规则也适用于旧代事件和心跳。
5. `running` 和 `draining` 都接受当前尝试的 `exit`，它进入 `backoff`，允许时刻为确认退出时刻加 `backoff`。退避到期仍需新的有效远端探测。等待退出时禁止启动新尝试；收到旧尝试的进度、退出或确认时不得推进当前尝试。
6. 只有当前 `running` 尝试的 `confirmed` 可以直接结案。摘要一致则 `succeeded/verified`，不一致则 `failed/remote_conflict`。传送计数达到 `size`、进入校验阶段或进程退出，都不能单独证明已交付。排空阶段的确认留待后续探测验证。
7. `cancel` 优先于同一事件的超时判断。处于 `running` 时发出一次停止动作，处于 `draining` 时不用再发。任何非终态取消后变为 `cancelled/cancelled`。成功、失败、取消都是吸收态，之后的事件仅留下空动作。

## 输出

输出 `{"state":状态,"reason":原因或null,"attempts":已启动次数,"actions":逐事件动作列表}`。每个输入事件在 `actions` 中对应一个数组。启动和停止分别用 `{"op":"start","attempt":编号}` 和 `{"op":"stop","attempt":编号}`。其余状态变化无需动作。

例如 `digest="packet-a", size=9, stall=4, backoff=2, max_attempts=2`，事件为 `{"t":0,"op":"probe","local":"packet-a","remote":"missing"}`、`{"t":4,"op":"tick"}`。结果为 `{"state":"draining","reason":null,"attempts":1,"actions":[[{"op":"start","attempt":1}],[{"op":"stop","attempt":1}]]}`。
