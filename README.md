# LensMatch

摄像头模组两两配对工具。一次操作完成数据读取、按 SN 合并、校验、全局最优匹配和结果导出。

支持两个无 IMU 模组配对，或一个带 IMU 与一个无 IMU 模组配对；支持统一输入与 A/B 跨组输入。

## 快速开始

### Windows 免安装桌面版

同事使用 `LensMatch-Windows-x64.zip`：完整解压后双击 `LensMatch.exe`，无需安装 Python 或 Excel。界面支持选择文件/目录、两种配对模式、A/B 分组、Score 筛选、运行进度及结果统计。

开发者在 Windows x64 + Python 3.12 环境构建：

```powershell
python -m pip install -r requirements-build.txt
python build_windows.py
```

产物在 `dist/LensMatch-Windows-x64.zip`。包内包含配置、合成示例、中文说明和运行依赖，不包含产线数据。必须保留整个解压目录。配置、默认输入和输出均相对 exe 所在目录解析，建议解压到桌面等可写位置。

也可在 GitHub Actions 手动运行 **Windows package**，下载同名构建产物。流程会先运行回归测试，再验证打包程序可完成示例配对并打开界面；只有通过后才上传 ZIP。Mac 不能交叉编译该 Windows 程序。

### 源码运行

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
- Score 定义为 `(Block3_H + Block4_H) / 2`，默认启用 ΔScore ≤ 6.8 的条件；界面默认勾选，也可以取消。
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
