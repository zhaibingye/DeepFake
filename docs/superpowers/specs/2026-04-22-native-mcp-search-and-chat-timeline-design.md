# Native MCP Search And Chat Timeline Design

## Goal
把当前“应用侧先搜索再喂给模型”的伪工具方案，升级成“模型原生决定是否调用搜索工具”的真工具调用方案，并把聊天页从分区式思考/工具展示改成按真实发生顺序渲染的 assistant 时间线。

## Scope
本次改动覆盖两条主线：

1. 搜索能力改为 provider 原生 tool calling。
2. assistant 输出改为统一时间线片段，并持久化保存。

本次只支持两个固定远程 MCP 搜索工具：

- `exa_search`
- `tavily_search`

本次不实现：

- 通用 MCP 注册中心
- 动态工具市场
- 自动选择搜索源
- 对不支持 tool calling 的模型做应用侧降级代调

## Product Decisions
- 用户仍通过前端开关决定是否允许联网搜索。
- 用户仍手动选择 `Exa` 或 `Tavily`。
- 开启搜索时，只把用户选中的那个工具暴露给模型。
- 是否实际调用工具，由模型自己决定。
- 当前 provider 或 model 不支持原生 tool calling 时，直接失败并提示原因。
- `Tavily` 未配置时，直接失败并提示原因。
- assistant 最终回答也属于时间线的一部分，而不是独立消息气泡。

## Backend Architecture
后端拆成四层职责：

### 1. Provider Request Layer
负责判断当前 provider/model 是否支持原生工具调用，并在 `enable_search=true` 时把选中的单个搜索工具 schema 注入 provider request payload。

### 2. Tool Runtime Layer
负责固定远程 MCP 的执行细节，包括：

- Exa 免密远程 MCP
- Tavily 带后台配置 API key 的远程 MCP

该层只执行模型明确发起的 tool call，不提前搜索，不替模型做决策。

### 3. Timeline Layer
负责 assistant 时间线片段的创建、追加、结束、失败和序列化。时间线片段至少包含：

- `thinking`
- `tool`
- `answer`

### 4. Route Orchestration Layer
负责流式收发、工具调用循环、事务提交和回滚。`main.py` 只保留路由与编排，不继续堆积业务细节。

## Assistant Timeline Model
一条 assistant message 改为保存 `parts` 数组，按真实发生顺序持久化：

```json
{
  "role": "assistant",
  "parts": [
    { "id": "part_1", "kind": "thinking", "status": "done", "text": "先判断是否需要搜索" },
    {
      "id": "part_2",
      "kind": "tool",
      "status": "done",
      "tool_name": "exa_search",
      "label": "Exa 搜索",
      "input": "你好",
      "detail": "返回 3 个结果",
      "output": "..."
    },
    { "id": "part_3", "kind": "thinking", "status": "done", "text": "整理结果" },
    { "id": "part_4", "kind": "answer", "status": "done", "text": "你好，..." }
  ]
}
```

历史会话加载时，前端直接按 `parts` 渲染，不再把 thinking、tool、answer 拆成三块分区。

## Stream Event Contract
前端不再消费分散的：

- `thinking_delta`
- `text_delta`
- `activity`

改为消费统一的时间线事件：

- `timeline_part_start`
- `timeline_part_delta`
- `timeline_part_end`
- `timeline_part_error`
- `conversation`
- `usage`
- `done`
- `error`

其中：

- `timeline_part_start`：创建一个新的 `thinking` / `tool` / `answer` 块
- `timeline_part_delta`：给某个块追加文本或结果细节
- `timeline_part_end`：标记块结束
- `timeline_part_error`：标记工具块失败

前端只根据事件顺序维护时间线数组，不再猜测某段内容该落到哪个区域。

## Search Tool Calling Flow
当用户开启搜索且选择一个搜索源后：

