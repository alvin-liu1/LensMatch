"""Load split production exports, multi-sheet workbooks or prepared tables."""
from pathlib import Path
import math
import pandas as pd
from .models import Module

EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".csv", ".txt", ".tsv"}
ALIASES = {
    "SN.": ["sn", "sn.", "serial", "serial number", "序列号"],
    "AEC": ["aec", "aec_light", "aec_light(-ob)"],
    "R/G": ["r/g", "r_g", "rg"], "B/G": ["b/g", "b_g", "bg"],
    "IMU_Flag": ["imu_flag", "imu", "imu flag"], "Score": ["score", "得分"],
    "Block3_H": ["block3_h"], "Block4_H": ["block4_h"],
}


def canonical(df):
    mapping = {alias: target for target, aliases in ALIASES.items() for alias in aliases}
    df = df.rename(columns={c: mapping.get(str(c).strip().lower(), str(c).strip()) for c in df.columns})
    if df.columns.duplicated().any():
        raise ValueError("表中存在同义重复列，请保留一个字段")
    return df.dropna(axis=1, how="all")


def tables_in_file(path, notes):
    if path.suffix.lower() not in {".csv", ".txt", ".tsv"}:
        try:
            workbook = pd.ExcelFile(path)
        except (ValueError, OSError):
            workbook = None
        if workbook is not None:
            with workbook:
                return [(f"{path.name}/{name}", canonical(pd.read_excel(workbook, sheet_name=name, dtype=object)))
                        for name in workbook.sheet_names]
    error = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeError as exc:
            error = exc
    else:
        raise ValueError(f"{path.name} 不能按 UTF-8/GBK 解码: {error}")
    # Production .xls files can append another unrelated table after a blank section.
    lines = text.splitlines()
    separator = next((i for i, line in enumerate(lines[1:], 1) if not line.strip()), None)
    tail = [line for line in lines[separator + 1:] if line.strip()] if separator is not None else []
    # Recognize the appended MTF measurement header specifically. Ordinary blank
    # rows inside a table must never discard subsequent module records.
    if tail and "MTF [%]" in tail[0] and not tail[0].split("\t")[0].strip():
        notes.append(f"{path.name}: 仅读取首个连续表，空行后的附加区域未参与配对")
        text = "\n".join(lines[:separator])
    from io import StringIO
    sep = "\t" if "\t" in lines[0] else ","
    return [(path.name, canonical(pd.read_csv(StringIO(text), sep=sep, dtype=object)))]


def role_of(df):
    cols = set(df.columns)
    if {"SN.", "AEC", "R/G", "B/G"} <= cols:
        return "prepared"
    if {"SN.", "Block3_H", "Block4_H"} <= cols:
        return "MTF"
    if {"SN.", "R/G", "B/G"} <= cols:
        return "AWB"
    if {"SN.", "AEC"} <= cols:
        return "AEC"
    return None


