"""Tkinter activation dialog (desktop / DLC CLI)."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if (_root / "shared").is_dir() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk

from shared.license.license_common import read_license
from shared.license.license_service import LicenseService


def _field_row(
    parent: ttk.Frame,
    label: str,
    builder: Callable[[ttk.Frame], tk.Widget],
    pady: int = 6,
    label_width: int = 14,
) -> tk.Widget:
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=pady)
    ttk.Label(row, text=label, width=label_width, anchor="w").pack(side="left", padx=(0, 8))
    widget = builder(row)
    widget.pack(side="left", fill="x", expand=True)
    return widget


class LicenseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk | tk.Toplevel, license_svc: LicenseService, on_changed=None):
        super().__init__(parent)
        self.license_svc = license_svc
        self.on_changed = on_changed
        self.title("授权激活")
        self.geometry("640x540")
        self.minsize(560, 480)
        self.transient(parent)
        self.grab_set()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

        info = license_svc.device_info()
        status = license_svc.status()

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=str(info.get("product_name", "")), font=("Microsoft YaHei UI", 11, "bold")).pack(
            anchor="w", pady=(0, 8)
        )

        status_frame = ttk.LabelFrame(outer, text="当前状态", padding=10)
        status_frame.pack(fill="x", pady=(0, 10))
        if status.get("activated"):
            status_text = "已激活 — 完整功能已解锁"
            color = "#008800"
        else:
            err = status.get("error", "未激活")
            status_text = f"未激活 — {err}"
            color = "#cc6600"
        ttk.Label(status_frame, text=status_text, foreground=color).pack(anchor="w")

        dev = ttk.LabelFrame(outer, text="本机设备信息（发给管理员生成激活码）", padding=10)
        dev.pack(fill="x", pady=(0, 10))

        hw_var = tk.StringVar(value=str(info["hw_id"]))
        dc_var = tk.StringVar(value=str(info["device_code"]))
        _field_row(
            dev,
            "设备指纹 HW_ID",
            lambda row: ttk.Entry(row, textvariable=hw_var, state="readonly"),
            label_width=16,
        )
        _field_row(
            dev,
            "激活设备码",
            lambda row: ttk.Entry(row, textvariable=dc_var, state="readonly"),
            label_width=16,
        )

        btn_row = ttk.Frame(dev)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="复制 HW_ID", command=lambda: self._copy(hw_var.get())).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="复制设备码", command=lambda: self._copy(dc_var.get())).pack(side="left")

        act = ttk.LabelFrame(outer, text="输入激活码", padding=10)
        act.pack(fill="both", expand=True)

        self.code_text = scrolledtext.ScrolledText(act, wrap="word", height=5, font=("Consolas", 10))
        self.code_text.pack(fill="both", expand=True, pady=(0, 8))
        if status.get("activated"):
            stored = read_license(license_svc.profile) or {}
            code = str(stored.get("license_code", ""))
            if code:
                self.code_text.insert("1.0", code)
                self.code_text.config(state="disabled")

        action_row = ttk.Frame(act)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="激活", command=self._activate, width=12).pack(side="left", padx=(0, 8))
        ttk.Button(action_row, text="卸载授权", command=self._deactivate, width=12).pack(side="left", padx=(0, 8))
        ttk.Button(action_row, text="关闭", command=self._close, width=12).pack(side="right")

        ttk.Label(
            outer,
            text="激活码离线验证，无需联网。格式：v1.xxxxx.yyyyy",
            foreground="#666",
        ).pack(anchor="w", pady=(8, 0))

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("复制", "已复制到剪贴板", parent=self)

    def _activate(self) -> None:
        code = self.code_text.get("1.0", "end-1c").strip()
        if not code:
            messagebox.showwarning("激活", "请先粘贴激活码", parent=self)
            return
        result = self.license_svc.activate(code)
        if result.get("ok"):
            messagebox.showinfo("激活", "激活成功，已解锁完整功能。", parent=self)
            if self.on_changed:
                self.on_changed()
            self.destroy()
        else:
            messagebox.showerror("激活失败", str(result.get("error", "未知错误")), parent=self)

    def _deactivate(self) -> None:
        if not messagebox.askyesno("卸载授权", "确定卸载本机授权？", parent=self):
            return
        self.license_svc.deactivate()
        messagebox.showinfo("卸载", "授权已卸载。", parent=self)
        if self.on_changed:
            self.on_changed()
        self.destroy()

    def _close(self) -> None:
        self.destroy()


def show_license_dialog(license_svc: LicenseService, *, modal: bool = True) -> None:
    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    dlg = LicenseDialog(root, license_svc)
    dlg.update_idletasks()
    dlg.deiconify()
    dlg.lift()
    dlg.attributes("-topmost", True)
    dlg.focus_force()
    if modal:
        root.wait_window(dlg)
    else:
        dlg.protocol("WM_DELETE_WINDOW", lambda: (dlg.destroy(), root.destroy()))
        root.mainloop()
