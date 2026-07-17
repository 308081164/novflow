# NovFlow Windows 桌面独立安装包

本文说明如何**构建**与**使用** NovFlow Windows 一键安装版。桌面版无需安装 Python、Node.js 或 Docker；数据保存在本机 `%LocalAppData%\NovFlow\data\`。

---

## 用户指南

### 安装

1. 运行 `NovFlowSetup.exe`（由构建步骤生成，位于 `dist/`）。
2. 安装向导支持**简体中文**与 **English**。中文 Windows 会自动使用简体中文界面；其他语言环境会按系统 UI 语言匹配，必要时弹出语言选择（默认优先简体中文）。
3. 按向导选择安装目录（默认 `%LocalAppData%\Programs\NovFlow` 或 `C:\Program Files\NovFlow`）。
4. 可选：创建桌面快捷方式。
5. 安装完成后可勾选「启动 NovFlow」。

### 日常使用

1. 双击 **NovFlow** 快捷方式或 `NovFlow.exe`。
2. 会先显示 **加载窗口**，后端就绪后自动打开嵌入式主窗口（1280×800）。
3. **启动时不做授权拦截** — 未激活也可进入应用、浏览书库与设置。
4. 首次进入或未激活时，应用内会提示 **「请前往设置完成授权激活」**；在 **设置 → 产品授权** 粘贴激活码完成激活（需勾选许可协议）。
5. 注册/登录后，在 **设置** 页粘贴 DeepSeek API Key（规则质检可不填 Key）。
6. 开始新建书籍、写作、导出。

### 产品授权（桌面版）

- 激活码离线验证，与本机设备指纹绑定。
- 未激活时：可打开应用、管理书库；**AI 写作、智能体、生图等** 功能由后端 API 拦截并提示前往设置激活。
- 激活入口：**设置 → 产品授权**（显示 HW_ID / 设备码、激活码输入、许可协议确认）。
- 启动器与 Electron 壳 **不会在启动前弹出授权对话框**；`license_gate.py` 仅作可选 CLI 工具，不参与正常启动流程。

### 单实例行为

- 若 NovFlow 已在运行，再次双击会将已有窗口置于前台。
- 关闭 NovFlow 窗口后，后端（uvicorn）与相关 Python 进程会自动退出，释放内存。
- 运行状态写入 `%LocalAppData%\NovFlow\data\server.json`（端口、后端 PID）；`launcher.log` / `electron.log` 记录诊断日志。

### 窗口未出现

1. 再次双击 NovFlow（会自动尝试聚焦已有窗口）。
2. 若仍无窗口，打开 `%LocalAppData%\NovFlow\data\` 下的 `electron.log`、`launcher.log`、`backend.log` 查看原因。
3. 仍无法解决：任务管理器结束 **NovFlow.exe** 及安装目录 `resources\novflow\runtime` 下的 **python.exe** / **uvicorn.exe** 后重试。

### 升级或重装

1. **正常情况**：直接运行新版 `NovFlowSetup.exe`，安装程序会在复制文件前自动结束 NovFlow 及相关进程。
2. **若提示无法关闭应用**：打开任务管理器，结束所有 **NovFlow.exe**，以及 `resources\novflow\runtime` 中的 **python.exe** / **uvicorn.exe**，然后重新运行安装包。
3. **手动清理（一次性）**（在 PowerShell 中）：

```powershell
taskkill /F /IM NovFlow.exe /T
Get-Content "$env:LOCALAPPDATA\NovFlow\data\server.json"
taskkill /F /T /PID <上一步看到的 pid>
```

### 数据位置

| 内容 | 路径 |
|------|------|
| SQLite 数据库 | `%LocalAppData%\NovFlow\data\novflow.db` |
| 图片/媒体文件 | `%LocalAppData%\NovFlow\data\media\` |
| 运行状态 | `%LocalAppData%\NovFlow\data\server.json` |
| Electron 日志 | `%LocalAppData%\NovFlow\data\electron.log` |
| 后端/启动器日志 | `%LocalAppData%\NovFlow\data\launcher.log` / `backend.log` |

卸载程序会删除 `%LocalAppData%\NovFlow` 下的用户数据（见 `installer/novflow.iss`）。

### 仍需用户自行准备

- **DeepSeek API Key**（AI 写作/质检）
- **联网**（云端 API）
- （可选）即梦 Key — 仅 AI 绘图需要

---

## 开发者：构建安装包

### 前置条件

- Windows 10/11
- [Python 3.11+](https://www.python.org/)（仅构建机需要）
- [Node.js 18+](https://nodejs.org/)（构建前端 + Electron）
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)（生成 `NovFlowSetup.exe`）

### 步骤

```powershell
cd novflow

# 一键打包（推荐）
.\package-desktop.ps1

# 或分步：
.\desktop\build.ps1          # staging + Electron
iscc installer\novflow.iss   # 安装器
```

产物：

| 文件 | 说明 |
|------|------|
| `dist/novflow-installer-stage/` | 可直接拷贝的绿色版目录 |
| `dist/NovFlowSetup.exe` | 最终安装程序 |

### 安装包目录结构

```text
{InstallDir}/
├── NovFlow.exe              # Electron 主程序（入口）
├── resources/
│   ├── app.asar             # Electron 壳
│   └── novflow/             # Python sidecar + 业务资源
│       ├── runtime/         # 捆绑 Python venv + uvicorn
│       ├── backend/         # FastAPI 后端
│       ├── frontend/dist/   # 预编译 SPA
│       ├── desktop/         # backend_launcher.py（license_gate.py 为可选 CLI，不参与启动）
│       └── shared/          # 授权模块
├── locales/
└── *.dll                    # Electron/Chromium 运行时
```

### 环境变量（自动设置）

| 变量 | 说明 |
|------|------|
| `NOVFLOW_DESKTOP=1` | 桌面模式 |
| `NOVFLOW_INSTALL_DIR` | 安装目录（Electron 内为 `resources/novflow`） |
| `NOVFLOW_DATA_DIR` | 数据目录，默认 `%LocalAppData%\NovFlow\data` |
| `USE_MINIO=false` | 本地文件存储图片 |

默认服务端口：**18765**。

### 本地调试（未打包）

```powershell
# 1. 准备 sidecar（runtime、backend、frontend/dist）
.\desktop\build.ps1   # 或手动启动后端

# 2. 开发模式启动 Electron 壳
$env:NOVFLOW_INSTALL_DIR = "D:\path\to\novflow"
cd desktop\electron
npm install
npm start
```

或使用 `python desktop\launcher.py`（会调用 `npm start`）。

---

## 相关文档

- [STANDALONE_DESKTOP.md](./STANDALONE_DESKTOP.md) — 可行性分析与缺口
- [README](../README.md) — 开发者本地启动
