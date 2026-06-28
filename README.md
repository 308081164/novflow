# NovFlow · AI 长篇网文工作台

面向非技术作者的 Web 应用：设定管理、章节 AI 写作、规则质检、定稿导出。

## 架构概览

**前后端分离**：React + Vite 前端（`frontend/`）+ FastAPI 后端（`backend/`）。

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + Vite + TypeScript + Tailwind |
| 后端 | FastAPI + SQLAlchemy |
| LLM | DeepSeek Chat API |
| 图像 | 火山即梦 Seedream（可选） |
| 存储 | SQLite/PostgreSQL + MinIO（可选） |

| 模式 | 数据库 | 章节正文存储 | 启动方式 |
|------|--------|--------------|----------|
| 本地开发 | SQLite | DB TEXT 列 | `start.ps1` / `start-backend.ps1` |
| Docker 部署 | PostgreSQL | MinIO 对象存储 | `docker compose up -d` |

- 元数据（书名、字数、状态、标题等）始终存在数据库
- MinIO 存储章节 Markdown 正文（`{book_id}/{chapter_no}.md`）与生成图片
- 未启用 MinIO 时自动回退到 SQLite TEXT，不影响现有本地工作流

### 智能体编排（写作 Agent）

写作智能体采用 **理解 → 规划 → 路由 → 执行 → 落库** 五层流水线（非单一 LLM 包办）：

1. **理解** — `agent_intent` 规则 + LLM 合并意图
2. **规划** — `task_planner` 生成 `execution_mode` 与步骤
3. **路由** — `write_agent.chat_turn` 按模式选专用执行器
4. **执行** — 一致性分析 / 逐章改文 / 卡片草案等
5. **落库** — `apply_edits` + 前端 `chapterDiff` 逐块审阅

创书助手（`setup_agent`）共享语义理解与即梦生图，但不走多资源一致性流水线。

**完整架构图、模块表与深度分析** → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

**扩展规划与可行性分析** → [docs/HYBRID_ARCHITECTURE.md](docs/HYBRID_ARCHITECTURE.md)（本地+云端+管理后台）、[docs/STANDALONE_DESKTOP.md](docs/STANDALONE_DESKTOP.md)（桌面独立安装）

---

## 快速开始（Windows 本地）

### 1. 配置 API Key

```powershell
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-...
```

### 2. 一键启动

```powershell
.\start.ps1
```

浏览器打开：**http://127.0.0.1:8000**

演示账号：`demo@example.com` / `demo123456`

### 3. 开发模式（前后端热更新）

```powershell
# 终端 1
.\start-backend.ps1

# 终端 2
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

---

## Docker 部署

前置：已安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。

```powershell
cd novflow
copy .env.example .env
# 编辑 .env，至少填入 DEEPSEEK_API_KEY（规则质检可不填）

docker compose config    # 校验 compose 配置
docker compose build     # 构建镜像
docker compose up -d     # 后台启动全部服务
```

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost | Nginx 托管 SPA，/api 反代后端 |
| 后端 API | http://localhost:8000 | FastAPI + Swagger `/docs` |
| MinIO API | http://localhost:9000 | S3 兼容对象存储 |
| MinIO 控制台 | http://localhost:9001 | 默认账号见 `.env` 中 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` |
| PostgreSQL | localhost:5432（容器内 `db:5432`） | 仅容器网络内访问 |

常用命令：

```powershell
docker compose ps          # 查看状态
docker compose logs -f backend   # 查看后端日志
docker compose down          # 停止并移除容器
docker compose down -v       # 同时删除数据库与 MinIO 卷（慎用）
```

Docker 模式下环境变量由 `docker-compose.yml` 注入：`USE_MINIO=true`、PostgreSQL、`MINIO_ENDPOINT=minio:9000`。本地 `start.ps1` 不受影响。

**推荐一键启动（会自动检查 Docker 是否运行）：**

```powershell
.\start-docker.ps1
```

### 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| `no such service: build` | 把 `build` 当成了服务名 | 用 `docker compose build` 或 `docker compose up -d --build`，不要写 `up -d build` |
| `dockerDesktopLinuxEngine ... cannot find the file` | Docker Desktop **未启动** | 打开 Docker Desktop，等 Engine running 后再执行 |
| `cd docker` 找不到路径 | compose 在 `novflow/` 根目录 | 在 `novflow` 下直接运行，**没有** `docker/` 子目录 |
| 拉取 `minio/mc` 失败 | 同上，引擎未运行 | 先启动 Docker Desktop |

正确命令示例：

```powershell
cd D:\Hui_Files\MyProjects\测试小项目\AI_nov\novflow
docker compose up -d --build    # 构建 + 启动（一条命令）
```

---

## 使用流程（从零创作）

1. **注册/登录** → **设置** 中填入 DeepSeek API Key  
2. **新建书籍** → 选择「从零开始」→ 进入 **5 步创建向导**  
   - 作品定位 → 世界观（可 AI 生成）→ 角色卡（可 AI 生成）→ 章节大纲（可 AI 生成）→ 开始写作  
3. 在 **章节编辑器** 中使用 AI 生成/扩写/规约修复  
4. **定稿** 后 **导出 TXT**

---

| 功能 | 说明 |
|------|------|
| 模板建书 | 「追逃喜剧」模板，自动导入前30章规划与正文 |
| 章节写作 | 编辑器 + AI 生成/加厚/规约修复 |
| 规则质检 | 逗号≤3、禁破折号、字数、标题格式等（无需 API Key） |
| 规则修复 | 一键修复逗号、破折号 |
| 定稿 | 无 error 后可定稿 |
| 导出 | 全书 TXT |

## 目录结构

```
novflow/
  docs/
    ARCHITECTURE.md         系统架构图、模块表、深度分析
    HYBRID_ARCHITECTURE.md  本地+云端+管理后台混合架构可行性
    STANDALONE_DESKTOP.md   本地独立安装包与零配置可行性
  backend/              FastAPI 后端
    app/
      routers/          REST 路由（write_agent, setup_chat, chapters…）
      services/
        write_agent.py      写作 Agent 编排核心
        agent_intent.py     语义理解（两阶段）
        task_planner.py     任务规划与 execution_mode
        write_task_executor.py  一致性/跨资源执行
        book_index.py       全书结构化索引
        setup_agent.py      创书助手
        rule_engine.py      规则质检
        generation.py       编辑器 AI 异步任务
        image_gen.py        即梦生图编排
        chapter_content.py  正文读写（MinIO / DB 回退）
    tests/              单元测试（planner、consistency、lint…）
  frontend/             React + Vite 前端
    src/
      components/write/ WriteAgentPanel、LintEditor
      utils/            chapterDiff、writeAgentMessage
  docker-compose.yml    PostgreSQL + MinIO + 前后端
  start.ps1             本地生产模式启动
```

## API 文档

启动后访问：http://127.0.0.1:8000/docs（Docker 亦可通过 http://localhost/docs）

## 与 Cursor 试笔项目的关系

- 软件目录：`novflow/`（独立）
- 设定/正文源：`../我的AI成精了/`（模板导入时读取）
- 规约逻辑：迁移自 `写作规约.md` 与 `scripts/fanqie_selfcheck.py`

## 限制（MVP）

- 章节历史版本（`chapter_versions`）仍存 DB，未迁移至 MinIO
- AI 生成为异步任务（轮询），非 SSE 流式展示
- 语义质检依赖 DeepSeek，规则质检离线可用
- 单用户演示级认证，无邮箱验证
- Docker 模板导入无法读取宿主机 `../我的AI成精了/` 正文（需后续挂载卷）
