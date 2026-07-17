"""NovFlow Image Engine GUI console + system tray (background plugin)."""

from __future__ import annotations

import os
import sys
import threading
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Paths must be ready before other image_engine imports when launched as -m
from image_engine import settings_store
from image_engine.license_gate import license_service
from image_engine.models_mgr import (
    find_lite_checkpoint,
    import_folder,
    import_weight,
    list_models,
    models_root,
    set_active_lite_model,
    set_models_dir,
)
from image_engine.model_download import cancel_download, download_model, is_downloading, load_catalog


APP_TITLE = "NovFlow 本地生图引擎"
_server: Any = None
_server_thread: threading.Thread | None = None
_tray_icon: Any = None
_root: Any = None
_exiting = False


def _install_root() -> Path:
    install = os.environ.get("NOVFLOW_INSTALL_DIR", "").strip()
    if install:
        return Path(install)
    return Path(__file__).resolve().parents[1]


def _eula_text() -> str:
    candidates = [
        _install_root() / "LICENSE-DLC.txt",
        _install_root().parent / "installer" / "LICENSE-DLC.txt",
        Path(__file__).resolve().parents[2] / "installer" / "LICENSE-DLC.txt",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass
    return (
        "NovFlow 本地生图引擎最终用户许可协议（EULA）\n\n"
        "本软件为 NovFlow 的独立可选组件，与主程序分开发布、分别授权。\n"
        "本地生图内容由用户本人负责；开发者不对生成内容承担法律责任。\n"
        "请遵守所在地法律法规。\n"
    )


def _tray_image():
    """Load brand icon or generate a simple tray image."""
    from PIL import Image, ImageDraw

    candidates = [
        _install_root() / "assets" / "tray_icon.png",
        _install_root() / "assets" / "icon.png",
        Path(__file__).resolve().parent / "assets" / "tray_icon.png",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return Image.open(path).convert("RGBA")
            except OSError:
                pass

    # Brand-like indigo square with "N"
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=12, fill=(67, 56, 202, 255))
    draw.text((20, 14), "N", fill=(255, 255, 255, 255))
    return img


def _base_url() -> str:
    cfg = settings_store.load_settings()
    host = str(cfg.get("host") or settings_store.DEFAULT_HOST)
    port = int(cfg.get("port") or settings_store.DEFAULT_PORT)
    return f"http://{host}:{port}"


def _http_json(method: str, path: str, timeout: float = 5.0) -> tuple[int, Any]:
    url = _base_url() + path
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        code = exc.code
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason or exc)) from exc
    text = body.decode("utf-8", errors="replace")
    if not text:
        return code, None
    try:
        import json

        return code, json.loads(text)
    except json.JSONDecodeError:
        return code, text


def _http_bytes(method: str, path: str, timeout: float = 30.0) -> tuple[int, bytes]:
    url = _base_url() + path
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason or exc)) from exc


def start_engine_server() -> None:
    global _server, _server_thread
    if _server_thread and _server_thread.is_alive():
        return

    settings_store.ensure_stdio()
    cfg = settings_store.apply_to_environ()
    host = str(cfg.get("host") or settings_store.DEFAULT_HOST)
    port = int(cfg.get("port") or settings_store.DEFAULT_PORT)

    import uvicorn

    from image_engine.app import app

    # use_colors=False: safe when stdout is a log file (pythonw / no TTY)
    config = uvicorn.Config(
        app, host=host, port=port, log_level="info", access_log=False, use_colors=False
    )
    server = uvicorn.Server(config)
    _server = server

    def _run() -> None:
        try:
            server.run()
        except Exception:
            traceback.print_exc()

    _server_thread = threading.Thread(target=_run, name="image-engine-uvicorn", daemon=True)
    _server_thread.start()

    # Wait briefly for bind
    import time

    for _ in range(50):
        if getattr(server, "started", False):
            break
        time.sleep(0.05)


