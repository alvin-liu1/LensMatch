# LensMatch

摄像头模组两两配对工具。一次操作完成数据读取、按 SN 合并、校验、全局最优匹配和结果导出。

支持两个无 IMU 模组配对，或一个带 IMU 与一个无 IMU 模组配对；支持统一输入与 A/B 跨组输入。

## 快速开始

需要 Python 3.10 或更新版本。

```powershell
python -m pip install -r requirements.txt
python match.py --input examples/noimu --use-score
```

Windows 可双击 `start.cmd` 打开操作界面。把同一批次的数据放入 `input` 后，选择模式并点击“开始匹配”，也可以直接运行 `python match.py`。公开仓库不含真实产线数据，首次试用请选择 `examples/noimu`。

IMU 混配示例：

```powershell
python match.py --mode mixed-imu --a examples/mixed/A.csv --b examples/mixed/B.csv --use-score
```

示例为合成数据。真实测试数据、历史结果和本机配置不随代码发布。

## 匹配规则

- 默认硬阈值：ΔAEC ≤ 1，ΔR/G ≤ 10，ΔB/G ≤ 10；不自动放宽。
- Score 定义为 `(Block3_H + Block4_H) / 2`，默认启用 ΔScore ≤ 6.8 的条件；客户界面无需勾选。
- 先最大化配对数量，再最小化总归一化成本；默认优化色彩差异。
- 一般图使用 Blossom；混配及 A/B 输入使用最大二分匹配与最小费用流。
- 阈值和权重通过 `config.json` 调整。

输出包含 Pairs、Unpaired、Invalid、Data、Config 工作表，每次运行生成独立目录。

## 测试

```powershell
python -m unittest discover -s tests -v
```

覆盖 100 组随机小样本的穷举对照、数据校验和合成示例。两项本地真实数据回归在未提供产线数据时跳过。

详见[使用说明](使用说明.md)。
