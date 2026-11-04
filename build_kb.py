"""
切块 + 双索引（BM25 + 向量），供问答检索。

- BM25：自写实现，CJK 用「重叠二元组」切词（不引第三方 rank_bm25，零依赖、可控）
- 向量：智谱 embedding-3（每块一次 embedding，落盘 kb_emb.npy）
- 融合：RRF（Reciprocal Rank Fusion），名次相加，比直接加权稳
- 元数据：公司 / 年份 / 页码 / 章节 / 是否表格 —— 答案要能指到出处
"""
import json
import math
import os
import re
from collections import Counter

import numpy as np

from config import (TEXT_DIR, INDEX_FILE, EMB_FILE, CHUNK_CHARS, CHUNK_OVERLAP,
                    TOP_K, PER_COMPANY_K, RRF_K, COMPANIES)

CJK = re.compile(r"[一-鿿]")
PAGE_RE = re.compile(r"^\[page (\d+)\]$")
SEC_RE = re.compile(r"^\[section (.*)\]$")


def tok(s):
    """CJK → 重叠二元组；英文/数字 → 词。"""
    s = re.sub(r"\s+", "", s)
    cjk = CJK.findall(s)
    grams = ["".join(cjk[i:i + 2]) for i in range(len(cjk) - 1)]
    return grams + [w.lower() for w in re.findall(r"[A-Za-z0-9]+", s)]


def split_company_year(fn):
    """'贵州茅台_600519_2025年报.md' -> ('贵州茅台', '600519', '2025')"""
    stem = fn[:-3]
    m = re.match(r"(.+?)_(\d{6})_(\d{4})年报$", stem)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r"(.+?)_(\d{4})年报$", stem)
    if m:
        return m.group(1), "", m.group(2)
    return stem, "", ""


def split_tables(text):
    """把 markdown 表格块与普通正文分开：表格整块保留（不切开），正文按窗口切。"""
    lines = text.split("\n")
    blocks, cur, cur_is_table = [], [], False
    for ln in lines:
        is_table = ln.strip().startswith("|")
        if cur and is_table != cur_is_table:
            blocks.append((cur_is_table, "\n".join(cur)))
            cur = []
        cur_is_table = is_table
        cur.append(ln)
    if cur:
        blocks.append((cur_is_table, "\n".join(cur)))
    return blocks


def table_labels(block):
    """取表格里每行的行首单元格（指标名）+ 表头列名，如 营业收入 / 毛利率"""
    labels = []
    rows = [ln for ln in block.split("\n") if ln.strip().startswith("|")]
    for i, ln in enumerate(rows):
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        cells = [c.replace("<br>", "").replace("\n", "") for c in cells]
        if not cells:
            continue
        if i == 0:      # 表头列名也当标签（毛利率、营业收入 常在列头）
            for c in cells[1:]:
                if c and not set(c) <= {"-"}:
                    labels.append(c)
            continue
        first = cells[0]
        if first and not set(first) <= {"-"}:
            labels.append(first)
    return labels


NOISE_RE = re.compile(r"[^\n]{0,60}?(股份有限公司|有限公司)[^\n]{0,20}?20\d{2}\s*年年度报告")


def _is_noise(text):
    """只有页眉/章节分隔的碎块：除标题外正文不足 30 字"""
    body = SEC_RE.sub("", text)
    body = NOISE_RE.sub("", body)
    return len(re.sub(r"\s+", "", body)) < 30


def chunk_report(path):
    fn = os.path.basename(path)
    company, code, year = split_company_year(fn)
    raw = open(path, encoding="utf-8").read()
    pages = re.split(r"\n\[page (\d+)\]\n", raw)
    chunks = []
    seq = 0
    for i in range(1, len(pages), 2):
        page_no = int(pages[i])
        body = pages[i + 1]
        section = ""
        m = SEC_RE.search(body)
        if m:
            section = m.group(1).strip()
        # 逐行找 section 标记（每页可能有多个）
        for blk_is_table, blk in split_tables(body):
            blk = SEC_RE.sub("", blk).strip()
            if not blk:
                continue
            if blk_is_table:
                seq += 1
                chunks.append({
                    "id": f"{company}{year}#p{page_no}#{seq}",
                    "company": company, "code": code, "year": year,
                    "page": page_no, "section": section, "kind": "table",
                    "labels": table_labels(blk),
                    "noise": False,
                    "text": blk[:4000],
                })
                continue
            start = 0
            while start < len(blk):
                seg = blk[start:start + CHUNK_CHARS]
                if seg.strip():
                    seq += 1
                    chunks.append({
                        "id": f"{company}{year}#p{page_no}#{seq}",
                        "company": company, "code": code, "year": year,
                        "page": page_no, "section": section, "kind": "text",
                        "labels": [],
                        "noise": _is_noise(seg),
                        "text": seg.strip(),
                    })
                if start + CHUNK_CHARS >= len(blk):
                    break
                start += CHUNK_CHARS - CHUNK_OVERLAP
    return chunks