def stop_engine_server() -> None:
    global _server
    server = _server
    if server is not None:
        server.should_exit = True
        _server = None


def _show_window() -> None:
    if _root is None:
        return
    try:
        _root.deiconify()
        _root.lift()
        _root.focus_force()
        _root.attributes("-topmost", True)
        _root.after(200, lambda: _root.attributes("-topmost", False))
    except Exception:
        pass


def _hide_window() -> None:
    if _root is None:
        return
    try:
        _root.withdraw()
    except Exception:
        pass


def _request_exit() -> None:
    global _exiting
    if _exiting:
        return
    _exiting = True
    stop_engine_server()
    icon = _tray_icon
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
    if _root is not None:
        try:
            _root.after(0, _root.destroy)
        except Exception:
            pass


def _start_tray() -> None:
    global _tray_icon
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError:
        return

    def on_open(icon, item) -> None:  # noqa: ARG001
        if _root is not None:
            _root.after(0, _show_window)

    def on_exit(icon, item) -> None:  # noqa: ARG001
        if _root is not None:
            _root.after(0, _request_exit)
        else:
            _request_exit()

    menu = pystray.Menu(
        Item("打开控制台", on_open, default=True),
        Item("退出程序", on_exit),
    )
    icon = pystray.Icon("novflow_image_engine", _tray_image(), APP_TITLE, menu)
    _tray_icon = icon

    def _run_icon() -> None:
        icon.run()

    threading.Thread(target=_run_icon, name="image-engine-tray", daemon=True).start()


def _on_close_window() -> None:
    """Closing the window hides to tray; engine keeps running."""
    _hide_window()
    icon = _tray_icon
    if icon is not None:
        try:
            icon.notify("引擎继续在后台运行。右键托盘图标可退出。", APP_TITLE)
        except Exception:
            pass


