# NovFlow 本地生图扩展（Image Engine DLC）技术方案

> **文档性质：** 产品与技术设计草案（Planning）  
> **版本：** 0.1  
> **日期：** 2026-06  
> **状态：** 待评审 — 本文档描述可选扩展能力，**不代表主程序已内置或官方托管任何生图服务**

---

## 1. 背景与目标

NovFlow 主程序默认通过**云端即梦 API** 生成封面、角色立绘与章节插图。该路径受平台内容安全策略约束，部分网文选段可能被拒绝。

部分作者希望在本机以**更高创作自由度**生成插图，且：

- **不由 NovFlow 官方服务器**部署、代理或审查任何生图请求；
- 以**可选「扩展 DLC」**形式交付，用户自愿下载、自愿启用；
- 主程序与 DLC **权责分离**：主程序仅提供对接协议与开关，不对用户本地生成内容负责。

### 1.1 设计目标（与需求映射）

| 需求 | 设计回应 |
|------|----------|
| 4GB 显存可用（可慢） | 默认 **Lite 档**：SD 1.5 / 轻量 SDXL + 低显存推理配置 |
| 大显存可更强/更快 | **Standard / Pro 档** 可选模型包（SDXL、FLUX 等） |
| 零代码、离线安装 | 独立安装包 + 图形化「引擎控制台」+ 一键检测，不依赖用户安装 Python/Node/CUDA 工具链 |
| 本地极低限制 | 引擎侧**不内置内容审查**；提示词直传本地模型 |
| 合规与免责 | 独立 EULA、首次启用强制确认、设置页常驻声明；主程序与 DLC 分开发布 |

### 1.2 非目标（Explicit Non-Goals）

- NovFlow **官方 SaaS / Docker 镜像内不提供**本地生图引擎或 NSFW 模型托管。
- **不**在云端为用户代跑 Stable Diffusion / FLUX。
- **不**帮用户绕过第三方平台（即梦等）的服务条款；云端与本地为**并列可选**后端。
- **不**保证 DLC 在所有 GPU（含核显、Mac 无 CUDA）上可用；最低支持 **NVIDIA + 4GB 显存**（见 §5）。

---

## 2. 产品边界与法律免责框架

> **以下为产品策略建议，正式文案需经法务审阅后写入 EULA / 安装器 / 应用内声明。**

### 2.1 三角关系

```text
┌─────────────────┐         HTTP（仅本机）        ┌──────────────────────────┐
│  NovFlow 主程序  │ ────────────────────────────► │  NovFlow 本地生图引擎（用户机） │
│  （设定/写作/UI） │ ◄──────────────────────────── │  独立进程 · 用户自担内容     │
└─────────────────┘         图片 bytes / 状态      └──────────────────────────┘
         │
         │ DeepSeek 等（云端，另议）
         ▼
   即梦 API（可选，非 DLC 范畴）
```

- **主程序**：提供「生图后端 = 即梦 | 本地 DLC | 关闭」切换；将提示词与参数转发至用户自启的本地引擎；接收 PNG 后存入用户自己的 MinIO/本地存储。
- **DLC**：独立安装、独立许可、独立进程；内含模型权重与推理运行时；**不**回传生成内容至 NovFlow 官方服务器（除非用户主动使用其他云功能）。

### 2.2 用户须确认的事项（首次启用 DLC 时）

建议在 DLC 控制台与 NovFlow 设置页**各展示一次**并记录确认时间戳（仅存用户本地 DB）：

1. 本地生图内容由**用户本人**生成并负责，NovFlow 及 DLC 提供方**不对其合法性、版权、肖像权、传播后果**承担责任。
2. 用户须**遵守所在地法律法规**；禁止用于制作、存储或传播违法内容（含未成年人相关、非自愿影像等）。
3. DLC **不包含**针对违法用途的主动审查，**亦不构成**对违法用途的鼓励或授权。
4. 向第三方平台上传 DLC 生成图片时，用户须自行遵守该平台规则。
5. 主程序与 DLC **分开发布**；未安装 DLC 时，NovFlow 行为与现版本一致。

### 2.3 分发建议

| 组件 | 分发渠道 | 说明 |
|------|----------|------|
| NovFlow 主程序 | 现有渠道 | 不含 SD 权重、不含 NSFW 模型 |
| Image Engine DLC | 独立下载页 / 网盘 / 离线安装包 | 大体积；可选 Lite/Standard/Pro 分包 |
| 可选模型包 | 同 DLC 渠道，增量包 | 用户按需安装，仍不经过官方推理服务器 |

