import argparse
import sys
from .models import Config

from .runtime import ROOT, load_config
from .service import execute


def run(input_path=None, a=None, b=None, output=None, config=None):
    result = execute(input_path, a, b, output, config)
    summary = result.summary
    print(" | ".join(f"{key}: {summary[key]}" for key in ["模式", "有效模组", "配对数", "未配对数", "无效模组"]))
    for note in summary["读取说明"]:
        print(note)
    print(f"结果: {result.target.resolve()}")
    return result.target


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
        if args.gui or (getattr(sys, "frozen", False) and not argv and len(sys.argv) == 1):
            from .gui import launch
            launch(config, args.input, args.a, args.b, args.output)
        else:
            run(args.input, args.a, args.b, args.output, config)
        return 0
    except (ValueError, OSError, ImportError, TypeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
