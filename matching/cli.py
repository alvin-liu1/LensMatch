import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys
from .models import Config
from .data import prepare
from .algorithm import solve
from .report import export

ROOT = Path(__file__).resolve().parent.parent


def run(input_path=None, a=None, b=None, output=None, config=None):
    config = config or Config()
    if bool(a) != bool(b):
        raise ValueError("A、B输入必须同时指定")
    if input_path and a:
        raise ValueError("统一输入和A/B输入只能选择一种")
    if a:
        sources = [(a, "A", 1 if config.mode == "mixed-imu" else 0), (b, "B", 0)]
    else:
        sources = [(input_path or ROOT / "input", "pool", 0 if config.mode == "no-imu" else None)]
    modules, invalid, notes = prepare(sources, config)
    if not modules:
        reason = invalid[0]["原因"] if invalid else "请核对输入"
        if config.use_score and any("Score缺失" in row["原因"] for row in invalid):
            reason += "。如果原始数据只有MTF，请在界面选择‘MTF 均值’来源；也可以取消启用Score"
        raise ValueError("没有有效模组。" + reason)
    if config.mode == "mixed-imu" and not a and any("IMU" in row["原因"] for row in invalid):
        raise ValueError("混配输入中存在缺失/非法IMU标记；请指定 --a 带IMU输入 --b 无IMU输入，或补齐IMU_Flag")
    if any("IMU标记与输入分组冲突" in row["原因"] or "无IMU模式不能" in row["原因"] for row in invalid):
        raise ValueError("业务模式与数据IMU标记冲突，请核对分组或切换模式")
    pairs, unpaired, graph = solve(modules, config)
    target = export(output or ROOT / "output", modules, pairs, unpaired, graph, invalid, notes, config, sources)
    print(f"模式: {config.mode} | 有效模组: {len(modules)} | 配对: {len(pairs)} | 未配对: {len(unpaired)} | 无效数据: {len(invalid)}")
    for note in notes:
        print(note)
    print(f"结果: {target.resolve()}")
    return target


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(data, dict):
        raise ValueError("配置必须是JSON对象")
    unknown = set(data) - {f.name for f in fields(Config)}
    if unknown:
        raise ValueError("未知配置项: " + ", ".join(sorted(unknown)))
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="摄像头模组一键提取与最优配对")
    parser.add_argument("--input", help="统一输入目录或文件；默认项目input目录，不递归读取历史子目录")
    parser.add_argument("--a", help="A组目录或文件；混配模式A必须带IMU")
    parser.add_argument("--b", help="B组目录或文件；B必须无IMU")
    parser.add_argument("--output", help="输出根目录，每次建立独立结果目录")
    parser.add_argument("--mode", choices=["no-imu", "mixed-imu"], default=None)
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    score = parser.add_mutually_exclusive_group()
    score.add_argument("--use-score", action="store_true")
    score.add_argument("--no-score", action="store_true")
    parser.add_argument("--gui", action="store_true", help="打开操作界面")
    args = parser.parse_args(argv)
    try:
        data = load_config(args.config)
        if args.mode:
            data["mode"] = args.mode
        if args.use_score or args.no_score:
            data["use_score"] = args.use_score
        config = Config(**data)
        if args.gui:
            from .gui import launch
            launch(config, args.input, args.a, args.b, args.output)
        else:
            run(args.input, args.a, args.b, args.output, config)
        return 0
    except (ValueError, OSError, ImportError, TypeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