**不建议**将完整 DLC 与主程序打在同一安装包内（体积、审核、责任边界均不利）。

---

## 3. 总体架构

### 3.1 逻辑分层

```text
┌─────────────────────────────────────────────────────────────┐
│ 前端 SettingsPage / 生图入口                                  │
│  - 生图后端：cloud_jimeng | local_dlc | off                  │
│  - DLC 状态：未安装 / 未启动 / 就绪 / 显存档 Lite|Std|Pro       │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST
┌───────────────────────────▼─────────────────────────────────┐
│  backend/app/services/image_providers/                       │
│  - JimengProvider（现有）                                     │
│  - LocalDlcProvider（新增）→ 127.0.0.1:17860                 │
│  - get_image_provider(user) 按用户设置路由                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ 仅当 local_dlc
┌───────────────────────────▼─────────────────────────────────┐
│  NovFlow 本地生图引擎（DLC 独立仓库/安装目录）                 │
│  - nf-image-engine.exe（或同名服务）                          │
│  - 内嵌 Python + diffusers/onnxruntime + CUDA 驱动检测        │
│  - 默认监听 127.0.0.1:17860（可配置，禁止 0.0.0.0 默认暴露）    │
│  - 模型目录 `{install_dir}/models/`（非 ProgramData）           │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 与现有代码的集成点

当前 `ImageProvider` 协议（见 `backend/app/services/image_providers/base.py`）已抽象：

```python
async def generate(user, prompt, *, reference_images, size) -> bytes
```

**集成原则：**

1. 新增 `LocalDlcProvider`，实现同一协议；`generate_and_store()` 无需改动调用方。
2. `get_image_provider(user)` 由「单例 Jimeng」改为「按 `user.image_backend` 或全局配置路由」。
3. `has_jimeng_key()` 与 `has_local_dlc()` 并列；写作 Agent / 章节插图在**无任一可用后端**时给出明确提示。
4. 云端即梦的「选段洗稿」逻辑（`build_image_safe_scene_brief`）在 **`local_dlc` 模式下可关闭或改为可选**，由用户设置「本地模式：原样提示词 / 轻度优化」。

---

## 4. DLC 组件构成

### 4.1 产品标识（与主程序分离，强制）

DLC **不得**与 NovFlow 主程序共用显示名、开始菜单文件夹、默认安装目录或 Inno Setup `AppId`：

| 项 | NovFlow 主程序 | NovFlow 本地生图引擎（DLC） |
|----|----------------|---------------------------|
| 显示名 / AppName | NovFlow | **NovFlow 本地生图引擎** |
| 开始菜单文件夹 | NovFlow | **NovFlow 本地生图引擎** |
| 默认安装目录 | `{autopf}\NovFlow` | **`{autopf}\NovFlowImageEngine`** |
| 安装包文件名 | `NovFlowSetup.exe` | `NovFlowImageEngineDLCSetup.exe` |
| AppId | `A7B3C9D1-…` | **独立 GUID**（见 `installer/novflow-dlc.iss`） |
| 互斥体 | `Global\NovFlowDesktopElectron` | `Global\NovFlowImageEngineDLC` |

构建：仓库根目录执行 `.\package-dlc.ps1`（可选 `-BundleLite` 内置约 4GB SD 1.5），输出 `dist/NovFlowImageEngineDLCSetup.exe`。

**模型目录：** 默认 `{安装目录}\models\`（例如 `D:\Applications\NovFlowImageEngine\models`），**不再**默认使用 `C:\ProgramData\NovFlowImageEngine\models`。旧版 ProgramData 中有权重时，首次启动控制台会提示迁移。未内置模型时，控制台「模型」页提供**一键下载 Lite 基础模型**（国内 ModelScope / hf-mirror，约 4GB）。

### 4.2 安装包内容（建议）

```text
NovFlowImageEngineDLCSetup.exe         # 安装器（Inno Setup；产品名「NovFlow 本地生图引擎」）
├── engine/
│   ├── nf-image-engine.exe            # 主服务（PyInstaller 单文件或目录式）
│   ├── _internal/                     # 内嵌运行时（用户不可见）
│   └── default_workflows/             # 预置 JSON（Lite/Std/Pro）
├── models/                            # 或安装时选择「仅引擎，模型后装」
│   ├── lite/
│   │   ├── v1-5-pruned-emaonly.safetensors
│   │   └── vae-ft-mse.safetensors
│   ├── standard/
│   │   └── sdxl_base_1.0.safetensors
│   └── pro/                           # 可选增量包
│       └── flux1-schnell-q4.safetensors
├── console/                           # 内置于 image_engine/console.py（Tk + pystray）
│   └── （GUI 控制台 + 托盘，默认启动方式）
├── LICENSE-DLC.txt                    # DLC 专用许可与免责
└── THIRD_PARTY_NOTICES.txt            # 开源模型与组件声明
```

### 4.3 引擎控制台（零代码配置）

面向非技术用户的**唯一**配置界面，功能最小集：

| 功能 | 说明 |
|------|------|
| 启动 / 停止引擎 | 图形控制台 + 系统托盘；关闭窗口隐藏到托盘，引擎继续运行；托盘「退出程序」完全停止 |
| 显存检测 | 读取 GPU 型号与 VRAM，推荐 Lite/Std/Pro |
| 模型包管理 | 已安装包列表；**一键下载** Lite/Standard（ModelScope 镜像）；**离线**导入 `.safetensors` |
| 端口与绑定 | 默认 `127.0.0.1:17860`；高级用户可改端口 |
| 性能档位 | 「省显存 / 均衡 / 质量」三档，映射到分辨率、步数、tile VAE |
| 连接测试 | 生成 64×64 测试图，供 NovFlow 设置页「测试本地引擎」调用 |
| 法律声明 | 查看 EULA；重置确认状态 |

**禁止**要求用户：编辑 `.env`、执行 `pip install`、配置 `CUDA_PATH`、使用 VPN 访问 HuggingFace。

### 4.4 离线分发策略

为满足「无需翻墙下载」：

1. **模型权重随 DLC 或国内镜像离线包提供**（百度网盘 / 阿里云盘 / 官方离线 CDN），安装器校验 SHA256。
2. 引擎**启动时不**访问 huggingface.co；仅读取本地 `models/`。
3. 更新通道：离线增量包（`NovFlow-ImageEngine-Models-Standard-1.1.zip`），控制台「导入更新包」。

---

## 5. 显存分级与性能策略

### 5.1 三档预设（Engine Tier）

| 档位 | 目标 VRAM | 默认模型 | 典型分辨率 | 步数 | 预期耗时（参考） |
|------|-----------|----------|------------|------|------------------|
| **Lite** | ≥ 4 GB | SD 1.5 + fp16/VAE tiling | 512×768（立绘）/ 768×432（插图） | 20–28 | 30–90 s/张 |
| **Standard** | ≥ 8 GB | SDXL base（或 SD 1.5 + 高清修复二阶段） | 832×1216 / 1024×576 | 24–32 | 15–45 s/张 |
| **Pro** | ≥ 12 GB | SDXL + refiner；≥16GB 可选 FLUX schnell | 1024×1536 / 1280×720 | 可配置 | 8–30 s/张 |

### 5.2 Lite（4GB）关键技术手段

引擎内部自动启用（用户无感）：

- `--medvram` 等价策略：分阶段加载 UNet / VAE / CLIP，生成后卸载。
- **VAE tiling / slicing**（`enable_vae_slicing`, `enable_vae_tiling`）。
- **注意力 slicing** 或 **xformers / sdpa**（按 GPU 能力探测）。
- **fp16 / bf16** 权重；必要时 **ONNX Runtime CUDA** 路径作为备选后端。
- 禁止 Lite 档默认加载 ControlNet / 多 LoRA 堆叠。
- **参考图生图**：Lite 仅支持 **单张** reference，且最长边 ≤ 768。

### 5.3 大显存优化

- 检测到 ≥12GB：允许 SDXL 原生分辨率、batch=1 多 LoRA（封面/角色风格包）。
- 检测到 ≥16GB：解锁 FLUX schnell 4-bit/8-bit 本地包（Pro 增量 DLC）。
- **队列**：引擎内 FIFO 队列，NovFlow 多章连续生图不并发抢 VRAM。

### 5.4 不支持环境（安装前检测并阻断）

- 无 NVIDIA 独显（仅 Intel/AMD 核显）：安装器提示「当前版本仅支持 NVIDIA CUDA」；后续可单独立项「CPU 极慢模式」但不作为 v1 承诺。
- 显存 &lt; 4GB：禁止启用 Lite，引导使用云端即梦或升级硬件。

---

## 6. 本地引擎 API 规范（NovFlow ↔ DLC）

建议固定 **NovFlow Image Engine HTTP API v1**，与 A1111 解耦，便于内嵌 diffusers、长期维护。

**Base URL：** `http://127.0.0.1:17860/v1`（仅 loopback）