1. 后端检查当前 provider/model 是否支持 tool calling。
2. 若不支持，直接返回 400。
3. 若支持，把选中的单个工具 schema 注入模型请求。
4. 模型若不调用工具，本轮直接走普通回答。
5. 模型若调用工具，后端执行对应远程 MCP。
6. 工具结果作为 tool result 回传给模型继续生成。
7. 生成过程中可能继续出现新的 `thinking` 块、再次调用工具，或直接进入 `answer` 块。

本轮只开放一个选中的搜索工具给模型，因此模型只决定“调不调”，不决定搜索源。

## Frontend UI
聊天页改成统一时间线卡片，而不是“思考框固定在上、工具固定在下、答案单独在底部”。

每个时间线块共享统一骨架：

- 左侧图标
- 标题和状态
- 可展开内容区
- 运行中的微动画

块类型：

- `thinking`
- `tool`
- `answer`

交互规则：

- 当前进行中的块默认展开。
- 当进入下一个块时，前一个块默认折叠。
- 用户手动展开后，不再被后续流强制折回。
- 历史消息默认折叠，只显示摘要。
- `answer` 作为最后一个时间线块持续增长，不再单独走传统 assistant 气泡。

## Frontend Structure
聊天时间线相关逻辑从 `App.tsx` 中拆出：

- `frontend/src/components/chat/TimelineList.tsx`
- `frontend/src/components/chat/TimelineBlock.tsx`
- `frontend/src/components/chat/ThinkingBlock.tsx`
- `frontend/src/components/chat/ToolBlock.tsx`
- `frontend/src/components/chat/AnswerBlock.tsx`
- `frontend/src/components/chat/useTimelineState.ts`
- `frontend/src/components/chat/timeline.ts`

`App.tsx` 只保留页面级状态、发送消息、路由与后台管理入口。

## Persistence And Compatibility
需要为 assistant message 增加新的 timeline 存储结构，并确保旧会话不直接损坏。

兼容策略：

- 新生成的 assistant message 使用 `parts` 持久化。
- 旧 assistant message 在读取时做兼容映射，转换成单次渲染用的 timeline 结构。
- 旧数据可读，但不要求回填迁移成新结构。

## Error Handling
- provider/model 不支持原生 tool calling：直接失败并提示。
- `Tavily` 未配置或被禁用：直接失败并提示。
- MCP 调用失败：发出工具错误时间线事件，然后整轮回滚。
- 用户中断：整轮回滚，不保存本轮 assistant timeline。
- provider 流式错误：整轮回滚。

保持现有规则不变：失败、异常、中断都不保存半截 assistant 回复。

## Testing
后端至少覆盖：

- 搜索开启时只注入用户选中的单个 tool schema
- provider 支持 tool calling 时，模型可选择不调用工具
- 模型调用 `exa_search` 时后端正确执行远程 MCP
- 模型调用 `tavily_search` 时后端正确执行远程 MCP
- provider 不支持 tool calling 时直接失败
- `Tavily` 未配置时直接失败
- 工具失败、中断、provider 错误时整轮回滚
- assistant timeline 能按顺序持久化

前端至少覆盖：

- `thinking -> tool -> thinking -> answer` 可按顺序渲染
- 当前块默认展开，切换到下一个块后默认折叠
- 用户手动展开后不会被后续流重置
- 历史消息重新加载后仍按持久化时间线还原
- `answer` 已不再走旧气泡路径

## Risks
最大风险有三点：

1. 不同 provider 的工具调用流式格式不同，需要后端明确做归一化。
2. assistant message 的持久化结构升级后，旧数据兼容必须稳住。
3. `App.tsx` 拆分时容易带出无关 UI 回归，实施时要严格限制范围。

## Success Criteria
- 搜索只在支持原生 tool calling 的模型上可用。
- 模型自己决定是否调用选中的搜索工具。
- assistant 输出能以真实时间顺序展示多个 thinking/tool/answer 块。
- 刷新页面或重新进入会话后，时间线顺序保持一致。
- 工具失败、provider 失败、用户中断时，不保存半截回复。
