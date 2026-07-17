import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Shield, X } from "lucide-react";
import { api, type LicenseStatus } from "../api";
import BrandMark from "./BrandMark";

const EULA_TEXT =
  "NovFlow 桌面版仅供个人学习与研究使用。激活码与本机绑定，禁止转售或共享。AI 生成内容需用户自行审核与合规使用。";

export default function LicenseNotice() {
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [deviceCode, setDeviceCode] = useState("");
  const [licenseCode, setLicenseCode] = useState("");
  const [eulaChecked, setEulaChecked] = useState(false);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  const refresh = async () => {
    try {
      const st = await api.getLicenseStatus();
      setStatus(st);
      if (st.desktop_mode && !st.activated) {
        try {
          const dev = await api.getLicenseDevice();
          setDeviceCode(dev.device_code);
        } catch {
          /* ignore */
        }
      } else {
        setShowModal(false);
      }
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const st = await api.getLicenseStatus();
        setStatus(st);
        if (!st.desktop_mode || st.activated) {
          return;
        }
        try {
          const dev = await api.getLicenseDevice();
          setDeviceCode(dev.device_code);
        } catch {
          /* ignore */
        }
        const expired = Boolean(st.error?.includes("过期"));
        const dismissedKey = expired
          ? "novflow_license_expired_modal_dismissed"
          : "novflow_license_modal_dismissed";
        if (!sessionStorage.getItem(dismissedKey)) {
          setShowModal(true);
        }
      } catch {
        setStatus(null);
      }
    })();
  }, []);

  const needsActivation = Boolean(status?.desktop_mode && !status.activated);
  const isExpired = Boolean(status?.error?.includes("过期"));

  const activate = async () => {
    const code = licenseCode.trim();
    if (!code) {
      setError("请先粘贴激活码");
      return;
    }
    if (!eulaChecked) {
      setError("请先阅读并同意软件许可协议");
      return;
    }
    setActivating(true);
    setError("");
    try {
      await api.activateLicense(code);
      setLicenseCode("");
      await refresh();
      sessionStorage.setItem("novflow_license_modal_dismissed", "1");
    } catch (e) {
      setError(String(e));
    } finally {
      setActivating(false);
    }
  };

  const dismissModal = () => {
    const dismissedKey = isExpired
      ? "novflow_license_expired_modal_dismissed"
      : "novflow_license_modal_dismissed";
    sessionStorage.setItem(dismissedKey, "1");
    setShowModal(false);
  };

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* ignore */
    }
  };

  if (!needsActivation) {
    return null;
  }

  return (
    <>
      {!bannerDismissed && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-2">
              <Shield className="h-4 w-4 shrink-0" />
              {isExpired
                ? `授权已过期${status?.valid_until ? `（${status.valid_until}）` : ""}，请前往设置重新激活`
                : "请前往设置完成授权激活"}
            </span>
            <div className="flex items-center gap-2">
              <Link to="/settings" className="btn-primary py-1 px-3 text-xs">
                前往设置
              </Link>
              <button
                type="button"
                className="rounded p-1 text-amber-700 hover:bg-amber-100"
                aria-label="关闭提示"
                onClick={() => setBannerDismissed(true)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 p-4">
          <div className="card max-h-[90vh] w-full max-w-lg overflow-y-auto p-6">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <BrandMark className="mt-0.5 h-10 w-10 shrink-0 rounded-lg shadow-sm ring-1 ring-slate-200/80" />
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">
                    {isExpired ? "授权已过期" : "产品授权激活"}
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">
                    {isExpired
                      ? `您的 NovFlow 桌面版授权已过期${status?.valid_until ? `（有效期至 ${status.valid_until}）` : ""}。请重新激活以继续使用 AI 功能；定稿、保存等非 AI 功能不受影响。`
                      : "欢迎使用 NovFlow 桌面版。请先完成授权激活以使用 AI 功能；您也可稍后在设置页激活。"}
                  </p>
                </div>
              </div>
              <button type="button" className="rounded p-1 text-slate-400 hover:bg-slate-100" onClick={dismissModal}>
                <X className="h-5 w-5" />
              </button>
            </div>

            {status?.hw_id && (
              <div className="mt-4 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-600">设备指纹</span>
                  <code className="rounded bg-white px-2 py-1 font-mono">{status.short_hw_id || status.hw_id}</code>
                  <button type="button" className="btn-secondary py-0.5 px-2 text-xs" onClick={() => copyText(status.hw_id || "")}>
                    复制 HW_ID
                  </button>
                </div>
                {deviceCode && (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-600">设备码</span>
                    <code className="rounded bg-white px-2 py-1 font-mono">{deviceCode}</code>
                    <button type="button" className="btn-secondary py-0.5 px-2 text-xs" onClick={() => copyText(deviceCode)}>
                      复制设备码
                    </button>
                  </div>
                )}
              </div>
            )}

            <textarea
              className="input mt-4 min-h-[80px] font-mono text-sm"
              placeholder="粘贴激活码（格式：v1.xxxxx.yyyyy）"
              value={licenseCode}
              onChange={(e) => setLicenseCode(e.target.value)}
            />

            <label className="mt-3 flex items-start gap-2 text-sm text-slate-600">
              <input type="checkbox" className="mt-1" checked={eulaChecked} onChange={(e) => setEulaChecked(e.target.checked)} />
              <span>我已阅读并同意 NovFlow 软件许可协议：{EULA_TEXT}</span>
            </label>

            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" className="btn-primary text-sm" onClick={activate} disabled={activating}>
                {activating ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                立即激活
              </button>
              <Link to="/settings" className="btn-secondary text-sm" onClick={dismissModal}>
                前往设置
              </Link>
              <button type="button" className="btn-secondary text-sm" onClick={dismissModal}>
                稍后再说
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