class BM25:
    def __init__(self, docs_tokens):
        self.N = len(docs_tokens)
        self.docs = docs_tokens
        self.doc_len = [len(d) for d in docs_tokens]
        self.avgdl = sum(self.doc_len) / max(1, self.N)
        self.df = Counter()
        for d in docs_tokens:
            for w in set(d):
                self.df[w] += 1
        self.idf = {w: math.log((self.N - c + 0.5) / (c + 0.5) + 1) for w, c in self.df.items()}

    def scores(self, q_tokens):
        q = set(q_tokens)
        out = np.zeros(self.N, dtype=np.float32)
        for w in q:
            idf = self.idf.get(w)
            if not idf:
                continue
            for i, d in enumerate(self.docs):
                tf = d.count(w)
                if tf:
                    out[i] += idf * tf * 2.2 / (tf + 1.2 * (1 - 0.75 + 0.75 * self.doc_len[i] / self.avgdl))
        return out


def build():
    chunks = []
    files = sorted(f for f in os.listdir(TEXT_DIR) if f.endswith(".md"))
    for fn in files:
        cs = chunk_report(os.path.join(TEXT_DIR, fn))
        chunks += cs
        print(f"[kb] {fn}: {len(cs)} 块")
    print(f"[kb] 合计 {len(chunks)} 块")

    toks = [tok(c["text"]) for c in chunks]
    bm = BM25(toks)
    data = {
        "chunks": chunks,
        "df": dict(bm.df), "idf": bm.idf, "avgdl": bm.avgdl,
        "companies": [c["name"] for c in COMPANIES],
        "built_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    json.dump(data, open(INDEX_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[kb] 索引已存 {INDEX_FILE}（{os.path.getsize(INDEX_FILE)/1024/1024:.1f} MB）")
    return data


MAX_EMB_CHARS = 1200   # embedding 输入截断（超出模型上限会 400）


def embed(chunks):
    """调用 embedding API，返回归一化后的向量矩阵（float32）。支持断点续跑。"""
    from config import EMB_BASE, EMB_KEY, EMB_MODEL, EMB_BATCH
    if not EMB_KEY:
        raise SystemExit("未配置 EMB_KEY（见 .env.example）")
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    import requests
    s = requests.Session()
    s.trust_env = False
    headers = {"Authorization": f"Bearer {EMB_KEY}", "Content-Type": "application/json"}

    texts = [(c["text"][:MAX_EMB_CHARS] or "空") for c in chunks]

    # 断点续跑：已完成的向量先存下来
    done = 0
    vecs = []
    if os.path.exists(EMB_FILE):
        try:
            part = np.load(EMB_FILE)
            if len(part) == len(texts):
                print(f"[emb] 已有完整向量 {part.shape}，跳过")
                return part.astype(np.float32)
            vecs = [row for row in part.astype(np.float32)]
            done = len(vecs)
            print(f"[emb] 断点续跑：已有 {done}/{len(texts)}")
        except Exception as e:
            print(f"[emb] 已有向量读不出来，重来：{e}")

    for i in range(done, len(texts), EMB_BATCH):
        batch = texts[i:i + EMB_BATCH]
        try:
            r = s.post(f"{EMB_BASE}/embeddings", headers=headers,
                       json={"model": EMB_MODEL, "input": batch}, timeout=180)
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda d: d.get("index", 0))
            vecs.extend([d["embedding"] for d in data])
        except Exception as e:
            # 降级：逐条重试，实在不行就用短文本占位（保证索引完整）
            body = ""
            try:
                body = e.response.text[:200]
            except Exception:
                pass
            print(f"[emb] 批次 {i} 失败（{e} {body}），改为逐条重试", flush=True)
            for t in batch:
                try:
                    r = s.post(f"{EMB_BASE}/embeddings", headers=headers,
                               json={"model": EMB_MODEL, "input": [t[:300] or "空"]}, timeout=120)
                    r.raise_for_status()
                    vecs.append(r.json()["data"][0]["embedding"])
                except Exception as e2:
                    print(f"[emb] 单条也失败，占位：{e2}", flush=True)
                    vecs.append([0.0] * 2048)
        if (i // EMB_BATCH) % 20 == 0:
            arr = np.array(vecs, dtype=np.float32)
            arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
            np.save(EMB_FILE, arr.astype(np.float16))
            print(f"[emb] {len(vecs)}/{len(texts)}", flush=True)

    arr = np.array(vecs, dtype=np.float32)
    arr /= (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)
    np.save(EMB_FILE, arr.astype(np.float16))
    print(f"[emb] 向量已存 {EMB_FILE}  shape={arr.shape}")
    return arr


if __name__ == "__main__":
    data = build()
    embed(data["chunks"])
