import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { CheckCircle, HardDrive, Key, Loader2, Save, Shield, Sparkles } from "lucide-react";

import { api, type ImageEngineStatus, type LicenseStatus } from "../api";

import { PageHeader } from "../components/Layout";

import { useAuth } from "../auth";

const JIMENG_MODEL_PRESETS = [
  { id: "doubao-seedream-4-0-250828", label: "Seedream 4.0（稳定，推荐首选）" },
  { id: "doubao-seedream-4-5-251128", label: "Seedream 4.5（较新，需单独开通）" },
  { id: "doubao-seedream-5-0-260128", label: "Seedream 5.0 lite（需单独开通）" },
] as const;

const DEFAULT_JIMENG_MODEL = JIMENG_MODEL_PRESETS[0].id;



export default function SettingsPage() {

  const { user, refreshUser } = useAuth();

  const [masked, setMasked] = useState("");

  const [configured, setConfigured] = useState(false);

  const [apiKey, setApiKey] = useState("");

  const [displayName, setDisplayName] = useState(user?.display_name || "");

  const [jimengMasked, setJimengMasked] = useState("");

  const [jimengConfigured, setJimengConfigured] = useState(false);

  const [jimengApiKey, setJimengApiKey] = useState("");

  const [jimengBaseUrl, setJimengBaseUrl] = useState("https://ark.cn-beijing.volces.com/api/v3");

  const [jimengModel, setJimengModel] = useState(DEFAULT_JIMENG_MODEL);

  const [testingJimeng, setTestingJimeng] = useState(false);

  const [jimengTestMsg, setJimengTestMsg] = useState("");

  const [imageBackend, setImageBackend] = useState<"jimeng" | "local_dlc" | "off">("jimeng");

  const [localDlcBaseUrl, setLocalDlcBaseUrl] = useState("http://127.0.0.1:17860/v1");

  const [localDlcTier, setLocalDlcTier] = useState("auto");

  const [localDlcPromptMode, setLocalDlcPromptMode] = useState<"raw" | "assist">("raw");

  const [eulaAccepted, setEulaAccepted] = useState(false);

  const [eulaChecked, setEulaChecked] = useState(false);

  const [engineStatus, setEngineStatus] = useState<ImageEngineStatus | null>(null);

  const [loadingEngineStatus, setLoadingEngineStatus] = useState(false);

  const [testingEngine, setTestingEngine] = useState(false);

  const [engineTestMsg, setEngineTestMsg] = useState("");

  const [acceptingEula, setAcceptingEula] = useState(false);

  const [msg, setMsg] = useState("");

  const [err, setErr] = useState("");

  const [saving, setSaving] = useState(false);

  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null);

  const [licenseDeviceCode, setLicenseDeviceCode] = useState("");

  const [licenseCode, setLicenseCode] = useState("");

  const [activatingLicense, setActivatingLicense] = useState(false);

  const [licenseMsg, setLicenseMsg] = useState("");

  const [licenseEulaChecked, setLicenseEulaChecked] = useState(false);



  useEffect(() => {

    api.getSettings().then((s) => {

      setMasked(s.deepseek_api_key_masked);

      setConfigured(s.deepseek_configured);

      setDisplayName(s.display_name);

      setJimengMasked(s.jimeng_api_key_masked);

      setJimengConfigured(s.jimeng_configured);

      setJimengBaseUrl(s.jimeng_base_url || "https://ark.cn-beijing.volces.com/api/v3");

      setJimengModel(s.jimeng_model || DEFAULT_JIMENG_MODEL);

      setImageBackend(s.image_backend || "jimeng");

      setLocalDlcBaseUrl(s.local_dlc_base_url || "http://127.0.0.1:17860/v1");

      setLocalDlcTier(s.local_dlc_tier || "auto");

      setLocalDlcPromptMode(s.local_dlc_prompt_mode || "raw");

      setEulaAccepted(s.local_dlc_eula_accepted);

    });

    api.getLicenseStatus().then(async (st) => {
      setLicenseStatus(st);
      if (st.desktop_mode && !st.activated) {
        try {
          const dev = await api.getLicenseDevice();
          setLicenseDeviceCode(dev.device_code);
        } catch {
          /* ignore */
        }
      }
    }).catch(() => {
      /* non-desktop or API unavailable */
    });

  }, []);



  const refreshLicenseStatus = async () => {
    const st = await api.getLicenseStatus();
    setLicenseStatus(st);
    if (st.desktop_mode && !st.activated) {
      const dev = await api.getLicenseDevice();
      setLicenseDeviceCode(dev.device_code);
    }
  };



  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setLicenseMsg(`${label}已复制`);
    } catch {
      setLicenseMsg(`复制失败，请手动选择 ${label}`);
    }
  };



  const activateLicense = async () => {
    const code = licenseCode.trim();
    if (!code) {
      setErr("请先粘贴激活码");
      return;
    }
    if (!licenseEulaChecked) {
      setErr("请先阅读并同意软件许可协议");
      return;
    }
    setActivatingLicense(true);
    setErr("");
    setLicenseMsg("");
    try {
      await api.activateLicense(code);
      setLicenseCode("");
      await refreshLicenseStatus();
      setLicenseMsg("激活成功，已解锁完整功能");
    } catch (e) {
      setErr(String(e));
    } finally {
      setActivatingLicense(false);
    }
  };



  const deactivateLicense = async () => {
    if (!window.confirm("确定卸载本机授权？")) return;
    setActivatingLicense(true);
    setErr("");
    setLicenseMsg("");
    try {
      await api.deactivateLicense();
      await refreshLicenseStatus();
      setLicenseMsg("授权已卸载");
    } catch (e) {
      setErr(String(e));
    } finally {
      setActivatingLicense(false);
    }
  };



  const refreshEngineStatus = async () => {

    setLoadingEngineStatus(true);

    try {

      const st = await api.getImageEngineStatus();

      setEngineStatus(st);

    } catch {

      setEngineStatus(null);

    } finally {

      setLoadingEngineStatus(false);

    }

  };



  useEffect(() => {

    if (imageBackend === "local_dlc") {

      refreshEngineStatus();

    }

  }, [imageBackend]);



  const save = async () => {

    setSaving(true);

    setErr("");

    try {

      const data: {

        display_name?: string;

        deepseek_api_key?: string;

        jimeng_api_key?: string;

        jimeng_base_url?: string;

        jimeng_model?: string;

        image_backend?: "jimeng" | "local_dlc" | "off";

        local_dlc_base_url?: string;

        local_dlc_tier?: string;

        local_dlc_prompt_mode?: "raw" | "assist";

      } = {

        display_name: displayName,

        jimeng_base_url: jimengBaseUrl,

        jimeng_model: jimengModel,

        image_backend: imageBackend,

        local_dlc_base_url: localDlcBaseUrl,

        local_dlc_tier: localDlcTier,

        local_dlc_prompt_mode: localDlcPromptMode,

      };

      if (apiKey.trim()) data.deepseek_api_key = apiKey.trim();

      if (jimengApiKey.trim()) data.jimeng_api_key = jimengApiKey.trim();

      const s = await api.updateSettings(data);

      setConfigured(s.deepseek_configured);

      setMasked(s.deepseek_api_key_masked);

      setJimengConfigured(s.jimeng_configured);

      setJimengMasked(s.jimeng_api_key_masked);

      setApiKey("");

      setJimengApiKey("");

      setEulaAccepted(s.local_dlc_eula_accepted);

      setMsg("设置已保存");

      await refreshUser();

    } catch (e) {

      setErr(String(e));

    } finally {

      setSaving(false);

    }

  };



  const acceptEula = async () => {

    if (!eulaChecked) {

      setErr("请先勾选免责声明");

      return;

    }

    setAcceptingEula(true);

    setErr("");

    try {

      const s = await api.acceptImageEngineEula();

      setEulaAccepted(s.local_dlc_eula_accepted);

      setMsg("已确认本地生图免责声明");

    } catch (e) {

      setErr(String(e));

    } finally {

      setAcceptingEula(false);

    }

  };



  const testLocalEngine = async () => {

    setTestingEngine(true);

    setEngineTestMsg("");

    setErr("");

    try {

      const res = await api.testImageEngine();

      setEngineTestMsg(res.message || "连接成功");

      await refreshEngineStatus();

    } catch (e) {

      setEngineTestMsg("");

      setErr(String(e));

    } finally {

      setTestingEngine(false);

    }

  };



  const engineStatusLabel = () => {

    if (imageBackend !== "local_dlc") return null;

    if (!eulaAccepted) return { text: "待确认免责声明", color: "text-amber-600" };

    if (loadingEngineStatus) return { text: "检测中…", color: "text-slate-500" };

    if (!engineStatus) return { text: "未知", color: "text-slate-500" };

    if (engineStatus.reachable) {

      const tier = engineStatus.tier ? ` · ${engineStatus.tier}` : "";

      return { text: `运行中${tier}`, color: "text-emerald-600" };

    }

    return { text: engineStatus.message || "未检测到引擎", color: "text-red-600" };

  };



  const statusInfo = engineStatusLabel();



  const testJimeng = async () => {

    setTestingJimeng(true);

    setJimengTestMsg("");

    setErr("");

    try {

      const res = await api.testJimeng({

        api_key: jimengApiKey.trim() || undefined,

        base_url: jimengBaseUrl.trim() || undefined,

        model: jimengModel.trim() || undefined,

      });

      if (res.model && res.model !== jimengModel.trim()) {
        setJimengModel(res.model);
      }
      setJimengTestMsg(res.message || "连接成功");

    } catch (e) {

      setJimengTestMsg("");

      setErr(String(e));

    } finally {

      setTestingJimeng(false);

    }

  };



  return (

    <div className="max-w-xl">

      <PageHeader title="账号设置" desc="配置 DeepSeek 与即梦 API，启用文本生成与 AI 绘图" />

      {msg && <div className="mb-4 rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{msg}</div>}

      {err && <div className="mb-4 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{err}</div>}



      <div className="card space-y-5 p-6">

        {licenseStatus?.desktop_mode && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-4">
            <label className="label flex items-center gap-2">
              <Shield className="h-4 w-4" /> 产品授权
            </label>
            {licenseStatus.activated ? (
              <p className="text-sm text-emerald-700">
                已激活 — {licenseStatus.product_name || "NovFlow"}
                {licenseStatus.valid_until
                  ? `（有效期至 ${licenseStatus.valid_until}）`
                  : licenseStatus.license_mode
                    ? `（${licenseStatus.license_mode}）`
                    : ""}
              </p>
            ) : (
              <p className="text-sm text-amber-800">
                未激活{licenseStatus.error?.includes("过期") ? "（授权已过期）" : ""} —{" "}
                {licenseStatus.error || "请完成授权激活"}
              </p>
            )}
            {!licenseStatus.activated && licenseStatus.hw_id && (
              <div className="mt-3 space-y-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-600">设备指纹</span>
                  <code className="rounded bg-white px-2 py-1 font-mono">{licenseStatus.short_hw_id || licenseStatus.hw_id}</code>
                  <button type="button" className="btn-secondary text-xs" onClick={() => copyText(licenseStatus.hw_id || "", "HW_ID")}>
                    复制 HW_ID
                  </button>
                </div>
                {licenseDeviceCode && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-600">设备码</span>
                    <code className="rounded bg-white px-2 py-1 font-mono">{licenseDeviceCode}</code>
                    <button type="button" className="btn-secondary text-xs" onClick={() => copyText(licenseDeviceCode, "设备码")}>
                      复制设备码
                    </button>
                  </div>
                )}
              </div>
            )}
            {!licenseStatus.activated && (
              <>
                <textarea
                  className="input mt-3 min-h-[88px] font-mono text-sm"
                  placeholder="粘贴激活码（格式：v1.xxxxx.yyyyy）"
                  value={licenseCode}
                  onChange={(e) => setLicenseCode(e.target.value)}
                />
                <label className="mt-3 flex items-start gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={licenseEulaChecked}
                    onChange={(e) => setLicenseEulaChecked(e.target.checked)}
                  />
                  <span>
                    我已阅读并同意 NovFlow 软件许可协议：激活码与本机绑定，禁止转售或共享；AI 生成内容需用户自行审核与合规使用。
                  </span>
                </label>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" className="btn-primary text-sm" onClick={activateLicense} disabled={activatingLicense}>
                    {activatingLicense ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    激活
                  </button>
                </div>
              </>
            )}
            {licenseStatus.activated && (
              <button type="button" className="btn-secondary mt-3 text-xs" onClick={deactivateLicense} disabled={activatingLicense}>
                卸载授权
              </button>
            )}
            {licenseMsg && <p className="mt-2 text-xs text-emerald-600">{licenseMsg}</p>}
            <p className="mt-2 text-[11px] text-slate-500">激活码离线验证，无需联网。未激活时部分功能可能受限。</p>
          </div>
        )}

        <div>

          <label className="label">昵称</label>

          <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />

        </div>

        <div>

          <label className="label flex items-center gap-2">

            <Key className="h-4 w-4" /> DeepSeek API Key

          </label>

          <p className="mb-2 text-xs text-slate-500">

            在{" "}

            <a href="https://platform.deepseek.com" target="_blank" rel="noreferrer" className="text-brand-600">

              platform.deepseek.com

            </a>{" "}

            获取。Key 仅保存在你的账号下，不会展示完整内容。

          </p>

          {configured && <p className="mb-2 text-sm text-emerald-600">已配置：{masked || "****"}</p>}

          <input

            className="input font-mono"

            type="password"

            placeholder="sk-...（留空则不修改）"

            value={apiKey}

            onChange={(e) => setApiKey(e.target.value)}

          />

        </div>



        <div className="border-t border-slate-100 pt-5">

          <label className="label flex items-center gap-2">

            <Sparkles className="h-4 w-4" /> 即梦 / Seedream API（火山方舟）

          </label>

          <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 leading-relaxed">

            <p className="font-medium text-slate-800">配置指南</p>

            <ol className="mt-2 list-decimal space-y-1 pl-4">

              <li>

                登录{" "}

                <a

                  href="https://console.volcengine.com/ark/region:ark+cn-beijing/apikey"

                  target="_blank"

                  rel="noreferrer"

                  className="text-brand-600"

                >

                  火山方舟控制台

                </a>{" "}

                创建 API Key

              </li>

              <li>
                在
                <a
                  href="https://console.volcengine.com/ark/region:ark+cn-beijing/model"
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-600"
                >
                  模型广场
                </a>
                开通 Seedream 图像模型（建议先开通 4.0：doubao-seedream-4-0-250828）
              </li>

              <li>将 API Key 填入下方；Base URL 默认即可（北京区域 ark.cn-beijing.volces.com）</li>

              <li>保存后点击「测试连接」验证；Docker 部署需确保 MinIO 已启用以持久化图片</li>

            </ol>

          </div>

          {jimengConfigured && <p className="mb-2 text-sm text-emerald-600">已配置：{jimengMasked || "****"}</p>}

          <div className="space-y-3">

            <input

              className="input font-mono"

              type="password"

              placeholder="ARK API Key（留空则不修改）"

              value={jimengApiKey}

              onChange={(e) => setJimengApiKey(e.target.value)}

            />

            <input

              className="input font-mono text-sm"

              placeholder="Base URL"

              value={jimengBaseUrl}

              onChange={(e) => setJimengBaseUrl(e.target.value)}

            />

            <div>
              <label className="label text-xs">模型 ID</label>
              <select
                className="input font-mono text-sm"
                value={JIMENG_MODEL_PRESETS.some((p) => p.id === jimengModel) ? jimengModel : "__custom__"}
                onChange={(e) => {
                  if (e.target.value !== "__custom__") setJimengModel(e.target.value);
                }}
              >
                {JIMENG_MODEL_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
                <option value="__custom__">自定义模型 ID…</option>
              </select>
            </div>
            {!JIMENG_MODEL_PRESETS.some((p) => p.id === jimengModel) && (
              <input
                className="input font-mono text-sm"
                placeholder="自定义模型 ID"
                value={jimengModel}
                onChange={(e) => setJimengModel(e.target.value)}
              />
            )}
            {JIMENG_MODEL_PRESETS.some((p) => p.id === jimengModel) && (
              <p className="text-[11px] text-slate-500">当前：{jimengModel}</p>
            )}

          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">

            <button type="button" className="btn-secondary text-xs" onClick={testJimeng} disabled={testingJimeng}>

              {testingJimeng ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle className="h-3.5 w-3.5" />}

              测试连接

            </button>

            {jimengTestMsg && <span className="text-xs text-emerald-600">{jimengTestMsg}</span>}

          </div>

        </div>



        <div className="border-t border-slate-100 pt-5">

          <label className="label flex items-center gap-2">

            <HardDrive className="h-4 w-4" /> 本地生图扩展（DLC）

          </label>

          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 leading-relaxed">

            <p className="font-medium">免责摘要</p>

            <ul className="mt-2 list-disc space-y-1 pl-4">

              <li>本地生图内容由用户本人生成并负责；NovFlow 不对其合法性、版权与传播后果承担责任。</li>

              <li>DLC 为独立可选扩展，不含内容审查；须遵守所在地法律法规。</li>

              <li>主程序与 DLC 分开发布；未安装时行为与现版本一致。</li>

            </ul>

          </div>

          <div className="space-y-3">

            <div>

              <label className="label text-xs">生图后端</label>

              <select

                className="input text-sm"

                value={imageBackend}

                onChange={(e) => setImageBackend(e.target.value as "jimeng" | "local_dlc" | "off")}

              >

                <option value="jimeng">云端即梦</option>

                <option value="local_dlc">本地 DLC</option>

                <option value="off">关闭生图</option>

              </select>

            </div>

            {statusInfo && (

              <p className={`text-sm ${statusInfo.color}`}>引擎状态：{statusInfo.text}</p>

            )}

            {!eulaAccepted && imageBackend === "local_dlc" && (

              <div className="rounded-lg border border-slate-200 p-3">

                <label className="flex items-start gap-2 text-sm">

                  <input

                    type="checkbox"

                    className="mt-1"

                    checked={eulaChecked}

                    onChange={(e) => setEulaChecked(e.target.checked)}

                  />

                  <span>我已阅读并同意本地生图免责声明，知晓内容自负且 DLC 不含审查。</span>

                </label>

                <button

                  type="button"

                  className="btn-secondary mt-2 text-xs"

                  onClick={acceptEula}

                  disabled={acceptingEula}

                >

                  {acceptingEula ? "提交中…" : "确认并启用"}

                </button>

              </div>

            )}

            {imageBackend === "local_dlc" && eulaAccepted && (

              <>

                <input

                  className="input font-mono text-sm"

                  placeholder="DLC Base URL"

                  value={localDlcBaseUrl}

                  onChange={(e) => setLocalDlcBaseUrl(e.target.value)}

                />

                <div className="grid grid-cols-2 gap-2">

                  <div>

                    <label className="label text-xs">显存档</label>

                    <select

                      className="input text-sm"

                      value={localDlcTier}

                      onChange={(e) => setLocalDlcTier(e.target.value)}

                    >

                      <option value="auto">自动</option>

                      <option value="lite">Lite（4GB+）</option>

                      <option value="standard">Standard（8GB+）</option>

                      <option value="pro">Pro（12GB+）</option>

                    </select>

                  </div>

                  <div>

                    <label className="label text-xs">提示词模式</label>

                    <select

                      className="input text-sm"

                      value={localDlcPromptMode}

                      onChange={(e) => setLocalDlcPromptMode(e.target.value as "raw" | "assist")}

                    >

                      <option value="raw">原样（不洗稿）</option>

                      <option value="assist">轻度优化（DeepSeek）</option>

                    </select>

                  </div>

                </div>

                <p className="text-[11px] text-slate-500">

                  DLC 需单独下载安装，详见项目文档 LOCAL_IMAGE_DLC.md。开发测试可运行{" "}

                  <code className="rounded bg-slate-100 px-1">image-engine/start.ps1</code> stub。

                </p>

                <div className="flex flex-wrap items-center gap-2">

                  <button

                    type="button"

                    className="btn-secondary text-xs"

                    onClick={testLocalEngine}

                    disabled={testingEngine}

                  >

                    {testingEngine ? (

                      <Loader2 className="h-3.5 w-3.5 animate-spin" />

                    ) : (

                      <CheckCircle className="h-3.5 w-3.5" />

                    )}

                    测试本地引擎

                  </button>

                  <button type="button" className="btn-secondary text-xs" onClick={refreshEngineStatus}>

                    刷新状态

                  </button>

                  {engineTestMsg && <span className="text-xs text-emerald-600">{engineTestMsg}</span>}

                </div>

              </>

            )}

          </div>

        </div>



        <button className="btn-primary" onClick={save} disabled={saving}>

          <Save className="h-4 w-4" /> {saving ? "保存中…" : "保存设置"}

        </button>

      </div>



      <p className="mt-6 text-sm text-slate-500">

        服务器 .env 中的全局 Key 可作为后备；你在此处配置的 Key 优先级更高。

      </p>

      <Link to="/dashboard" className="mt-4 inline-block text-sm text-brand-600 hover:underline">

        返回书库

      </Link>

    </div>

  );

}