### 6.1 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | `{ "status":"ok", "tier":"lite", "vram_mb":4096, "model":"sd15" }` |
| GET | `/capabilities` | 支持的分辨率、max_steps、ref_image、nsfw_filter:false |
| POST | `/generate` | 文生图 / 单图参考生图 |
| POST | `/generate/test` | 64×64 快速自检 |

### 6.2 `POST /generate` 请求体

```json
{
  "prompt": "小说章节插图，……",
  "negative_prompt": "low quality, blurry, watermark, text",
  "width": 768,
  "height": 432,
  "steps": 24,
  "seed": -1,
  "kind": "illustration",
  "reference_image_base64": null,
  "tier_override": null
}
```

**响应：** `image/png` 二进制，或 `{ "error": "..." }` JSON（4xx/5xx）。

### 6.3 与 NovFlow `ImageKind` 映射

| kind | 默认宽高比 | Lite 默认像素 |
|------|------------|---------------|
| cover | 2:3 | 512×768 |
| character | 9:16 | 512×912 |
| illustration | 16:9 | 768×432 |

`LocalDlcProvider.generate()` 负责把 `size_for_kind()` 转为 width/height；云端即梦继续使用原有 size 字符串。

### 6.4 安全绑定

- 默认 **`127.0.0.1`**，不接受公网入站。
- 可选 **本地 token**：NovFlow 设置页生成一次性 token 写入 DLC 配置，防止本机其他程序滥用（低优先级）。

