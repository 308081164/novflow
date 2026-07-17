# NovFlow 激活码格式与签发说明

NovFlow 使用与降 AIGC 工具相同的 **离线 Ed25519 签名**机制，仅 `product_id` 等产品标识不同。

## 产品标识（独立密钥域）

| 产品 | `product_id` | `layout` | 本地许可文件 |
|------|--------------|----------|--------------|
| NovFlow Desktop | `novflow_desktop` | `1` | `%LocalAppData%\NovFlow\data\config\novflow-desktop-license.json` |
| NovFlow 本地生图引擎 | `novflow_image_dlc` | `1` | `%LocalAppData%\NovFlow\data\config\novflow-image-dlc-license.json` |

Desktop 激活码 **不能** 解锁 DLC，反之亦然（payload 中 `product_id` 校验）。

## 激活码字符串格式

```
v1.<base64url(compact_json)>.<base64url(ed25519_signature)>
```

### Payload JSON 字段

```json
{
  "product_id": "novflow_desktop",
  "layout": "1",
  "hw_id": "<64位hex>",
  "license_mode": "permanent|time_limited",
  "tier": "full",
  "issued_at": "YYYY-MM-DD",
  "activate_before": "YYYY-MM-DD",
  "valid_until": "YYYY-MM-DD",
  "batch_id": "...",
  "customer_ref": "..."
}
```

### 授权模式与过期规则

| `license_mode` | 过期字段 | 行为 |
|----------------|----------|------|
| `permanent` | 可选 `activate_before` | 仅限制**首次激活**截止日期；激活后永久有效 |
| `time_limited` | **必填** `valid_until` | 到期日**当天仍有效**，次日 0 点起拒绝激活与 AI 功能 |
| 任意 | 若 payload 含 `valid_until` | 客户端每次验签后均校验该日期（防止误签） |

**管理员签发限时授权时：**

- CLI：`--mode time_limited --valid-until 2026-12-31`
- 若仅写 `--valid-until` 未指定 mode，CLI 会自动切换为 `time_limited`
- Android 管理端：选择「限时」并填写 `YYYY-MM-DD`

**切勿**在 `permanent` 模式下填写有效期——该字段不会写入签名 payload，用户将永久可用。

日期格式统一为 **本地日历日 `YYYY-MM-DD`**（比较使用 `date.today()`，非 UTC 时间戳）。

## 设备指纹 HW_ID

```
SHA256( "NOVFLOW-LICENSE-v1" + product_id|layout|machineGuid|cpuId|diskSerial|mac )
```

- 输出 64 位小写 hex
- 短 ID（前 16 位大写）仅用于展示，**不可用于签发**

## 激活设备码

- HMAC-SHA256 密钥：`novflow-activation-key-v1`（hex: `6e6f76666c6f772d61637469766174696f6e2d6b65792d7631`）
- 输入：`hw_id + product_id + layout`
- 28 位 Crockford Base32 + Luhn mod-32 校验位
- 显示为 7 组 × 4 字符，用 `-` 分隔

## 密钥管理

| 文件 | 说明 |
|------|------|
| `tools/.issuer-private.der` | Ed25519 私钥 PKCS#8 DER（**勿提交 git**） |
| `shared/license/license_keys.py` | 客户端内置公钥 SPKI DER hex |

导出私钥 hex（用于 GitHub Secret）：

```powershell
[BitConverter]::ToString([IO.File]::ReadAllBytes("tools\.issuer-private.der")).Replace("-","").ToLower()
```

## 签发方式

### CLI（桌面管理员）

```powershell
py -3 tools\generate_license.py generate --product desktop --hw-id <64位HW_ID>
py -3 tools\generate_license.py generate --product dlc --hw-id <64位HW_ID>
py -3 tools\generate_license.py verify --product desktop --hw-id <HW_ID> --code "v1...."
```

### Android APK

仓库内 `mobile/license-admin-android/`，CI 构建后安装。在「生成」页选择产品类型后签发。

## GitHub Actions Secret

| Secret | 用途 |
|--------|------|
| `NOVFLOW_ISSUER_PRIVATE_PKCS8_HEX` | APK CI 注入私钥到 assets |
| `NOVFLOW_PUBKEY` | 可选，覆盖客户端内置公钥（测试） |

触发 tag：`license-admin-v*` 或手动 `workflow_dispatch`。

## 客户端验证流程

1. 读取本地许可 JSON
2. 拒绝 `deactivated: true`
3. 对存储的 `license_code` 重新验签 + `product_id` + `hw_id` + **当日日期过期校验**
4. **每次 API 请求**（`require_desktop_license`）与状态查询均重新校验，不信任缓存布尔值
5. 到期后 AI 路由返回 403，`error: license_expired`
