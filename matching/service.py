"""UI-independent application workflow with structured results and progress."""
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from .models import Config
from .errors import InputError
from .runtime import ROOT
from .data import prepare
from .algorithm import solve
from .report import export


@dataclass(frozen=True)
class RunResult:
    target: Path
    summary: dict


def execute(input_path=None, a=None, b=None, output=None, config=None, progress=None):
    config = config or Config()
    if bool(a) != bool(b):
        raise InputError("incomplete_groups", "A、B输入必须同时指定")
    if input_path and a:
        raise InputError("ambiguous_input", "统一输入和A/B输入只能选择一种")
    sources = ([(a, "A", 1 if config.mode == "mixed-imu" else 0), (b, "B", 0)] if a else
               [(input_path or ROOT / "input", "pool", 0 if config.mode == "no-imu" else None)])
    timings = {}
    started = perf_counter()

    def notify(stage, message):
        if progress:
            progress(stage, message)

    notify("read", "正在读取与校验数据")
    modules, invalid, notes = prepare(sources, config, lambda message: notify("read", message))
    timings["读取校验秒"] = round(perf_counter() - started, 3)
    codes = {code for row in invalid for code in row.get("错误代码", "").split(";")}
    if "imu_conflict" in codes:
        raise InputError("imu_conflict", "业务模式与数据IMU标记冲突，请核对分组或切换模式", invalid)
    if config.mode == "mixed-imu" and not a and codes & {"invalid_imu", "missing_imu"}:
        raise InputError("invalid_imu", "混配输入中存在缺失/非法IMU标记；请指定A带IMU、B无IMU输入，或补齐IMU_Flag", invalid)
    if not modules:
        if invalid:
            notes.append("没有有效模组，本次仅导出异常清单，请补齐或修正数据后重试。")
        else:
            raise InputError("no_valid_modules", "输入没有模组记录，请核对输入", invalid)
    notify("match", f"正在匹配 {len(modules)} 个有效模组")
    matching_started = perf_counter()
    pairs, unpaired, graph = solve(modules, config, lambda message: notify("match", message))
    timings["匹配秒"] = round(perf_counter() - matching_started, 3)
    notify("export", "正在导出并提交结果")
    target = export(output or ROOT / "output", modules, pairs, unpaired, graph, invalid, notes, config, sources, timings)
    import json
    summary = json.loads((target.parent / "summary.json").read_text(encoding="utf-8"))
    notify("done", "结果已保存")
    return RunResult(target, summary)
