"""
从各公司年报的「主要会计数据」表里抽出关键指标，做成一张对照表。

用途有两个：
1. 给跨公司题提供**人工基准**（不信大模型说的，直接从原文表格读）；
2. 验证知识库答出来的数字对不对——答案里的数字必须能在对照表里对上。

用法：python tools/extract_key_metrics.py [年份]
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_DIR = os.path.join(BASE, "text")


def norm(s):
    return (s or "").replace("\n", "").replace(" ", "").replace("<br>", "")


def row_cells(line):
    """把一行 markdown 表格拆成单元格（去掉 markdown 的首尾竖线，保留中间的空单元格）"""
    parts = line.strip().split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [norm(c) for c in parts]


def tables_of(text):
    """把连续以 | 开头的行切成一个个表格块"""
    blocks, cur = [], []
    for ln in text.split("\n"):
        if ln.strip().startswith("|"):
            cur.append(ln)
        else:
            if cur:
                blocks.append(cur)
                cur = []
    if cur:
        blocks.append(cur)
    return blocks


def parse_report(path):
    """从「主要会计数据」表里抽关键指标；兼容各家不同的表头写法与行名后缀"""
    text = open(path, encoding="utf-8").read()
    cands = []
    for rows in tables_of(text):
        tb = [row_cells(r) for r in rows]
        flat = " ".join(" ".join(r) for r in tb)
        if "营业收入" not in flat:
            continue
        header = None
        for r in tb:
            joined = "".join(r)
            if "2025年" in joined and ("2024年" in joined or "上年" in joined):
                header = r
                break
        if header is not None:
            cands.append((tb, header))
    # 逐个候选试抽，取第一个能抽出像样数字的
    for tb, header in cands:
        out = extract_rows(tb, header)
        if out.get("营业收入") and out["营业收入"][0] > 1e8:
            return out
    return {}


def extract_rows(tb, header):
    hpos = {v: i for i, v in enumerate(header)}

    def num(x):
        x = x.replace(",", "").replace("%", "")
        try:
            return float(x)
        except Exception:
            return None

    def cell(row, *keys):
        for k in keys:
            for hk, idx in hpos.items():
                if k in hk:
                    return row[idx] if idx < len(row) else ""
        return ""

    out = {}
    for row in tb:
        key = row[0]
        if key.startswith("营业收入") or key.startswith("归属于上市公司股东的净利润") \
                or key.startswith("归属于上市公司股东的扣除非"):
            v25 = num(cell(row, "2025年"))
            v24 = num(cell(row, "2024年"))
            pct = num(cell(row, "增减", "增长", "变动"))
            if v25 is not None:
                short = ("营业收入" if key.startswith("营业收入")
                         else "归属于上市公司股东的净利润" if key.startswith("归属于上市公司股东的净利润")
                         else "扣非净利润")
                out[short] = (v25, v24, pct)
        if key.startswith("加权平均净资产收益率"):
            v25 = num(cell(row, "2025年"))
            if v25 is not None:
                out["加权ROE"] = (v25, num(cell(row, "2024年")), None)
    return out


def main():
    year = sys.argv[1] if len(sys.argv) > 1 else "2025"
    rows = []
    for fn in sorted(os.listdir(TEXT_DIR)):
        if not fn.endswith(".md") or f"_{year}年报" not in fn:
            continue
        company = fn.split("_")[0]
        d = parse_report(os.path.join(TEXT_DIR, fn))
        rev = d.get("营业收入")
        np_ = d.get("归属于上市公司股东的净利润")
        rows.append((company, rev, np_, d.get("加权ROE")))
    rows.sort(key=lambda r: -(r[1][0] if r[1] else 0))
    print(f"| 公司 | {year} 营业收入(亿元) | 同比(%) | {year} 归母净利润(亿元) | 同比(%) | 加权ROE(%) |")
    print("|---|---|---|---|---|---|")
    for company, rev, np_, roe in rows:
        if not rev:
            continue
        r_yi = rev[0] / 1e8
        n_yi = f"{np_[0]/1e8:.2f}" if np_ else "—"
        n_pct = f"{np_[2]:.2f}" if np_ and np_[2] is not None else "—"
        roe_s = f"{roe[0]:.2f}" if roe else "—"
        print(f"| {company} | {r_yi:.2f} | {rev[2] if rev[2] is not None else '—'} | {n_yi} | {n_pct} | {roe_s} |")
    print()
    print("人工基准（直接读原文表格，用于核对知识库答案的数字）：")
    for company, rev, np_, roe in rows:
        if rev:
            print(f"  {company}: 营业收入 {rev[0]/1e8:.2f} 亿（上年 {rev[1]/1e8:.2f} 亿，{rev[2]}%）")


if __name__ == "__main__":
    main()
