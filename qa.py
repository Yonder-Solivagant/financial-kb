"""
问答：BM25 + 向量双路召回 → RRF 融合 → LLM 生成带出处的答案。

三个要点（都来自课上/踩坑）：
1. **分层抽样**：跨公司题（"哪家最高""谁增速最快"）用全局 TopK 必然漏公司，
   这里对问题里点到（或"各家/哪些公司"）的公司分别召回再合并，保证每家都有机会上榜。
2. **答案必须带出处**：每条事实后面标 [公司#页码#块号]，页码能回原 PDF 核对。
3. **不许编**：片段里没有就说"资料中未提及"。
"""
import json
import os
import re

import numpy as np

from build_kb import BM25, tok
from config import (INDEX_FILE, EMB_FILE, TOP_K, PER_COMPANY_K, RRF_K,
                    LLM_BASE, LLM_KEY, LLM_MODEL, COMPANIES)

SYSTEM = ("你是财报问答助手。只根据下面给出的【检索片段】回答问题，"
          "每个事实后用 [id] 标注来源（id 形如 贵州茅台2025#p42#17，页码即年报 PDF 页码）。"
          "片段里没有的信息，明确写「资料中未提及」；不要用常识补全，不要编造数字。"
          "如果问题涉及多家公司/多家横向比较，逐家列出，不要只答一家。")

_CACHE = {}


def load():
    if "data" not in _CACHE:
        d = json.load(open(INDEX_FILE, encoding="utf-8"))
        d["emb"] = np.load(EMB_FILE).astype(np.float32)
        d["tokens"] = [tok(c["text"]) for c in d["chunks"]]   # 缓存一次，查询时不再重切
        _CACHE["data"] = d
    return _CACHE["data"]


def _bm25_scores(data, question):
    bm = BM25(data["tokens"])
    bm.df = data["df"]
    bm.idf = data["idf"]
    bm.avgdl = data["avgdl"]
    return bm.scores(tok(question))


def _embed_query(question):
    from config import EMB_BASE, EMB_KEY, EMB_MODEL
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    import requests
    s = requests.Session()
    s.trust_env = False
    r = s.post(f"{EMB_BASE}/embeddings",
               headers={"Authorization": f"Bearer {EMB_KEY}", "Content-Type": "application/json"},
               json={"model": EMB_MODEL, "input": [question]}, timeout=60)
    r.raise_for_status()
    v = np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _rrf(rank_bm, rank_vec, k=RRF_K):
    """Reciprocal Rank Fusion：把两路召回的名次换成分数相加（名次 0 开始）"""
    score = {}
    for pos, idx in enumerate(rank_bm):
        score[idx] = score.get(idx, 0) + 1.0 / (k + pos + 1)
    for pos, idx in enumerate(rank_vec):
        score[idx] = score.get(idx, 0) + 1.0 / (k + pos + 1)
    return score


def mentioned_companies(question):
    names = [c["name"] for c in COMPANIES]
    hit = [n for n in names if n in question]
    if len(hit) >= 2:
        return hit
    # 泛指题（各家/哪些公司/十家/比较）→ 全量分层
    if re.search(r"各家|哪些公司|十家|10家|全部|全体|各家对比|板块|行业内|横向", question):
        return names
    return hit


def mentioned_years(question):
    return {y for y in ("2025", "2024", "2023") if y in question}


def _company_index(chunks):
    idx = {}
    for i, c in enumerate(chunks):
        idx.setdefault(c["company"], []).append(i)
    return idx


GENERIC_LABELS = {"合计", "小计", "总计", "项目", "名称", "单位", "金额", "数量", "占比",
                   "比例", "期末余额", "期初余额", "本期数", "上年同期数", "其他", "序号", "类别",
                   "本年比上年增减", "变动比例", "单位：元", "币种", "合计数"}


def _label_match(label, question):
    """标签与问题的宽松匹配：全等、前缀命中、或短标签被问题包含"""
    label = label.replace("（元）", "").replace("(元)", "").replace(" ", "").strip()
    if len(label) < 2 or label in GENERIC_LABELS:
        return False
    if label in question:
        return True
    if len(label) >= 3 and label[:3] in question:
        return True
    # 去掉口径后缀再比（高价位酒产品 → 高价位）
    core = re.sub(r"(白酒|酒类|产品|业务|收入|金额|合计|占比|比重|毛利率|情况|分类)$", "", label)
    if len(core) >= 3 and core in question:
        return True
    return False


def _label_hits(question, chunks, pool):
    """第三路召回：问题里点名的指标名（表格行首/列头）优先给对应表格块。

    例：问「合同负债」→ 那些行首写着「合同负债」的表格块直接进候选；
        问「中高档产品收入占比」→ 行首写着「中高档白酒」的表也命中（前缀匹配）。
    """
    hits = []
    for i in pool:
        labels = chunks[i].get("labels") or []
        for lb in labels:
            if _label_match(lb, question):
                hits.append(i)
                break
    return hits


