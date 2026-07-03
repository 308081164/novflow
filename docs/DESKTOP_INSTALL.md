# NovFlow Windows 桌面独立安装包

本文说明如何**构建**与**使用** NovFlow Windows 一键安装版。桌面版无需安装 Python、Node.js 或 Docker；数据保存在本机 `%LocalAppData%\NovFlow\data\`。

---

## 用户指南

### 安装

1. 运行 `NovFlowSetup.exe`（由构建步骤生成，位于 `dist/`）。
2. 按向导选择安装目录（默认 `%LocalAppData%\Programs\NovFlow` 或 `C:\Program Files\NovFlow`）。
3. 可选：创建桌面快捷方式。
4. 安装完成后可勾选「启动 NovFlow」。

### 日常使用

1. 双击 **NovFlow** 快捷方式或 `NovFlow.exe`。
2. 浏览器会自动打开 `http://127.0.0.1:18765`。
3. 注册/登录后，在 **设置** 页粘贴 DeepSeek API Key（规则质检可不填 Key）。
4. 开始新建书籍、写作、导出。

### 单实例行为

- 若 NovFlow 已在运行，再次双击只会打开浏览器，不会重复启动后端。
- 运行状态写入 `%LocalAppData%\NovFlow\data\server.json`（端口、PID）。

### 数据位置

| 内容 | 路径 |
|------|------|
| SQLite 数据库 | `%LocalAppData%\NovFlow\data\novflow.db` |
| 图片/媒体文件 | `%LocalAppData%\NovFlow\data\media\` |
| 运行状态 | `%LocalAppData%\NovFlow\data\server.json` |

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
- [Node.js 18+](https://nodejs.org/)（构建前端）
- [Inno Setup 6](https://jrsoftware.org/isinfo.php)（生成 `NovFlowSetup.exe`）

### 步骤

```powershell
cd novflow

# 1. 生成分发目录（前端 build + 便携 Python + NovFlow.exe）
.\desktop\build.ps1

# 2. 编译安装器（需 iscc 在 PATH，或从 Inno Setup 安装目录调用）
iscc installer\novflow.iss
```

产物：

| 文件 | 说明 |
|------|------|
| `dist/novflow-installer-stage/` | 可直接拷贝的绿色版目录 |
| `dist/NovFlowSetup.exe` | 最终安装程序 |

### 安装包目录结构

```text
{InstallDir}/
├── NovFlow.exe          # 启动器（PyInstaller）
├── runtime/             # 捆绑 Python venv + uvicorn
├── backend/             # FastAPI 后端
└── frontend/dist/       # 预编译 SPA
```

### 环境变量（启动器自动设置）

| 变量 | 说明 |
|------|------|
| `NOVFLOW_DESKTOP=1` | 桌面模式 |
| `NOVFLOW_INSTALL_DIR` | 安装目录 |
| `NOVFLOW_DATA_DIR` | 数据目录，默认 `%LocalAppData%\NovFlow\data` |
| `USE_MINIO=false` | 本地文件存储图片 |

默认服务端口：**18765**。

### 本地调试启动器（未打包）

```powershell
$env:NOVFLOW_INSTALL_DIR = "D:\path\to\novflow"
$env:NOVFLOW_DATA_DIR = "$env:LOCALAPPDATA\NovFlow\data"
python desktop\launcher.py
```

需已执行 `desktop\build.ps1` 或手动准备好 `runtime/`、`backend/`、`frontend/dist/`。

---

## 相关文档

- [STANDALONE_DESKTOP.md](./STANDALONE_DESKTOP.md) — 可行性分析与缺口
- [README](../README.md) — 开发者本地启动
