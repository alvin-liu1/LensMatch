"""Small native interface; computation runs off the UI thread."""
from dataclasses import asdict, replace
import os
import time
import traceback
import subprocess
import sys
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .runtime import ROOT, read_preferences, save_preferences, record_error
from .service import execute
from .models import Config


def launch(config, input_path=None, a=None, b=None, output=None):
    base_config = config
    preferences = read_preferences()
    try:
        config = Config(**preferences.get("config", asdict(config)))
    except (TypeError, ValueError):
        config = base_config
    root = tk.Tk()
    root.title("摄像头模组配对")
    width = min(1040, root.winfo_screenwidth() - 80)
    height = min(740, root.winfo_screenheight() - 100)
    root.geometry(f"{width}x{height}")
    root.minsize(min(980, width), min(700, height))
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    mode = tk.StringVar(value=config.mode)
    ttk.Label(panel, text="配对模式").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(panel, text="两边都无 IMU", variable=mode, value="no-imu").grid(row=0, column=1, sticky="w")
    ttk.Radiobutton(panel, text="A带 IMU，B无 IMU", variable=mode, value="mixed-imu").grid(row=1, column=1, sticky="w")
    split = tk.BooleanVar(value=bool(a) or preferences.get("split", False) is True)
    ttk.Checkbutton(panel, text="使用分别存放的 A/B 输入（仅允许跨组配对）", variable=split).grid(row=2, column=1, sticky="w", pady=8)
    variables = {}
    for row, (key, label, value) in enumerate([
        ("input", "统一输入", input_path or preferences.get("input", str(ROOT / "input"))),
        ("a", "A 输入", a or preferences.get("a", "")), ("b", "B 输入", b or preferences.get("b", "")),
        ("output", "结果目录", output or preferences.get("output", str(ROOT / "output")))], 3):
        variable = variables[key] = tk.StringVar(value=value)
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(panel, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8)
        def select_directory(var=variable):
            path = filedialog.askdirectory(parent=root)
            if path:
                var.set(path)
        ttk.Button(panel, text="选目录", command=select_directory).grid(row=row, column=2, padx=3)
        if key != "output":
            def select_file(var=variable):
                path = filedialog.askopenfilename(parent=root, filetypes=[("数据文件", "*.xlsx *.xls *.xlsm *.csv *.tsv *.txt")])
                if path:
                    var.set(path)
            ttk.Button(panel, text="选文件", command=select_file).grid(row=row, column=3)
    score = tk.BooleanVar(value=config.use_score)
    score_panel = ttk.Frame(panel)
    score_panel.grid(row=7, column=1, columnspan=3, sticky="ew", pady=8)
    ttk.Checkbutton(score_panel, text="启用 Score 差值筛选", variable=score).pack(side="left")
    sources = {"读取真实 Score 列": "column", "MTF 均值（Block3_H、Block4_H）": "block-average"}
    source = tk.StringVar(value=next(label for label, value in sources.items() if value == config.score_source))
    source_box = ttk.Combobox(score_panel, textvariable=source, values=list(sources), state="readonly", width=34)
    source_box.pack(side="left", padx=8)
    def score_state(*_):
        source_box.configure(state="readonly" if score.get() else "disabled")
    score.trace_add("write", score_state)
    score_state()
    limits = tk.StringVar()
    def refresh_limits():
        limits.set(f"阈值：ΔAEC ≤ {config.aec_limit}，ΔR/G ≤ {config.rg_limit}，ΔB/G ≤ {config.bg_limit}，ΔScore ≤ {config.score_limit}")
    refresh_limits()
    ttk.Label(panel, textvariable=limits).grid(row=8, column=0, columnspan=3, sticky="w")

    def edit_config():
        dialog = tk.Toplevel(root)
        dialog.title("阈值与成本权重")
        dialog.transient(root)
        dialog.grab_set()
        entries = {}
        ttk.Label(dialog, text="硬阈值决定是否合格；权重只影响合格配对的质量排序。", padding=12).grid(row=0, column=0, columnspan=3)
        for column, label in enumerate(["指标", "差值上限", "成本权重"]):
            ttk.Label(dialog, text=label).grid(row=1, column=column, padx=12)
        for row, key in enumerate(["aec", "rg", "bg", "score"], 2):
            ttk.Label(dialog, text=key.upper()).grid(row=row, column=0, padx=12, pady=8)
            for column, value in [(1, getattr(config, key + "_limit")), (2, config.weights[key])]:
                variable = tk.StringVar(value=str(value))
                entries[key, column] = variable
                ttk.Entry(dialog, textvariable=variable, width=16).grid(row=row, column=column, padx=12)
        def apply():
            nonlocal config
            try:
                config = replace(config, use_score=score.get(),
                                 **{k + "_limit": float(entries[k, 1].get()) for k in ["aec", "rg", "bg", "score"]},
                                 weights={k: float(entries[k, 2].get()) for k in ["aec", "rg", "bg", "score"]})
            except (ValueError, TypeError) as exc:
                messagebox.showerror("配置无效", str(exc), parent=dialog)
                return
            refresh_limits()
            dialog.destroy()
        ttk.Button(dialog, text="应用", command=apply).grid(row=6, column=1, pady=16)
        def restore():
            for key in ["aec", "rg", "bg", "score"]:
                entries[key, 1].set(str(getattr(base_config, key + "_limit")))
                entries[key, 2].set(str(base_config.weights[key]))
        ttk.Button(dialog, text="恢复 config.json 数值", command=restore).grid(row=6, column=2, pady=16)
    settings_button = ttk.Button(panel, text="阈值与权重…", command=edit_config)
    settings_button.grid(row=8, column=3, pady=8)
    status = tk.StringVar(value="混配：用 A/B 输入指定真实硬件类型，或在统一输入里提供 IMU_Flag。")
    ttk.Label(panel, textvariable=status, wraplength=740).grid(row=10, column=0, columnspan=4, sticky="w", pady=10)
    results = queue.Queue()
    last_result = [None]
    progress = ttk.Progressbar(panel, mode="indeterminate")
    progress.grid(row=11, column=0, columnspan=4, sticky="ew", pady=8)

    log = tk.Text(panel, height=7, wrap="word", state="disabled")
    log.grid(row=12, column=0, columnspan=4, sticky="nsew", pady=8)
    panel.rowconfigure(12, weight=1)
    started = [None]
    current_stage = ["正在读取与校验数据"]
    def append_log(message):
        log.configure(state="normal")
        log.insert("end", time.strftime("%H:%M:%S ") + message + "\n")
        log.see("end")
        log.configure(state="disabled")
    def remember(selected=None):
        selected = selected or replace(config, mode=mode.get(), use_score=score.get(), score_source=sources[source.get()])
        save_preferences({**{key: variable.get() for key, variable in variables.items()},
                          "split": split.get(), "config": asdict(selected)})

    def start():
        if not variables["output"].get().strip():
            messagebox.showerror("输入不完整", "请选择结果保存目录", parent=root)
            return
        if not split.get() and not variables["input"].get().strip():
            messagebox.showerror("输入不完整", "请选择统一输入文件或目录", parent=root)
            return
        try:
            selected = replace(config, mode=mode.get(), use_score=score.get(), score_source=sources[source.get()])
        except (TypeError, ValueError) as exc:
            messagebox.showerror("配置无效", str(exc), parent=root)
            return
        if split.get():
            if not variables["a"].get() or not variables["b"].get():
                messagebox.showerror("输入不完整", "请指定 A 和 B 输入", parent=root)
                return
            args = (None, variables["a"].get(), variables["b"].get())
        else:
            args = (variables["input"].get(), None, None)
        output_dir = variables["output"].get()
        start_button.configure(state="disabled")
        open_button.configure(state="disabled")
        settings_button.configure(state="disabled")
        started[0] = time.monotonic()
        try:
            remember(selected)
        except OSError as exc:
            append_log(f"无法保存偏好：{exc}")
        progress.start()
        status.set("正在读取、校验和匹配…")
        def worker():
            try:
                results.put(("done", execute(*args, output_dir, selected, progress=lambda stage, message: results.put(("progress", (stage, message))))))
            except Exception as exc:
                detail = str(exc)
                if getattr(exc, "invalid", None):
                    detail += "\n" + "\n".join(f"{row.get('SN') or '(缺失SN)'}: {row['来源']} / {row['原因']}" for row in exc.invalid[:10])
                log_path = record_error(traceback.format_exc() + "\n" + str(getattr(exc, "invalid", ())))
                results.put(("error", (detail, log_path)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            ok, result = results.get_nowait()
        except queue.Empty:
            if started[0] is not None and str(start_button.cget("state")) == "disabled":
                status.set(f"{current_stage[0]} · 已耗时 {time.monotonic() - started[0]:.1f} 秒")
            root.after(100, poll)
            return
        if ok == "progress":
            stage, message = result
            current_stage[0] = message
            elapsed = time.monotonic() - started[0]
            status.set(f"{message} · 已耗时 {elapsed:.1f} 秒")
            append_log(message)
            root.after(10, poll)
            return
        start_button.configure(state="normal")
        settings_button.configure(state="normal")
        progress.stop()
        elapsed = time.monotonic() - started[0]
        if ok == "done":
            last_result[0] = result.target
            summary = result.summary
            counts = "，".join(f"{key}：{summary[key]}" for key in ["有效模组", "配对数", "未配对数", "无效模组"])
            outcome = "匹配完成" if summary["有效模组"] else "没有有效模组，已导出异常清单"
            status.set(f"{outcome}，耗时 {elapsed:.1f} 秒。{counts}\n结果：{result.target}")
            append_log(f"完成：{counts}；耗时 {elapsed:.1f} 秒")
            open_button.configure(state="normal")
        else:
            detail, log_path = result
            status.set("匹配失败，请查看错误详情并核对输入。")
            append_log(detail)
            if log_path:
                detail += f"\n\n诊断日志：{log_path}"
            messagebox.showerror("匹配失败", detail, parent=root)
        root.after(100, poll)

    start_button = ttk.Button(panel, text="开始匹配", command=start)
    start_button.grid(row=9, column=1, sticky="w", pady=12)
    def open_result():
        try:
            if sys.platform == "win32":
                os.startfile(str(last_result[0].parent))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(last_result[0].parent)])
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc), parent=root)
    open_button = ttk.Button(panel, text="打开结果目录", state="disabled", command=open_result)
    open_button.grid(row=9, column=2, columnspan=2)
    def close():
        if str(start_button.cget("state")) == "disabled":
            messagebox.showinfo("正在匹配", "请等待当前结果保存完成后再关闭。", parent=root)
            return
        try:
            remember()
        except (OSError, TypeError, ValueError):
            pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, poll)
    root.mainloop()
