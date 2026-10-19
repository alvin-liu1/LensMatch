"""Load split production exports, multi-sheet workbooks or prepared tables."""
from pathlib import Path
import math
import csv
from io import StringIO
from .errors import InputError
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
        raise InputError("duplicate_columns", "表中存在同义重复列，请保留一个字段")
    return df.replace(r"^\s*$", pd.NA, regex=True)


def tables_in_file(path, notes):
    if path.suffix.lower() not in {".csv", ".txt", ".tsv"}:
        try:
            workbook = pd.ExcelFile(path)
        except (ValueError, OSError):
            workbook = None
        if workbook is not None:
            with workbook:
                tables = []
                for name in workbook.sheet_names:
                    df = canonical(pd.read_excel(workbook, sheet_name=name, dtype=object, keep_default_na=False))
                    df["__location"] = [f"{path.resolve()} / {name} / 第{i + 2}行" for i in range(len(df))]
                    tables.append((f"{path.name}/{name}", df))
                return tables
    error = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeError as exc:
            error = exc
    else:
        raise InputError("encoding", f"{path.name} 不能按 UTF-8/GBK 解码: {error}")
    # Production .xls files can append another unrelated table after a blank section.
    lines = text.splitlines()
    separator = next((i for i, line in enumerate(lines[1:], 1) if not line.strip()), None)
    tail = [line for line in lines[separator + 1:] if line.strip()] if separator is not None else []
    # Recognize the appended MTF measurement header specifically. Ordinary blank
    # rows inside a table must never discard subsequent module records.
    if tail and "MTF [%]" in tail[0] and not tail[0].split("\t")[0].strip():
        notes.append(f"{path.name}: 仅读取首个连续表，空行后的附加区域未参与配对")
        text = "\n".join(lines[:separator])
    if not lines:
        raise InputError("empty_file", f"空文件: {path}")
    sep = "\t" if "\t" in lines[0] else ","
    reader = csv.reader(StringIO(text), delimiter=sep)
    headers = next(reader)
    rows, locations = [], []
    while True:
        line = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) > len(headers):
            raise InputError("column_count", f"{path.resolve()} / 第{line}行: 字段数量超过表头，请核对分隔符")
        rows.append(row + [""] * (len(headers) - len(row)))
        locations.append(f"{path.resolve()} / 第{line}行")
    df = canonical(pd.DataFrame(rows, columns=headers))
    df["__location"] = locations
    return [(path.name, df)]


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
        raise InputError("missing_input", f"输入不存在: {path}")
    paths = sorted(path.iterdir()) if path.is_dir() else [path]
    files = [p for p in paths if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$")]
    if not files:
        raise InputError("no_files", f"未找到数据文件: {path}")
    return files


def locations(record):
    return tuple(dict.fromkeys(
        part for key, value in record.items() if str(key).startswith("__") and isinstance(value, str)
        for part in value.split("\n") if part))


def unique_rows(df, label):
    df = df.dropna(subset=["SN."]).copy()
    df["SN."] = df["SN."].astype(str).str.strip()
    df = df[df["SN."] != ""]
    metadata = [c for c in df if str(c).startswith("__")]
    metrics = [c for c in df if c not in metadata]
    for column in metrics:
        if column != "SN.":
            values = pd.to_numeric(df[column], errors="coerce")
            df[column] = values.where(values.notna(), df[column])
    distinct = df.drop_duplicates(subset=metrics)
    duplicated = distinct.loc[distinct.duplicated("SN.", keep=False), "SN."].unique()
    if len(duplicated):
        details = []
        for sn in duplicated[:10]:
            records = df[df["SN."] == sn]
            changed = [c for c in metrics if c != "SN." and records[c].nunique(dropna=False) > 1]
            origins = [p for record in records.to_dict("records") for p in locations(record)]
            details.append(f"SN={sn}，冲突字段={','.join(changed)}；" + "；".join(dict.fromkeys(origins)))
        raise InputError("conflicting_retest", f"{label}: 同一SN存在冲突记录，请先确认复测取值:\n" + "\n".join(details))
    if metadata:
        grouped = df.groupby("SN.", sort=False)
        result = distinct[metrics].copy().set_index("SN.")
        for column in metadata:
            result[column] = grouped[column].agg(lambda values: "\n".join(dict.fromkeys(v for v in values if isinstance(v, str))))
        return result.reset_index()
    return distinct


def load_source(source, notes, invalid=None, group="pool", progress=None):
    roles = {}
    flag_tables = []
    score_tables = []
    for path in discover(source):
        if progress:
            progress(f"读取 {path.name}")
        for label, df in tables_in_file(path, notes):
            role = role_of(df)
            if role is None:
                notes.append(f"跳过 {label}: 非配对数据表（例如Shading）")
                continue
            # Ignore truly empty Excel rows, but retain measurements without an SN.
            content = [c for c in df if c != "__location"]
            df = df.dropna(subset=content, how="all").copy()
            missing_sn = df["SN."].isna() | df["SN."].astype(str).str.strip().eq("")
            if invalid is not None:
                for record in df[missing_sn].to_dict("records"):
                    invalid.append({"SN": "", "Group": group, "来源": record["__location"],
                                    "错误代码": "missing_sn", "原因": "SN 缺失，无法识别模组",
                                    "原始记录": str({k: str(v) for k, v in record.items() if not k.startswith("__")})})
            df = df[~missing_sn].copy()
            provenance = f"__source_{role}"
            df = df.rename(columns={"__location": provenance})
            cols = {"prepared": ["SN.", "AEC", "R/G", "B/G", "Block3_H", "Block4_H"],
                    "MTF": ["SN.", "Block3_H", "Block4_H"], "AEC": ["SN.", "AEC"],
                    "AWB": ["SN.", "R/G", "B/G"]}[role]
            roles.setdefault(role, []).append(df[[c for c in cols if c in df] + [provenance]])
            if "IMU_Flag" in df:
                flag_tables.append(df[["SN.", "IMU_Flag", provenance]].rename(columns={provenance: "__source_IMU_Flag"}))
            if "Score" in df:
                score_tables.append(df[["SN.", "Score", provenance]].rename(columns={provenance: "__source_Score"}))
            notes.append(f"读取 {label}: {role}")
    if "prepared" in roles:
        if len(roles) > 1:
            raise InputError("mixed_formats", "同一输入包含原始表和提取结果，请分开存放，避免重复批次")
        result = unique_rows(pd.concat(roles["prepared"], ignore_index=True), "提取结果")
    else:
        missing = {"MTF", "AEC", "AWB"} - roles.keys()
        if missing:
            raise InputError("missing_tables", "缺少测试表: " + ", ".join(sorted(missing)))
        clean = {role: unique_rows(pd.concat(frames, ignore_index=True), role) for role, frames in roles.items()}
        # Outer join retains incomplete modules in Invalid instead of silently dropping them.
        result = clean["MTF"].merge(clean["AEC"], on="SN.", how="outer", validate="one_to_one")
        result = result.merge(clean["AWB"], on="SN.", how="outer", validate="one_to_one")
    for frames, column in ((flag_tables, "IMU_Flag"), (score_tables, "Score")):
        if frames:
            extra = pd.concat(frames, ignore_index=True).dropna(subset=[column])
            extra = unique_rows(extra, column)
            result = result.merge(extra, on="SN.", how="left", validate="one_to_one")
    return result


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def prepare(sources, config, progress=None):
    modules, invalid, notes = [], [], []
    seen = {}
    for source, group, assigned_imu in sources:
        frame = load_source(source, notes, invalid, group, progress)
        for record in frame.to_dict("records"):
            sn = str(record["SN."]).strip()
            if sn in seen:
                raise InputError("duplicate_sn", f"SN跨输入重复: {sn}，不能把同一模组当作两颗镜头；来源：" + "；".join(seen[sn] + locations(record)))
            seen[sn] = locations(record)
            reasons, codes = [], []
            values = {key: number(record.get(col)) for key, col in (("aec", "AEC"), ("rg", "R/G"), ("bg", "B/G"))}
            reasons.extend(f"{key} 缺失或非有限数值" for key, value in values.items() if value is None)
            if any(value is None for value in values.values()):
                codes.append("invalid_numeric")
            raw_imu = record.get("IMU_Flag")
            imu = number(raw_imu)
            has_imu = raw_imu is not None and not pd.isna(raw_imu) and str(raw_imu).strip() != ""
            if has_imu and imu not in (0, 1):
                reasons.append("IMU_Flag 必须为 0 或 1")
                codes.append("invalid_imu")
            elif assigned_imu is not None:
                if has_imu and imu != assigned_imu:
                    reasons.append("IMU标记与输入分组冲突")
                    codes.append("imu_conflict")
                imu = assigned_imu
            elif config.mode == "no-imu":
                if has_imu and imu != 0:
                    reasons.append("无IMU模式不能使用带IMU模组")
                    codes.append("imu_conflict")
                imu = 0
            elif imu not in (0, 1):
                reasons.append("混配模式缺少IMU标记，请指定A/B输入或补齐IMU_Flag")
                codes.append("missing_imu")
            block3, block4 = number(record.get("Block3_H")), number(record.get("Block4_H"))
            score = number(record.get("Score"))
            if config.score_source == "block-average":
                score = (block3 + block4) / 2 if block3 is not None and block4 is not None else None
            if config.use_score and score is None:
                reasons.append("启用Score但指定来源的Score缺失")
                codes.append("missing_score")
            if reasons:
                invalid.append({"SN": sn, "Group": group, "来源": "\n".join(locations(record)), "原因": "; ".join(reasons),
                                "错误代码": ";".join(codes or ["invalid_numeric"])})
                continue
            modules.append(Module(sn, **values, imu=int(imu), group=group, score=score, block3=block3, block4=block4, sources=locations(record)))
    modules.sort(key=lambda m: (m.group, m.sn))
    return modules, invalid, notes
