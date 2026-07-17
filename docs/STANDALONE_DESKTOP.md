# NovFlow 本地独立安装包 — 零配置可行性分析

> 评估 NovFlow 能否做成「用户无需电脑知识、无需配置环境变量和开发工具」的桌面独立软件。  
> 评估日期：2026-06

---

## 1. 结论

**可以接近「奶奶级」体验，但不能做到字面意义上的「零电脑知识 / 零环境变量 / 零开发工具」。**

架构已偏向「本地单机 Web 应用」，但**交付形态仍是开发者工作流**；要变成真正的一键安装，需额外 **12–20 人日**工程，且**外网 AI Key 与联网无法消除**。

| 维度 | 现状 | 目标态 |
|------|------|--------|
| 零 `.env` 编辑 | 部分能 | GUI 已可存 DeepSeek/即梦 Key，`.env` 只是后备 |
| 零开发工具 | **不能** | 仍需 Python、Node、PowerShell/`npm` |
| 零电脑知识 | **不能** | 需懂「双击安装、打开浏览器、粘贴 Key」 |
| 零配置 | **不能** | 至少一次 DeepSeek Key + 联网 |

**务实定义：**「奶奶级」= 双击桌面图标 → **Electron 嵌入式窗口**自动打开 → 注册/登录 → 设置里粘贴 Key → 开始写书。不使用系统浏览器。不需要装 Python、Node、Docker，不需要编辑 `.env`，不需要看黑窗口终端。

---

## 2. 用户仍需做什么

**应用本身可默认（无需用户管）：**

- SQLite 数据库：`config.py` 默认 `sqlite:///./data/novflow.db`
- 章节正文：本地模式 `USE_MINIO=false` 时存 DB TEXT
- JWT、演示账号：`main.py` 启动时 `ensure_demo_user`
- 前端：生产模式下由 FastAPI 托管 `frontend/dist`

**用户仍必须：**

1. 安装并启动应用（理想：一个 `.exe` 或快捷方式）
2. 注册/登录
3. **一次性粘贴 DeepSeek API Key**（设置页）
4. **保持联网**（DeepSeek / 即梦均为云端 API）
5. （可选）即梦 Key — 仅 AI 绘图需要

---

## 3. 真正「一键安装」需要的技术要件

**当前代码已具备：**

- 单机 SQLite + 本地正文回退
- 后端一体托管 SPA
- 用户级 API Key GUI

**仍缺、必须补的工程：**

| 要件 | 说明 |
|------|------|
| 捆绑 Python 运行时 | PyInstaller / Nuitka / embedded Python sidecar |
| 预编译前端 | 安装包内带 `frontend/dist`，不能在用户机器上 `npm install` |
| 无终端自启后端 | Electron 壳隐藏启动 uvicorn，嵌入式 BrowserWindow |
| SQLite + 本地文件 | 默认 `USE_MINIO=false`；**图片需补本地 filesystem 存储** |
| 首次运行向导 | 欢迎页 → 数据目录 → 粘贴 Key |
| Windows 安装器 | Inno Setup / NSIS / WiX |
| 单实例 + 托盘 | 避免重复占 8000 端口 |
| 去掉 `.env` 依赖 | 桌面版用 `%AppData%/NovFlow/` 或仅 DB 存配置 |

**桌面版不应走：** Docker Compose（PostgreSQL + MinIO + 4 容器）——对普通用户过重。

---

## 4. 与目标相比的当前缺口

### 启动与交付

| 文件/流程 | 问题 |
|-----------|------|
| `start.ps1` | 依赖系统 `python`、`npm`；每次 build；前台 uvicorn；不自动开浏览器 |
| `start.bat` | 与 README 不一致：dev 双窗口、演示账号文案不同 |
| 无安装包脚本 | ~~没有任何 Inno Setup / Tauri / Electron 打包~~ → **已有** Electron + Inno Setup（见 `desktop/build.ps1`） |

