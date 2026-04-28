# deepfake

一个本地可运行的多用户 AI 聊天控制台。前端使用 Vite + React + TypeScript，后端使用 FastAPI，数据存储使用 SQLite。当前版本支持多供应商接入、流式聊天、思考 / 工具 / 回答时间线、Markdown / LaTeX 渲染、图片输入、联网搜索，以及拆分后的管理员后台。

## 项目亮点

- 多用户注册、登录、退出登录和会话隔离
- 首次部署通过前端初始化页面创建首个管理员，并保留初始化接口用于自动化部署
- 管理员后台拆分为概览、供应商管理、搜索 MCP 管理、用户管理
- 支持 Anthropic Messages、OpenAI Chat Completions、OpenAI Responses、Gemini 接口格式
- 按供应商配置思考、视觉、原生工具调用、上下文窗口和最大输出 token
- 流式聊天输出，并按“思考 / 工具调用 / 回答”渲染时间线
- 支持 Exa、Tavily 搜索 MCP，可在后台配置是否开放给聊天页
- Markdown / GFM / LaTeX 渲染和图片上传输入
- 会话新建、重命名、删除和历史消息读取
- 用户启用 / 停用、重置密码、手动创建与删除

## 项目截图

### 聊天主界面

![聊天主界面](frontend/public/readme-chat.png)

### 管理员后台

![管理员后台](frontend/public/readme-admin.png)

> 截图文件位于 `frontend/public/`，用于 README 展示。重新截图时请覆盖 `readme-chat.png` 和 `readme-admin.png`。

## 技术栈

- Frontend: Vite 8 + React 19 + TypeScript 6
- UI: CSS Modules-style 全局样式 + lucide-react 图标
- Markdown: react-markdown + remark-gfm + remark-math + rehype-katex
- Backend: FastAPI + Pydantic
- Database: SQLite

## 项目结构

```text
deepfake/
├─ frontend/
│  ├─ public/                 # logo、favicon、README 截图
│  └─ src/
│     ├─ components/          # Markdown、聊天时间线等通用组件
│     ├─ features/
│     │  ├─ admin/            # 管理员后台页面与控制器
│     │  ├─ auth/             # 登录、注册、初始化管理员页面
│     │  └─ chat/             # 聊天页面、发送控制器、搜索供应商状态
│     ├─ api.ts               # 前端 API 封装
│     └─ types.ts             # 前端共享类型
├─ backend/
│  ├─ app/
│  │  ├─ routers/             # public/auth/admin/conversations/chat 路由
│  │  ├─ provider_client.py   # 多供应商流式适配
│  │  ├─ chat_stream_service.py
│  │  ├─ tool_runtime.py      # 搜索工具运行时
│  │  └─ *.py                 # 认证、用户、供应商、会话等服务
│  └─ data/app.db             # 本地 SQLite 数据库，禁止提交
├─ AGENTS.md
├─ LICENSE
└─ README.md
```

## 功能概览

### 用户侧

- 注册 / 登录 / 退出登录
- 独立会话列表与会话历史
- 新建、重命名、删除会话
- 文本聊天与 NDJSON 流式回复
- 思考内容、工具调用和最终回答分块显示
- Markdown、GFM 表格、代码块、LaTeX 渲染
- 图片上传输入，按模型视觉能力动态开放
- 深度思考开关与 effort 选择
- 联网搜索开关，支持 Exa / Tavily 作为搜索来源
- 可折叠侧边栏和紧凑聊天输入区

### 管理员侧

- 概览页查看供应商、用户和注册状态
- 添加、编辑、删除模型供应商
- 配置接口格式、API URL、API Key、模型名称、能力开关和 token 限制
- 配置 Exa / Tavily 搜索 MCP，控制聊天页是否可用
- 修改管理员用户名和密码
- 开启或关闭普通用户注册
- 手动创建普通用户或管理员
- 启用 / 停用用户
- 重置用户密码
- 删除用户及其历史会话

## 运行环境

建议环境：

- Node.js 20+
- npm 10+
- Python 3.11+

当前依赖文件显示的前端主要版本：

- React 19
- Vite 8
- TypeScript 6
- Vitest 3

## 安装教程

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd deepfake
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 安装后端依赖

```bash
cd ../backend
python -m pip install -r requirements.txt
```

## 启动教程

前后端需要分别启动。

### 启动后端

在 `backend/` 目录执行：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后地址：

- API: `http://127.0.0.1:8000`
- Health Check: `http://127.0.0.1:8000/api/health`

### 启动前端

在 `frontend/` 目录执行：

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

启动后地址：

- Web: `http://127.0.0.1:5173`

## 首次管理员初始化

后端首次启动时不会自动创建默认管理员。首次部署后，请先启动后端和前端，然后打开：

- `http://127.0.0.1:5173`

如果系统还没有任何管理员账号，前端会自动显示“创建第一个管理员”页面。该页面会要求填写：

- 管理员用户名：3 到 32 个字符
- 管理员密码：6 到 128 个字符
- 确认密码：必须与管理员密码一致

点击“创建管理员并进入”后，前端会调用初始化接口创建首个管理员，并自动进入应用。