class EngineConsole:
    def __init__(self, root) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext

        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x640")
        self.root.minsize(640, 480)

        self._status_var = tk.StringVar(value="正在启动…")
        self._health_var = tk.StringVar(value="—")
        self._tier_var = tk.StringVar(value="—")
        self._port_var = tk.StringVar(value=str(settings_store.load_settings().get("port", 17860)))
        self._models_path_var = tk.StringVar(value=str(models_root()))
        self._download_status_var = tk.StringVar(value="")
        self._download_pct_var = tk.DoubleVar(value=0.0)
        self._license_status_var = tk.StringVar(value="—")
        self._eula_accepted = tk.BooleanVar(value=False)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", _on_close_window)
        self.root.after(400, self.refresh_status)
        self.root.after(2000, self._poll_status)
        self.root.after(800, self._check_models_migration)
        self.root.after(1200, self._maybe_first_run_lite_prompt)

    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk

        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self._status_var, foreground="#444").pack(side="right")

        nb = ttk.Notebook(self.root, padding=8)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tab_status = ttk.Frame(nb, padding=10)
        self.tab_license = ttk.Frame(nb, padding=10)
        self.tab_models = ttk.Frame(nb, padding=10)
        self.tab_settings = ttk.Frame(nb, padding=10)
        nb.add(self.tab_status, text="状态")
        nb.add(self.tab_license, text="授权")
        nb.add(self.tab_models, text="模型")
        nb.add(self.tab_settings, text="设置")

        self._build_status_tab()
        self._build_license_tab()
        self._build_models_tab()
        self._build_settings_tab()

        footer = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="关闭窗口将隐藏到系统托盘，引擎继续运行。退出请使用托盘菜单「退出程序」。",
            foreground="#666",
        ).pack(anchor="w")

    def _build_status_tab(self) -> None:
        ttk = self.ttk
        frame = self.tab_status

        info = ttk.LabelFrame(frame, text="引擎状态", padding=12)
        info.pack(fill="x")

        rows = [
            ("运行状态", self._status_var),
            ("健康检查", self._health_var),
            ("性能档位", self._tier_var),
            ("监听地址", self.tk.StringVar(value=_base_url() + "/v1")),
        ]
        # keep address var for refresh
        self._addr_var = rows[3][1]

        for i, (label, var) in enumerate(rows):
            ttk.Label(info, text=label + "：", width=12, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(info, textvariable=var).grid(row=i, column=1, sticky="w", pady=3)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="刷新状态", command=self.refresh_status, width=14).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="测试连通性", command=self.test_connectivity, width=14).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="隐藏到托盘", command=_on_close_window, width=14).pack(side="left")

        tip = ttk.LabelFrame(frame, text="说明", padding=10)
        tip.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(
            tip,
            text=(
                "本引擎默认仅监听本机 127.0.0.1，供 NovFlow 主程序调用。\n"
                "当前为 stub / 集成测试版本时，连通性测试会返回占位 PNG。\n"
                "请在「授权」页完成激活后，主程序方可调用生图接口。"
            ),
            justify="left",
        ).pack(anchor="w")

    def _build_license_tab(self) -> None:
        tk = self.tk
        ttk = self.ttk
        scrolledtext = self.scrolledtext
        frame = self.tab_license
        svc = license_service()
        info = svc.device_info()

        status_box = ttk.LabelFrame(frame, text="当前状态", padding=10)
        status_box.pack(fill="x")
        ttk.Label(status_box, textvariable=self._license_status_var).pack(anchor="w")

        dev = ttk.LabelFrame(frame, text="本机设备信息（发给管理员生成激活码）", padding=10)
        dev.pack(fill="x", pady=(8, 0))

        self._hw_var = tk.StringVar(value=str(info.get("hw_id", "")))
        self._dc_var = tk.StringVar(value=str(info.get("device_code", "")))

        for label, var in (("设备指纹 HW_ID", self._hw_var), ("激活设备码", self._dc_var)):
            row = ttk.Frame(dev)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=16, anchor="w").pack(side="left")
            ttk.Entry(row, textvariable=var, state="readonly").pack(side="left", fill="x", expand=True)

        copy_row = ttk.Frame(dev)
        copy_row.pack(fill="x", pady=(6, 0))
        ttk.Button(copy_row, text="复制 HW_ID", command=lambda: self._copy(self._hw_var.get())).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(copy_row, text="复制设备码", command=lambda: self._copy(self._dc_var.get())).pack(side="left")

        act = ttk.LabelFrame(frame, text="输入激活码", padding=10)
        act.pack(fill="x", pady=(8, 0))
        self.code_text = scrolledtext.ScrolledText(act, wrap="word", height=4, font=("Consolas", 10))
        self.code_text.pack(fill="x", pady=(0, 6))

        from shared.license.license_common import read_license

        st = svc.status()
        if st.get("activated"):
            stored = read_license(svc.profile) or {}
            code = str(stored.get("license_code", ""))
            if code:
                self.code_text.insert("1.0", code)

        eula_row = ttk.Frame(act)
        eula_row.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(eula_row, text="我已阅读并同意下方 EULA", variable=self._eula_accepted).pack(anchor="w")

        action_row = ttk.Frame(act)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="激活", command=self._activate, width=12).pack(side="left", padx=(0, 8))
        ttk.Button(action_row, text="卸载授权", command=self._deactivate, width=12).pack(side="left")

        eula_box = ttk.LabelFrame(frame, text="最终用户许可协议（EULA）", padding=8)
        eula_box.pack(fill="both", expand=True, pady=(8, 0))
        eula_view = scrolledtext.ScrolledText(eula_box, wrap="word", height=8, font=("Microsoft YaHei UI", 9))
        eula_view.pack(fill="both", expand=True)
        eula_view.insert("1.0", _eula_text())
        eula_view.config(state="disabled")

        self._refresh_license_status()

    def _build_models_tab(self) -> None:
        ttk = self.ttk
        frame = self.tab_models

        path_box = ttk.LabelFrame(frame, text="模型目录（位于安装目录下）", padding=10)
        path_box.pack(fill="x")
        row = ttk.Frame(path_box)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self._models_path_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text="浏览…", command=self._browse_models_dir, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="打开目录", command=self._open_models_dir, width=10).pack(side="left")
        ttk.Label(
            path_box,
            text=f"默认路径：{settings_store.install_root()}\\models",
            foreground="#666",
        ).pack(anchor="w", pady=(6, 0))

        dl_box = ttk.LabelFrame(frame, text="一键下载（国内镜像）", padding=10)
        dl_box.pack(fill="x", pady=(8, 0))

        hero = ttk.Frame(dl_box)
        hero.pack(fill="x", pady=(0, 6))
        ttk.Button(
            hero,
            text="一键下载 Lite 基础模型",
            command=lambda: self._start_download("sd15-lite"),
            width=24,
        ).pack(side="left", padx=(0, 12))
        lite = next((m for m in load_catalog() if m.id == "sd15-lite"), None)
        if lite:
            ttk.Label(hero, text=f"SD 1.5 · {lite.size_display} · 4GB 显存可用", foreground="#444").pack(
                side="left"
            )

        ttk.Label(dl_box, text="其他档位：", foreground="#666").pack(anchor="w", pady=(4, 2))
        for model in load_catalog():
            if model.id == "sd15-lite":
                continue
            item = ttk.Frame(dl_box)
            item.pack(fill="x", pady=3)
            ttk.Label(
                item,
                text=f"{model.name}  —  {model.size_display}",
                wraplength=520,
            ).pack(side="left", fill="x", expand=True)
            ttk.Button(
                item,
                text=f"下载 {model.tier.upper()}",
                command=lambda mid=model.id: self._start_download(mid),
                width=14,
            ).pack(side="right")

        prog_row = ttk.Frame(dl_box)
        prog_row.pack(fill="x", pady=(8, 0))
        self._download_progress = ttk.Progressbar(prog_row, variable=self._download_pct_var, maximum=100)
        self._download_progress.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(prog_row, text="取消", command=self._cancel_download, width=8).pack(side="right")
        ttk.Label(dl_box, textvariable=self._download_status_var, foreground="#444").pack(anchor="w", pady=(4, 0))

        list_box = ttk.LabelFrame(frame, text="已安装模型 / 权重", padding=10)
        list_box.pack(fill="both", expand=True, pady=(8, 0))

        self.models_list = self.tk.Listbox(list_box, height=8, font=("Consolas", 10))
        scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.models_list.yview)
        self.models_list.config(yscrollcommand=scroll.set)
        self.models_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="刷新列表", command=self.refresh_models, width=12).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="离线导入文件…", command=self._import_file, width=14).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="离线导入文件夹…", command=self._import_folder, width=16).pack(side="left", padx=(0, 8))

        ttk.Label(
            frame,
            text="首次使用建议点击「下载 LITE」获取 SD 1.5 基础模型（约 4GB）。也可从网盘复制 .safetensors 后使用「离线导入」。",
            foreground="#666",
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self.refresh_models()

    def _build_settings_tab(self) -> None:
        ttk = self.ttk
        frame = self.tab_settings

        port_box = ttk.LabelFrame(frame, text="高级 — 监听端口", padding=10)
        port_box.pack(fill="x")
        row = ttk.Frame(port_box)
        row.pack(fill="x")
        ttk.Label(row, text="端口", width=10).pack(side="left")
        ttk.Entry(row, textvariable=self._port_var, width=10).pack(side="left", padx=(0, 8))
        ttk.Button(row, text="保存", command=self._save_port, width=10).pack(side="left")
        ttk.Label(
            port_box,
            text="默认 17860，仅绑定 127.0.0.1。修改端口后需重启引擎（托盘「退出程序」后重新启动）。",
            foreground="#666",
        ).pack(anchor="w", pady=(8, 0))

        log_box = ttk.LabelFrame(frame, text="日志", padding=10)
        log_box.pack(fill="x", pady=(10, 0))
        ttk.Button(log_box, text="打开日志文件夹", command=self._open_log_dir, width=16).pack(anchor="w")
        ttk.Label(log_box, text=str(settings_store.log_dir()), foreground="#666").pack(anchor="w", pady=(6, 0))

        about = ttk.LabelFrame(frame, text="关于", padding=10)
        about.pack(fill="x", pady=(10, 0))
        ttk.Label(
            about,
            text="NovFlow 本地生图引擎控制台\n关闭窗口 = 隐藏到托盘（服务继续）\n托盘右键「退出程序」= 完全停止",
            justify="left",
        ).pack(anchor="w")

    def _copy(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.messagebox.showinfo("复制", "已复制到剪贴板", parent=self.root)

    def _refresh_license_status(self) -> None:
        st = license_service().status()
        if st.get("activated"):
            self._license_status_var.set("已激活 — 完整功能已解锁")
        else:
            err = st.get("error", "未激活")
            self._license_status_var.set(f"未激活 — {err}")

    def _activate(self) -> None:
        if not self._eula_accepted.get():
            self.messagebox.showwarning("授权", "请先勾选同意 EULA", parent=self.root)
            return
        code = self.code_text.get("1.0", "end-1c").strip()
        if not code:
            self.messagebox.showwarning("授权", "请先粘贴激活码", parent=self.root)
            return
        result = license_service().activate(code)
        if result.get("ok"):
            self.messagebox.showinfo("激活", "激活成功，已解锁完整功能。", parent=self.root)
            self._refresh_license_status()
            self.refresh_status()
        else:
            self.messagebox.showerror("激活失败", str(result.get("error", "未知错误")), parent=self.root)

    def _deactivate(self) -> None:
        if not self.messagebox.askyesno("卸载授权", "确定卸载本机授权？", parent=self.root):
            return
        license_service().deactivate()
        self.messagebox.showinfo("卸载", "授权已卸载。", parent=self.root)
        self._refresh_license_status()
        self.refresh_status()

    def refresh_status(self) -> None:
        self._addr_var.set(_base_url() + "/v1")
        try:
            code, data = _http_json("GET", "/v1/health", timeout=3.0)
            if code == 200 and isinstance(data, dict):
                self._status_var.set("运行中")
                self._health_var.set(str(data.get("status", "ok")))
                self._tier_var.set(str(data.get("tier", "—")))
                lic = data.get("license") or {}
                if not lic.get("activated"):
                    self._status_var.set("运行中（未激活）")
            else:
                self._status_var.set(f"异常 (HTTP {code})")
                self._health_var.set(str(data))
        except Exception as exc:
            self._status_var.set("未就绪")
            self._health_var.set(str(exc))
            self._tier_var.set("—")
        self._refresh_license_status()

    def _poll_status(self) -> None:
        if _exiting:
            return
        self.refresh_status()
        self.root.after(5000, self._poll_status)

    def test_connectivity(self) -> None:
        try:
            code, body = _http_bytes("POST", "/v1/generate/test", timeout=15.0)
            if code == 200 and body.startswith(b"\x89PNG"):
                self.messagebox.showinfo(
                    "连通性测试",
                    f"成功：引擎返回测试 PNG（{len(body)} 字节）。\n地址：{_base_url()}/v1",
                    parent=self.root,
                )
                self.refresh_status()
                return
            if code == 403:
                self.messagebox.showwarning(
                    "连通性测试",
                    "引擎在线，但未激活授权（HTTP 403）。请先在「授权」页激活。",
                    parent=self.root,
                )
                return
            self.messagebox.showerror(
                "连通性测试",
                f"失败：HTTP {code}\n{body[:200]!r}",
                parent=self.root,
            )
        except Exception as exc:
            self.messagebox.showerror("连通性测试", f"无法连接引擎：{exc}", parent=self.root)

    def refresh_models(self) -> None:
        self._models_path_var.set(str(models_root()))
        self.models_list.delete(0, "end")
        entries = list_models()
        if not entries:
            self.models_list.insert("end", "（尚未安装模型权重 — 可一键下载 Lite 或离线导入）")
            return
        for entry in entries:
            self.models_list.insert("end", entry.display())
        ckpt = find_lite_checkpoint()
        if ckpt:
            set_active_lite_model(ckpt.name)

    def _format_bytes(self, done: int, total: int) -> str:
        def fmt(n: int) -> str:
            if n >= 1024**3:
                return f"{n / 1024**3:.2f} GB"
            if n >= 1024**2:
                return f"{n / 1024**2:.1f} MB"
            return f"{n / 1024:.0f} KB"

        if total > 0:
            pct = min(100.0, done * 100.0 / total)
            return f"{fmt(done)} / {fmt(total)} ({pct:.1f}%)"
        return fmt(done)

    def _start_download(self, model_id: str) -> None:
        if is_downloading():
            self.messagebox.showwarning("下载", "已有下载任务进行中", parent=self.root)
            return
        from image_engine.model_download import get_catalog_model

        model = get_catalog_model(model_id)
        if model is None:
            return
        if not self.messagebox.askyesno(
            "确认下载",
            f"将下载：{model.name}\n大小：{model.size_display}\n\n保存到：{models_root()}\\{model.tier}\\\n\n是否继续？",
            parent=self.root,
        ):
            return

        self._download_pct_var.set(0.0)
        self._download_status_var.set("准备下载…")

        def on_progress(done: int, total: int, name: str) -> None:
            pct = (done * 100.0 / total) if total > 0 else 0.0
            text = f"正在下载 {name} — {self._format_bytes(done, total)}"

            def _ui() -> None:
                self._download_pct_var.set(pct)
                self._download_status_var.set(text)

            self.root.after(0, _ui)

        def on_done(dest: Path | None, err: str | None) -> None:
            def _ui() -> None:
                if dest:
                    set_active_lite_model(dest.name)
                    self._download_pct_var.set(100.0)
                    self._download_status_var.set(f"下载完成：{dest.name}")
                    self.messagebox.showinfo("下载完成", f"模型已保存至：\n{dest}", parent=self.root)
                    self.refresh_models()
                    self.refresh_status()
                else:
                    self._download_pct_var.set(0.0)
                    self._download_status_var.set(err or "下载失败")
                    if err and err != "下载已取消":
                        self.messagebox.showerror("下载失败", err, parent=self.root)

            self.root.after(0, _ui)

        try:
            download_model(model_id, on_progress=on_progress, on_done=on_done)
        except Exception as exc:
            self.messagebox.showerror("下载", str(exc), parent=self.root)

    def _cancel_download(self) -> None:
        if is_downloading():
            cancel_download()
            self._download_status_var.set("正在取消…")

    def _check_models_migration(self) -> None:
        cfg = settings_store.load_settings()
        if not cfg.get("models_migration_pending"):
            return
        legacy = str(cfg.get("models_migration_legacy") or "")
        if not self.messagebox.askyesno(
            "迁移模型目录",
            f"检测到旧版模型目录中有权重文件：\n{legacy}\n\n"
            f"新版默认目录为：\n{settings_store.default_models_dir()}\n\n"
            "是否将模型复制到新目录？（推荐）",
            parent=self.root,
        ):
            settings_store.dismiss_models_migration()
            return
        try:
            dest = settings_store.apply_models_migration(move=False)
            self.messagebox.showinfo("迁移完成", f"模型已复制到：\n{dest}", parent=self.root)
            self.refresh_models()
        except Exception as exc:
            self.messagebox.showerror("迁移失败", str(exc), parent=self.root)

    def _maybe_first_run_lite_prompt(self) -> None:
        cfg = settings_store.load_settings()
        if cfg.get("first_run_lite_prompt_dismissed"):
            return
        if find_lite_checkpoint() is not None:
            return
        if is_downloading():
            return
        if not self.messagebox.askyesno(
            "首次设置 — Lite 基础模型",
            "尚未检测到 Lite 基础模型（SD 1.5，约 4GB）。\n\n"
            "大多数用户需要此模型才能正常生图。\n\n"
            "是否现在一键下载？（使用国内 ModelScope 镜像）",
            parent=self.root,
        ):
            settings_store.save_settings({"first_run_lite_prompt_dismissed": True})
            return
        self._start_download("sd15-lite")

    def _browse_models_dir(self) -> None:
        path = self.filedialog.askdirectory(title="选择模型目录", initialdir=str(models_root()))
        if not path:
            return
        set_models_dir(Path(path))
        self.refresh_models()

    def _open_models_dir(self) -> None:
        path = models_root()
        path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def _open_log_dir(self) -> None:
        path = settings_store.log_dir()
        path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            self.messagebox.showerror("打开失败", str(exc), parent=self.root)

    def _import_file(self) -> None:
        path = self.filedialog.askopenfilename(
            title="离线导入模型权重",
            filetypes=[
                ("模型权重", "*.safetensors *.ckpt *.pt *.pth *.bin *.onnx"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        try:
            dest = import_weight(Path(path), tier="lite")
            self.messagebox.showinfo("导入成功", f"已复制到：\n{dest}", parent=self.root)
            self.refresh_models()
        except Exception as exc:
            self.messagebox.showerror("导入失败", str(exc), parent=self.root)

    def _import_folder(self) -> None:
        path = self.filedialog.askdirectory(title="离线导入模型文件夹")
        if not path:
            return
        try:
            imported = import_folder(Path(path), tier="lite")
            if not imported:
                self.messagebox.showwarning("导入", "该文件夹中未找到权重文件。", parent=self.root)
                return
            self.messagebox.showinfo("导入成功", f"已导入 {len(imported)} 个文件。", parent=self.root)
            self.refresh_models()
        except Exception as exc:
            self.messagebox.showerror("导入失败", str(exc), parent=self.root)

    def _save_port(self) -> None:
        raw = self._port_var.get().strip()
        if not raw.isdigit() or not (1 <= int(raw) <= 65535):
            self.messagebox.showwarning("设置", "请输入有效端口（1–65535）", parent=self.root)
            return
        settings_store.save_settings({"port": int(raw)})
        self.messagebox.showinfo(
            "设置",
            "端口已保存。请通过托盘「退出程序」后重新启动引擎以使新端口生效。",
            parent=self.root,
        )


def run_console() -> None:
    global _root
    import tkinter as tk

    settings_store.ensure_stdio()
    settings_store.apply_to_environ()

    try:
        start_engine_server()
    except OSError as exc:
        _show_startup_error(f"启动失败：{exc}\n\n若端口已被占用，请先结束旧进程或在设置中更换端口。")
        raise SystemExit(1) from exc
    except Exception as exc:
        _show_startup_error(f"启动失败：{exc}\n\n{traceback.format_exc()}")
        raise SystemExit(1) from exc

    root = tk.Tk()
    _root = root
    try:
        root.iconphoto(True, tk.PhotoImage(data=_photoimage_png_data()))
    except Exception:
        pass

    EngineConsole(root)
    _start_tray()
    root.mainloop()
    stop_engine_server()


def _photoimage_png_data() -> str:
    """Minimal PNG as base64 for window icon (optional)."""
    import base64
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((1, 1, 30, 30), radius=6, fill=(67, 56, 202, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _show_startup_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)