---

## 7. NovFlow 主程序改造清单

### 7.1 数据模型

`users` 或全局 `settings` 表扩展（示例）：

| 字段 | 说明 |
|------|------|
| `image_backend` | `jimeng` \| `local_dlc` \| `off` |
| `local_dlc_base_url` | 默认 `http://127.0.0.1:17860/v1` |
| `local_dlc_tier` | `auto` \| `lite` \| `standard` \| `pro` |
| `local_dlc_prompt_mode` | `raw` \| `assist`（是否走 DeepSeek 场景改写） |
| `local_dlc_eula_accepted_at` | 首次确认时间 |

### 7.2 后端

- [x] `image_providers/local_dlc.py` — `LocalDlcProvider`
- [x] `resolve_image_backend(user)` / `has_image_generation(user)`
- [x] `GET /settings/image-engine/status` — 代理探测 DLC `/health`
- [x] `POST /settings/image-engine/test` — 测试生成
- [x] `POST /settings/image-engine/eula` — 免责声明确认
- [x] `image_gen.py` — `maybe_handle_chat_image` 分支：本地 `raw` 模式跳过云端洗稿
- [x] 错误类型统一：`ImageEngineError`（与 `JimengError` 并列），前端友好文案

### 7.3 前端

- [x] 设置页新增卡片：**本地生图扩展（DLC）**
  - 状态灯：未检测到 / 运行中 / 错误
  - 下载说明（文档链接 + stub 指引）
  - 后端切换：云端即梦 / 本地 DLC / 关闭
  - 「测试连接」「刷新状态」
  - 常驻免责摘要 + EULA 确认
- [x] 生图失败提示区分：云端审核 vs 本地 OOM vs 引擎未启动（后端文案 + 前端展示）

### 7.4 写作 Agent

- [x] 快捷操作「为本章生成场景插图」：若 `image_backend=local_dlc` + `raw`，选段直传本地
- [x] 回复模板区分：`已生成插图（本地引擎，未经云端审核）`

---

## 8. 引擎实现路线（推荐）

### 8.1 方案对比

| 方案 | 4GB 友好 | 离线打包 | 维护成本 | 建议 |
|------|----------|----------|----------|------|
| **A. 自研 diffusers 微服务** | 高（完全控制显存） | 中（PyInstaller + 内嵌 wheel） | 中 | **v1 首选** |
| B. 捆绑 A1111 便携版 | 中 | 低（现成） | 高（升级难、体积大） | 不推荐作 DLC 核心 |
| C. ComfyUI API | 高 | 低 | 高（workflow 复杂） | Pro 档或 v2 高级用户 |
| D. ONNX + DirectML | 核显可跑 | 中 | 高 | 后续 AMD/Intel 扩展 |

### 8.2 v1 推荐技术栈（方案 A）

| 层级 | 选型 |
|------|------|
| 推理 | `diffusers` + `torch`（CUDA 11.8/12.1 捆绑） |
| 服务 | `FastAPI` + `uvicorn`，单 worker（避免 VRAM 翻倍） |
| 打包 | PyInstaller `--onedir` + Inno Setup 安装器 |
| GPU 检测 | `pynvml` / `nvidia-sml-py` |
| 控制台 | Tauri 2 或 PySide6 小窗（二选一） |
| 模型格式 | `.safetensors` 本地路径加载 |

