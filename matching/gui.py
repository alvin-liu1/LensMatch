"""Small native interface; computation runs off the UI thread."""
from dataclasses import replace
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .cli import ROOT, run


def launch(config, input_path=None, a=None, b=None, output=None):
    root = tk.Tk()
    root.title("摄像头模组配对")
    root.geometry("900x560")
    root.minsize(900, 560)
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(1, weight=1)
    mode = tk.StringVar(value=config.mode)
    ttk.Label(panel, text="配对模式").grid(row=0, column=0, sticky="w")
    ttk.Radiobutton(panel, text="两边都无 IMU", variable=mode, value="no-imu").grid(row=0, column=1, sticky="w")
    ttk.Radiobutton(panel, text="A带 IMU，B无 IMU", variable=mode, value="mixed-imu").grid(row=1, column=1, sticky="w")
    split = tk.BooleanVar(value=bool(a))
    ttk.Checkbutton(panel, text="使用分别存放的 A/B 输入（仅允许跨组配对）", variable=split).grid(row=2, column=1, sticky="w", pady=8)
    variables = {}
    for row, (key, label, value) in enumerate([
        ("input", "统一输入", input_path or str(ROOT / "input")),
        ("a", "A 输入", a or ""), ("b", "B 输入", b or ""),
        ("output", "结果目录", output or str(ROOT / "output"))], 3):
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
    score_panel = ttk.Frame(panel)
    score_panel.grid(row=7, column=1, columnspan=3, sticky="ew", pady=8)
    ttk.Label(score_panel, text=f"Score 已启用（差值阈值: {config.score_limit}）").pack(side="left")
    sources = {"读取真实 Score 列": "column", "MTF 均值（Block3_H、Block4_H）": "block-average"}
    source = tk.StringVar(value=next(label for label, value in sources.items() if value == config.score_source))
    source_box = ttk.Combobox(score_panel, textvariable=source, values=list(sources), state="readonly", width=34)
    source_box.pack(side="left", padx=8)
    ttk.Label(panel, text=f"阈值：ΔAEC ≤ {config.aec_limit}，ΔR/G ≤ {config.rg_limit}，ΔB/G ≤ {config.bg_limit}；可在 config.json 调整").grid(row=8, column=0, columnspan=4, sticky="w")
    status = tk.StringVar(value="混配：用 A/B 输入指定真实硬件类型，或在统一输入里提供 IMU_Flag。")
    ttk.Label(panel, textvariable=status, wraplength=740).grid(row=10, column=0, columnspan=4, sticky="w", pady=10)
    results = queue.Queue()
    last_result = [None]

    def start():
        selected = replace(config, mode=mode.get(), use_score=True, score_source=sources[source.get()])
        if split.get():
            if not variables["a"].get() or not variables["b"].get():
                messagebox.showerror("输入不完整", "请指定 A 和 B 输入", parent=root)
                return
            args = (None, variables["a"].get(), variables["b"].get())
        else:
            args = (variables["input"].get(), None, None)
        output_dir = variables["output"].get()
        start_button.configure(state="disabled")
        status.set("正在读取、校验和匹配…")
        def worker():
            try:
                results.put((True, run(*args, output_dir, selected)))
            except Exception as exc:
                results.put((False, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            ok, result = results.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        start_button.configure(state="normal")
        if ok:
            last_result[0] = result
            status.set(f"匹配完成。结果：{result}；Pairs为配对清单，Invalid为无效数据。")
            open_button.configure(state="normal")
        else:
            status.set("匹配失败，请核对输入。")
            messagebox.showerror("匹配失败", result, parent=root)
        root.after(100, poll)

    start_button = ttk.Button(panel, text="开始匹配", command=start)
    start_button.grid(row=9, column=1, sticky="w", pady=12)
    def open_result():
        try:
            os.startfile(str(last_result[0].parent))
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc), parent=root)
    open_button = ttk.Button(panel, text="打开结果目录", state="disabled", command=open_result)
    open_button.grid(row=9, column=2, columnspan=2)
    def close():
        if str(start_button.cget("state")) == "disabled":
            messagebox.showinfo("正在匹配", "请等待当前结果保存完成后再关闭。", parent=root)
            return
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(100, poll)
    root.mainloop()
