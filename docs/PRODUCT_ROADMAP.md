# NovFlow 产品路线图

> **版本：** 0.1 · **日期：** 2026-07  
> **性质：** 权威设计决策汇总（与旧文档冲突时以本文为准）

---

## 三大支柱

### 1. 桌面壳（换壳）

**决策：** v1 从「系统浏览器 + 隐藏 uvicorn」升级为 **嵌入式 WebView**，FastAPI 仍作为 localhost sidecar。

| 项 | v1（当前） | 未来选项 |
|----|-----------|----------|
| 壳 | **pywebview**（Windows WebView2） | Electron / Tauri |
| 后端 | 捆绑 Python + uvicorn @ 127.0.0.1 | 不变 |
| 打包 | 增强现有 PyInstaller launcher | 独立原生壳 |
| 回退 | pywebview 不可用时打开系统浏览器 | — |

**阶段与估算：**

| 阶段 | 内容 | 人日 |
|------|------|------|
| P0 ✅ | pywebview 窗口、1280×800、单实例 mutex | 2–3 |
| P1 | 系统托盘、开机自启 | 3–5 |
| P2 | 首次运行向导（Key / 数据目录） | 2–3 |
| P3 | 自动更新通道 | 5–8 |

→ 详见 [STANDALONE_DESKTOP.md](./STANDALONE_DESKTOP.md)

---

### 2. 类 Git 书籍版本（非 raw Git）

**决策：** 产品模型 = **书籍检查点** + **章节版本时间线** + **Agent apply_edits 前自动检查点**。完整 Git 分支合并 **延后**。

| 能力 | 实现基础 | 状态 |
|------|----------|------|
| 章节历史 | `ChapterVersion` 表（append-only） | ✅ 已有 |
| 手动/Agent 落库前快照 | apply_edits 前写入 version | 待做 |
| 书籍级检查点 | 新书级 `BookCheckpoint` 或打包快照 | 待做 |
| Git 分支 / merge | — | **Deferred** |

**阶段与估算：**

| 阶段 | 内容 | 人日 |
|------|------|------|
| P0 | apply_edits 自动 ChapterVersion | 2–3 |
| P1 | 书籍检查点 UI（列表 / 恢复） | 5–8 |
| P2 | 检查点与云同步 manifest 对齐 | 8–12 |
| — | Git 式分支 | 不纳入 v1 |

→ 与 [HYBRID_ARCHITECTURE.md](./HYBRID_ARCHITECTURE.md) §3.3 变更日志互补

---

### 3. 云控制面 Hub

**决策：** 独立 **控制面服务** 负责 auth、会员、激活码、备份/同步、Admin/客服；业务 Agent 仍在主仓或 sidecar。

| 模块 | 形态 | 说明 |
|------|------|------|
| 首版架构 | **模块化单体** | `routers/admin`、`routers/sync` |
| API Key | 用户本地加密 **或** 平台代理代调 | 永不进 sync payload |
| 备份格式 | `.novflow.zip` v0 | 整书 JSON + MD + 图片 manifest |
| MinIO 多租户 | key 前缀 **`{cloud_uuid}/`** | 必须，防泄漏 |

**阶段与估算：**

| 阶段 | 内容 | 人日 |
|------|------|------|
| P0 | PG 多租户 + media 鉴权 + uuid key | 10–15 |
| P1 | Admin + 激活码 + 会员 gate | 15–20 |
| P2 | 按书 sync MVP（LWW + 变更日志） | 20–30 |
| P3 | `.novflow.zip` 备份/恢复 | 8–12 |

→ 详见 [HYBRID_ARCHITECTURE.md](./HYBRID_ARCHITECTURE.md)

---

## 横切：本地生图 DLC

可选扩展，主程序仅客户端 + 设置；引擎独立分发。

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 2 | LocalDlcProvider + 设置页 + stub 引擎 | 进行中 |
| Phase 1 | diffusers 完整引擎 + 安装包 | Deferred |
| Phase 3 | Standard/Pro 档、参考图生图 | Deferred |

→ [LOCAL_IMAGE_DLC.md](./LOCAL_IMAGE_DLC.md)

---

## 推荐执行顺序（单人全栈）

```text
P0 桌面 WebView ─┬─► P0 DLC 对接（stub）
                 └─► P0 版本自动检查点
        ↓
P1 云多租户基线 + Admin/激活码
        ↓
P2 按书 sync 或 .novflow.zip 备份（二选一 MVP）
        ↓
P3 完整 sync + DLC 正式引擎分包
```

**总估算（完整愿景）：** 90–135 人日（与 HYBRID_ARCHITECTURE 一致；桌面壳方案改为 pywebview 后 P0 略减）

---

## 相关文档

- [HYBRID_ARCHITECTURE.md](./HYBRID_ARCHITECTURE.md) — 混合部署与 sync
- [STANDALONE_DESKTOP.md](./STANDALONE_DESKTOP.md) — Windows 离线安装
- [LOCAL_IMAGE_DLC.md](./LOCAL_IMAGE_DLC.md) — 本地生图扩展
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 当前系统架构
