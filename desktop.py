"""Windowed distribution entry point, including visible startup errors."""
import tkinter as tk
import sys
import json
from pathlib import Path
from tkinter import messagebox
from matching.runtime import ROOT, load_config, record_error
from matching.service import execute
from matching.models import Config
from matching.gui import launch


if __name__ == "__main__":
    try:
        config = Config(**load_config(ROOT / "config.json"))
        if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
            target = execute(ROOT / "examples" / "noimu", output=Path(sys.argv[2]), config=config).target
            summary = json.loads((target.parent / "summary.json").read_text(encoding="utf-8"))
            if summary["配对数"] != 5 or summary["无效模组"] != 0:
                raise ValueError("打包程序合成数据回归失败")
        else:
            launch(config)
    except Exception as exc:
        if "--smoke-test" in sys.argv:
            raise SystemExit(1) from exc
        import traceback
        log_path = record_error(traceback.format_exc())
        error_root = tk.Tk()
        error_root.withdraw()
        messagebox.showerror("LensMatch 启动失败", str(exc) + (f"\n诊断日志：{log_path}" if log_path else ""), parent=error_root)
        error_root.destroy()
        raise SystemExit(1)
