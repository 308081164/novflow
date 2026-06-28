import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { CheckCircle, Key, Loader2, Save, Sparkles } from "lucide-react";

import { api } from "../api";

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

  const [msg, setMsg] = useState("");

  const [err, setErr] = useState("");

  const [saving, setSaving] = useState(false);



  useEffect(() => {

    api.getSettings().then((s) => {

      setMasked(s.deepseek_api_key_masked);

      setConfigured(s.deepseek_configured);

      setDisplayName(s.display_name);

      setJimengMasked(s.jimeng_api_key_masked);

      setJimengConfigured(s.jimeng_configured);

      setJimengBaseUrl(s.jimeng_base_url || "https://ark.cn-beijing.volces.com/api/v3");

      setJimengModel(s.jimeng_model || DEFAULT_JIMENG_MODEL);

    });

  }, []);



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

      } = { display_name: displayName, jimeng_base_url: jimengBaseUrl, jimeng_model: jimengModel };

      if (apiKey.trim()) data.deepseek_api_key = apiKey.trim();

      if (jimengApiKey.trim()) data.jimeng_api_key = jimengApiKey.trim();

      const s = await api.updateSettings(data);

      setConfigured(s.deepseek_configured);

      setMasked(s.deepseek_api_key_masked);

      setJimengConfigured(s.jimeng_configured);

      setJimengMasked(s.jimeng_api_key_masked);

      setApiKey("");

      setJimengApiKey("");

      setMsg("设置已保存");

      await refreshUser();

    } catch (e) {

      setErr(String(e));

    } finally {

      setSaving(false);

    }

  };



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