### 功能在桌面模式的硬缺口

| 文件 | 问题 |
|------|------|
| `storage.py` | `USE_MINIO=false` 时 `put_bytes` 报错，**桌面无法持久化 AI 插图/封面** |
| `pipeline.py` | 模板依赖宿主机目录，安装包内通常不存在 |

### 已有优势（不必重做）

- `config.py`：SQLite、`USE_MINIO=false` 默认值合理
- `main.py`：启动建库、演示用户、托管前端
- `api_key.py`：用户 Key 优先于全局 Key
- 规则 lint / 导出：可无 API Key 使用

---

## 5. 理想 vs 现实用户故事

### 目标态（打包完成后）

1. 双击 `NovFlowSetup.exe` 安装
2. 双击「NovFlow」，**嵌入式应用窗口**打开（非独立浏览器标签）
3. 首次向导粘贴 DeepSeek Key（可跳过，仅规则质检可用）
4. 注册 → 新建书籍 → 写作 → 导出 TXT
5. 数据在 `%AppData%/NovFlow/data/`

### 现状

1. 需安装 **Python + Node.js**
2. 可能需处理 PowerShell 执行策略
3. `copy .env.example .env` 或脚本提示填 Key
4. 运行 `.\start.ps1` → pip + npm + build
5. **黑窗口不能关**；手动打开浏览器
6. AI 绘图在本地模式可能因 MinIO 报错

---

## 6. 无法消除的外部依赖

| 无法消除 | 原因 |
|----------|------|
| DeepSeek API Key | 云端 LLM |
| 联网 | AI 写作/质检走 HTTP API |
| 第三方账号注册 | 获取 Key 需在平台注册 |
| API 费用 | 按 token 计费 |
| 即梦 Key（若要绘图） | 同上 |

本地大模型 = 换产品形态（GPU、模型下载、显存）。

---

## 7. 工作量估算

| 阶段 | 内容 | 人日 |
|------|------|------|
| MVP 打包 | PyInstaller + Inno Setup + 启动器 | 5–8 |
| 桌面存储补齐 | `storage.py` 本地文件 fallback | 2–4 |
| 首次引导 | Welcome 向导、Key 粘贴 | 2–3 |
| 打磨 | 单实例、托盘、端口提示、卸载 | 3–5 |
| 测试与发布 | 干净 Win10/11 虚机、文档 | 2–4 |
| **合计** | 「奶奶可用」版本 | **12–20 人日** |

**更快但更糙（8–10 人日）：** 仅 PyInstaller + 批处理，不做首次向导和本地图片存储。

**更慢但更「真桌面」（+8–15 人日）：** Electron/Tauri 内嵌 WebView。

---

## 8. 桌面客户端（exe）方案对比

| 方案 | 人天 | 说明 |
|------|------|------|
| **Electron + sidecar Python（v1 ✅）** | 2–3（壳）+ 打包 | 当前实现；嵌入式 Chromium 窗口 |
| **Tauri + sidecar Python** | 12–18 | 后续可选 |
| **pywebview + sidecar Python** | — | 已弃用（无 UI 响应问题） |
| **纯离线前端重写** | 45–70 | 不推荐；等于 fork 后端 |

---

## 9. 总结

- **现在不行**，工程上**可以做到「接近」零配置。
- **零 API Key / 零联网**永远不行（除非本地 LLM 产品）。
- 合理目标：**12–20 人日** 做出 Windows 一键安装 + GUI 配 Key + 本地数据。

---

## 相关文档

- [HYBRID_ARCHITECTURE.md](./HYBRID_ARCHITECTURE.md) — 本地 + 云端 + 管理后台混合架构
- [PRODUCT_ROADMAP.md](./PRODUCT_ROADMAP.md) — 产品三大支柱路线图
- [LOCAL_IMAGE_DLC.md](./LOCAL_IMAGE_DLC.md) — 本地生图 DLC
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 当前系统架构
- [README](../README.md) — 快速开始