def retrieve(question, k=TOP_K, stratified=True):
    """召回：BM25 + 向量 → RRF 融合。

    关键改动：**先做实体/年份过滤再做排序**。
    纯 BM25 在 15k 块上会被高频词稀释（「茅台」「2025」「营业收入」到处都是），
    真正稀有的信息（哪家公司、哪一年、哪张表）反而排不上去。
    这里先把候选池收到问题点到的公司（跨公司题则按公司分层），再排序。
    """
    data = load()
    chunks = data["chunks"]
    names = mentioned_companies(question) if stratified else []
    years = mentioned_years(question)

    # 公司名在候选池内已无区分度（全池都是这家公司），反而会把「关联方」这类
    # 反复出现公司名的表顶上来 → 池确定后把公司名从查询里去掉。
    q_bm = question
    for n in sorted(names, key=len, reverse=True):
        q_bm = q_bm.replace(n, "")

    bm_scores = _bm25_scores(data, q_bm)
    qv = _embed_query(question)
    vec_scores = data["emb"] @ qv

    by_company = _company_index(chunks)
    # 噪声块（只有页眉的碎块）不进候选
    by_company = {k: [i for i in v if not chunks[i].get("noise")] for k, v in by_company.items()}
    non_noise = [i for i in range(len(chunks)) if not chunks[i].get("noise")]

    if len(names) == 1:
        pool = by_company.get(names[0], [])
        picked = list(pool)
    elif len(names) >= 2:
        picked = []
        for n in names:
            picked.extend(by_company.get(n, []))
    else:
        picked = list(non_noise)

    order_bm = sorted(picked, key=lambda i: -bm_scores[i])
    order_vec = sorted(picked, key=lambda i: -vec_scores[i])
    score = _rrf(order_bm, order_vec)

    # 第三路：指标名命中（表格行首）
    label_hits = _label_hits(question, chunks, picked)
    if label_hits:
        lpos = {i: r for r, i in enumerate(label_hits)}
        for i, r in lpos.items():
            score[i] = score.get(i, 0) + 1.0 / (RRF_K + r + 1)

    # 年份加权：问题里点了 2025，就压低其它年份
    if years:
        for i in picked:
            if chunks[i]["year"] not in years:
                score[i] = score.get(i, 0) * 0.35

    if len(names) >= 2:
        # 分层抽样：每家先取自己的高分块，保证「谁最高/谁最快」这类题不会只召回到一家
        by_c = {}
        for i in sorted(score, key=lambda i: -score[i]):
            by_c.setdefault(chunks[i]["company"], []).append(i)
        out = []
        for n in names:
            out.extend(by_c.get(n, [])[:PER_COMPANY_K])
        out.extend(sorted(score, key=lambda i: -score[i])[:k])
        seen, dedup = set(), []
        for i in out:
            if i in seen:
                continue
            seen.add(i)
            dedup.append(i)
        out = dedup[:max(k, len(names) * PER_COMPANY_K)]
    else:
        out = sorted(score, key=lambda i: -score[i])[:k]

    hits = []
    for rank, i in enumerate(out, 1):
        c = chunks[i]
        hits.append({**c, "rrf": round(float(score.get(i, 0)), 5), "rank": rank})
    return hits


def ask(question, k=TOP_K, use_llm=True):
    hits = retrieve(question, k=k)
    ctx = "\n\n".join(
        f"[{h['id']}]（{h['company']} {h['year']}年报 第{h['page']}页｜{h['section']}）\n{h['text']}"
        for h in hits
    )
    if not use_llm or not LLM_KEY:
        return {"answer": "（未配置 LLM_KEY，仅返回检索片段）\n\n" + ctx, "sources": [h["id"] for h in hits], "hits": hits}
    prompt = f"【检索片段】\n{ctx}\n\n【问题】{question}"
    try:
        import requests
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:
            pass
        s = requests.Session()
        s.trust_env = False
        r = s.post(f"{LLM_BASE}/chat/completions",
                   headers={"Authorization": f"Bearer {LLM_KEY}", "Content-Type": "application/json"},
                   json={"model": LLM_MODEL, "messages": [
                       {"role": "system", "content": SYSTEM},
                       {"role": "user", "content": prompt},
                   ], "temperature": 0},
                   timeout=180)
        r.raise_for_status()
        answer = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        answer = f"（LLM 调用失败：{e}）\n\n{ctx[:2000]}"
    return {"answer": answer, "sources": [h["id"] for h in hits], "hits": hits}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "贵州茅台 2025 年营业收入是多少？"
    res = ask(q)
    print("来源：", res["sources"])
    print(res["answer"])