def discover(source):
    path = Path(source)
    if not path.exists():
        raise ValueError(f"输入不存在: {path}")
    paths = sorted(path.iterdir()) if path.is_dir() else [path]
    files = [p for p in paths if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$")]
    if not files:
        raise ValueError(f"未找到数据文件: {path}")
    return files


def unique_rows(df, label):
    df = df.dropna(subset=["SN."]).copy()
    df["SN."] = df["SN."].astype(str).str.strip()
    df = df[df["SN."] != ""]
    for column in df.columns:
        if column != "SN.":
            # Normalize numeric formatting before identifying conflicting retests.
            values = pd.to_numeric(df[column], errors="coerce")
            df[column] = values.where(values.notna(), df[column])
    df = df.drop_duplicates()
    duplicated = df.loc[df.duplicated("SN.", keep=False), "SN."].unique()
    if len(duplicated):
        raise ValueError(f"{label}: 同一SN存在冲突记录，请先确认复测取值: {', '.join(duplicated[:10])}")
    return df


def load_source(source, notes):
    roles = {}
    flag_tables = []
    score_tables = []
    for path in discover(source):
        for label, df in tables_in_file(path, notes):
            role = role_of(df)
            if role is None:
                notes.append(f"跳过 {label}: 非配对数据表（例如Shading）")
                continue
            cols = {"prepared": ["SN.", "AEC", "R/G", "B/G", "Block3_H", "Block4_H"],
                    "MTF": ["SN.", "Block3_H", "Block4_H"], "AEC": ["SN.", "AEC"],
                    "AWB": ["SN.", "R/G", "B/G"]}[role]
            roles.setdefault(role, []).append(df[[c for c in cols if c in df]])
            if "IMU_Flag" in df:
                flag_tables.append(df[["SN.", "IMU_Flag"]])
            if "Score" in df:
                score_tables.append(df[["SN.", "Score"]])
            notes.append(f"读取 {label}: {role}")
    if "prepared" in roles:
        if len(roles) > 1:
            raise ValueError("同一输入包含原始表和提取结果，请分开存放，避免重复批次")
        result = unique_rows(pd.concat(roles["prepared"], ignore_index=True), "提取结果")
    else:
        missing = {"MTF", "AEC", "AWB"} - roles.keys()
        if missing:
            raise ValueError("缺少测试表: " + ", ".join(sorted(missing)))
        clean = {role: unique_rows(pd.concat(frames, ignore_index=True), role) for role, frames in roles.items()}
        # Outer join retains incomplete modules in Invalid instead of silently dropping them.
        result = clean["MTF"].merge(clean["AEC"], on="SN.", how="outer", validate="one_to_one")
        result = result.merge(clean["AWB"], on="SN.", how="outer", validate="one_to_one")
    for frames, column in ((flag_tables, "IMU_Flag"), (score_tables, "Score")):
        if frames:
            extra = pd.concat(frames, ignore_index=True).dropna(subset=[column])
            extra = unique_rows(extra, column)
            result = result.merge(extra, on="SN.", how="left", validate="one_to_one")
    if result.empty:
        raise ValueError("输入没有模组记录")
    return result


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def prepare(sources, config):
    modules, invalid, notes = [], [], []
    seen = set()
    for source, group, assigned_imu in sources:
        frame = load_source(source, notes)
        for record in frame.to_dict("records"):
            sn = str(record["SN."]).strip()
            if sn in seen:
                raise ValueError(f"SN跨输入重复: {sn}，不能把同一模组当作两颗镜头")
            seen.add(sn)
            reasons = []
            values = {key: number(record.get(col)) for key, col in (("aec", "AEC"), ("rg", "R/G"), ("bg", "B/G"))}
            reasons.extend(f"{key} 缺失或非有限数值" for key, value in values.items() if value is None)
            raw_imu = record.get("IMU_Flag")
            imu = number(raw_imu)
            has_imu = raw_imu is not None and not pd.isna(raw_imu) and str(raw_imu).strip() != ""
            if has_imu and imu not in (0, 1):
                reasons.append("IMU_Flag 必须为 0 或 1")
            elif assigned_imu is not None:
                if has_imu and imu != assigned_imu:
                    reasons.append("IMU标记与输入分组冲突")
                imu = assigned_imu
            elif config.mode == "no-imu":
                if has_imu and imu != 0:
                    reasons.append("无IMU模式不能使用带IMU模组")
                imu = 0
            elif imu not in (0, 1):
                reasons.append("混配模式缺少IMU标记，请指定A/B输入或补齐IMU_Flag")
            block3, block4 = number(record.get("Block3_H")), number(record.get("Block4_H"))
            score = number(record.get("Score"))
            if config.score_source == "block-average":
                score = (block3 + block4) / 2 if block3 is not None and block4 is not None else None
            if config.use_score and score is None:
                reasons.append("启用Score但指定来源的Score缺失")
            if reasons:
                invalid.append({"SN": sn, "Group": group, "来源": str(source), "原因": "; ".join(reasons)})
                continue
            modules.append(Module(sn, **values, imu=int(imu), group=group, score=score, block3=block3, block4=block4))
    modules.sort(key=lambda m: (m.group, m.sn))
    return modules, invalid, notes
