import { Link } from "react-router-dom";
import { X } from "lucide-react";

type Props = {
  open: boolean;
  title: string;
  message: string;
  onClose: () => void;
  settingsLink?: boolean;
  confirmLabel?: string;
};

export default function AppAlertModal({
  open,
  title,
  message,
  onClose,
  settingsLink = false,
  confirmLabel = "知道了",
}: Props) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 p-4">
      <div className="card w-full max-w-md p-6 shadow-xl" role="alertdialog" aria-modal="true" aria-labelledby="app-alert-title">
        <div className="flex items-start justify-between gap-3">
          <h2 id="app-alert-title" className="text-lg font-semibold text-slate-900">
            {title}
          </h2>
          <button type="button" className="rounded p-1 text-slate-400 hover:bg-slate-100" onClick={onClose} aria-label="关闭">
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{message}</p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          {settingsLink && (
            <Link to="/settings" className="btn-primary text-sm" onClick={onClose}>
              前往设置
            </Link>
          )}
          <button type="button" className="btn-secondary text-sm" onClick={onClose}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