**独立仓库建议：** `novflow-image-engine/`（与 `novflow/` 主仓分离），主仓仅保留 `LocalDlcProvider` 客户端与文档。

---

## 9. 内容策略（本地无审查）

### 9.1 引擎侧

- **不部署** NSFW 分类器、不调用外部审核 API。
- `negative_prompt` 仅用于**画质**（模糊、水印、畸形），不用于道德过滤。
- 日志**默认不记录**完整 prompt 到磁盘；调试模式需用户显式开启。

### 9.2 主程序侧

- NovFlow **不预览、不上传、不备份**用户本地生图到官方服务器（现有 MinIO 为用户自建或本地 Docker 时仍属用户基础设施）。
- 文档与 EULA 明确：本地模式下的提示词与成图**均为用户数据**。

### 9.3 与云端路径并存

| 后端 | 内容策略 | 适用 |
|------|----------|------|
| 即梦 | 平台审核 + 可选 DeepSeek 洗稿 | 免安装、合规保守 |
| 本地 DLC | 无审查，用户自负 | 创作自由、离线、敏感选段 |
| off | — | 仅手动上传图片 |

---

## 10. 实施路线图（建议）

### Phase 0 — 文档与法务（1 周）

- [ ] 定稿 `LICENSE-DLC.txt`、安装器勾选文案、设置页声明
- [ ] 确认 DLC 与主程序分开发布流程

### Phase 1 — 引擎 MVP（3–4 周）

- [ ] `novflow-image-engine`：Lite 档 SD1.5 + `/health` + `/generate`
- [ ] PyInstaller Windows 安装包 + 控制台启动/停止
- [ ] 捆绑 Lite 模型离线包（约 2–4 GB）

### Phase 2 — NovFlow 对接（1–2 周）

- [x] `LocalDlcProvider` + 设置页 + 健康检查（stub 引擎 `image-engine/`）
- [ ] 封面 / 立绘 / 插图三路径端到端测试（需 stub 或正式引擎联调）

### Phase 3 — Standard/Pro 与体验（2–3 周）

- [ ] SDXL / FLUX 增量包、显存自动分档
- [ ] 参考图生图（单图）、队列与进度回调（可选 WebSocket）
- [ ] 写作 Agent 本地模式与 `raw` 提示词

### Phase 4 — 发布与维护

- [ ] 离线更新包机制、版本兼容矩阵（NovFlow x.x ↔ Engine x.y）
- [ ] 用户文档：《DLC 安装指南》（图文，无命令行）

---

## 11. 风险与限制

| 风险 | 缓解 |
|------|------|
| DLC 体积大、下载慢 | Lite/Standard/Pro 分包；国内离线网盘 |
| 4GB 仍 OOM | 安装前检测；运行时捕获 OOM 并建议降档 |
| NVIDIA 驱动/CUDA 版本碎片化 | 安装器预检；捆绑匹配 torch wheel；文档列明最低驱动版本 |
| 用户误认「官方提供黄色内容」 | 分开发布 + EULA + UI 强调「本地自负」 |
| 地方法律差异 | EULA 要求用户自行合规；不提供违法内容教程 |
| 开源模型许可证 | SD/SDXL/FLUX 各自 license 写入 `THIRD_PARTY_NOTICES` |
| Mac / Linux 用户 | v1 仅 Windows；后续评估 |

---

## 12. 附录

### 12.1 名词表

| 术语 | 含义 |
|------|------|
| **主程序** | NovFlow 应用（写作、设定、云端即梦） |
| **NovFlow 本地生图引擎** | 可选本地生图扩展安装包（独立于主程序） |
| **Lite / Standard / Pro** | 按显存与模型能力划分的引擎档位 |

### 12.2 相关文档

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 现有 `ImageProvider` 与即梦路径
- [STANDALONE_DESKTOP.md](./STANDALONE_DESKTOP.md) — 桌面一键安装与本地存储策略
- [PRODUCT_ROADMAP.md](./PRODUCT_ROADMAP.md) — 产品路线图

### 12.3 文档变更记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.2 | 2026-07 | 模型目录改至安装目录；GUI 一键下载 Lite；可选 -BundleLite 打包 SD 1.5 |
| 0.1 | 2026-06 | 初稿：DLC 边界、三档显存、API、集成清单、免责框架 |

---

**免责声明（文档级）：** 本文档为内部技术方案，不构成法律意见。对外发布的 EULA、隐私政策与用户提示须由具备资质的法律顾问审定。