初始化接口仍可用于脚本化部署：

- `GET /api/setup/status`：检查是否仍需初始化管理员
- `POST /api/setup/admin`：创建首个管理员并返回登录会话

注意：

- 在首个管理员创建完成前，`POST /api/setup/admin` 是未鉴权的公开初始化接口。
- 生产环境请先在受信网络、反向代理访问控制或临时防火墙保护下通过前端页面或初始化接口完成初始化，再对公网开放服务。

示例：

```bash
curl http://127.0.0.1:8000/api/setup/status

curl -X POST http://127.0.0.1:8000/api/setup/admin \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"请改成强密码\"}"
```

当 `GET /api/setup/status` 返回 `{"needs_admin_setup": false}` 时，表示管理员已初始化完成。

## 使用教程

### 普通用户使用流程

1. 打开 `http://127.0.0.1:5173`
2. 注册或登录账号
3. 选择可用供应商模型
4. 按需要开启深度思考、联网搜索或上传图片
5. 发起新对话并查看流式时间线回复
6. 在侧边栏管理历史会话

### 管理员使用流程

1. 首次部署时打开前端初始化页面创建第一个管理员
2. 使用管理员账号登录
3. 在聊天页左下角点击“管理后台”
4. 在“供应商管理”添加可用模型
5. 在“搜索 MCP 管理”配置 Exa / Tavily
6. 在“用户管理”控制注册开关、创建用户、重置密码或删除用户

管理员路由：

- `/admin`：概览
- `/admin/providers`：供应商管理
- `/admin/search-mcp`：搜索 MCP 管理
- `/admin/users`：用户管理

## 聊天接口说明

聊天接口只保留流式接口：

- `POST /api/chat/stream`

前端按 NDJSON 读取事件，主要事件包括：

- `conversation`
- `timeline_part_start`
- `timeline_part_delta`
- `timeline_part_end`
- `text_delta`
- `thinking_delta`
- `done`
- `error`

旧的 `POST /api/chat` 已移除。

## 供应商配置说明

当前支持的供应商接口格式：

- `anthropic_messages`
- `openai_chat`
- `openai_responses`
- `gemini`

供应商配置项包括：

- 名称 `name`
- 接口格式 `api_format`
- API URL `api_url`
- API Key `api_key`
- 模型名 `model_name`
- 是否支持思考 `supports_thinking`
- 是否支持视觉 `supports_vision`
- 是否支持工具调用 `supports_tool_calling`
- 思考努力等级 `thinking_effort`
- 最大上下文窗口 `max_context_window`
- 最大输出 token `max_output_tokens`
- 是否启用 `is_enabled`

地址补全规则：

- Anthropic Messages 会补全到 `/messages`
- OpenAI Chat 会补全到 `/chat/completions`
- Gemini 会补全到 `models/{model}:streamGenerateContent?alt=sse`
- OpenAI Responses 使用对应 Responses 适配器处理

## 搜索 MCP 说明

聊天页的“联网搜索”依赖供应商原生工具调用能力。管理员可在后台配置：

- Exa 搜索：API Key 可选，启用后可作为聊天搜索来源
- Tavily 搜索：必须配置 API Key 才能真正可用

如果当前模型未开启 `supports_tool_calling`，聊天页会禁用联网搜索按钮。

## 数据存储说明

项目数据保存在本地 SQLite：

- 数据库文件：`backend/data/app.db`

数据库中包含：

- 用户账号
- 登录会话
- 会话和消息
- 供应商配置
- 搜索 MCP 配置
- 图片消息内容（base64）

请不要提交本地数据库、日志或真实 API Key。

## 前后端连接说明

前端 API 地址目前写在：

- `frontend/src/api.ts`

默认值为：

```ts
const API_BASE = 'http://127.0.0.1:8000/api'
```

如果后端部署地址发生变化，需要同步修改这里。

## 常用检查命令

### 前端 lint

```bash
cd frontend
npm run lint
```

### 前端测试

```bash
cd frontend
npm run test
```

### 前端 build

```bash
cd frontend
npm run build
```

### 后端语法检查

```bash
cd backend
python -m compileall app
```

## 常见问题

### 1. 为什么前端连不上后端？

请确认：

- 后端正在 `127.0.0.1:8000` 运行
- 前端正在 `127.0.0.1:5173` 运行
- 前端 `src/api.ts` 中的 API 地址未被改错

### 2. 为什么聊天页没有联网搜索？

请确认：

- 管理员已在“搜索 MCP 管理”启用 Exa 或 Tavily
- Tavily 已配置 API Key
- 当前聊天供应商已开启工具调用能力
- 当前供应商接口格式支持原生工具调用

### 3. 为什么普通用户不能注册？

可能是管理员在后台关闭了“允许普通用户注册”。管理员仍可在“用户管理”手动创建账号。

### 4. 编辑供应商时为什么可以留空 URL 或 Key？

编辑已有供应商时，连接 URL 或 API Key 留空会保留当前已保存值，不会用空值覆盖原配置。

## License

本项目使用 `Apache-2.0` 开源许可证，详见根目录 `LICENSE` 文件。
