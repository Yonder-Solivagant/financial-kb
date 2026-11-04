"""
作业3 的 10 道测试题（含 3 道跨公司全景题）+ 逐题记录。

跑法：python questions.py            → 生成 问答记录.md（召回块 + 答案 + 判定 + 错在哪）
判定用大模型当"考官"：把题、答案、召回片段一起给它，要求只依据片段判对错，
再人工复核关键数字（数字题必须回原 PDF 抽查）。
"""
import json
import os
import re
import time

from config import LLM_BASE, LLM_KEY, LLM_MODEL
from qa import ask, retrieve

QUESTIONS = [
    {"q": "贵州茅台 2025 年营业收入和归属于上市公司股东的净利润分别是多少？"},
    {"q": "五粮液 2025 年酒类业务收入是多少？其中高价位酒产品收入占比情况如何？"},
    {"q": "泸州老窖 2025 年高档酒类收入是多少？"},
    {"q": "洋河股份 2025 年末合同负债金额是多少？公司对合同负债变动的解释是什么？"},
    {"q": "山西汾酒 2025 年省外市场收入是多少？占公司营业收入的比重如何？"},
    {"q": "今世缘 2025 年江苏省内市场与省外市场的收入分别是多少？"},
    {"q": "迎驾贡酒 2025 年中高档产品收入占比是多少？"},
    {"q": "十家白酒公司中，2025 年营业收入最高的是哪一家？相比 2024 年营业收入增速最快的是哪一家？", "cross": True},
    {"q": "对比贵州茅台与五粮液 2025 年的毛利率，哪一家更高？", "cross": True},
    {"q": "哪些白酒公司在 2025 年年报中提到了国际化、海外市场或出海布局？", "cross": True},
]

JUDGE_SYSTEM = ("你是严格考官。只依据给出的【证据片段】判断【答案】是否正确。"
                 "输出三行，格式固定：\n判定：正确 / 部分正确 / 错误\n理由：一句话\n错在哪：没有错就写「无」，有错就具体写错在哪个数字或表述")


def llm(system, user, temperature=0):
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
                   {"role": "system", "content": system},
                   {"role": "user", "content": user}],
                   "temperature": temperature},
               timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def judge(question, answer, hits):
    evidence = "\n\n".join(
        f"[{h['id']}]（{h['company']} {h['year']}年报 第{h['page']}页）\n{h['text'][:900]}"
        for h in hits
    )
    user = f"【问题】{question}\n\n【答案】{answer}\n\n【证据片段】\n{evidence}"
    try:
        return llm(JUDGE_SYSTEM, user)
    except Exception as e:
        return f"判定：无法判定\n理由：{e}\n错在哪：-"


def run():
    out = ["# 作业3 · 财报知识库 · 10 题逐题记录", "",
           f"> 运行时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　语料：10 家公司 × 2024/2025 年报（20 份 PDF）",
           "> 召回：BM25（CJK 二元组）+ 向量（embedding-3）→ RRF 融合；跨公司题按公司分层抽样。",
           "> 判定：DeepSeek 当考官，只依据召回片段判对错；数字题另做原文抽查（见文末复核）。", ""]
    summary = []
    for i, item in enumerate(QUESTIONS, 1):
        q = item["q"]
        print(f"\n=== Q{i} {q}", flush=True)
        hits = retrieve(q)
        res = ask(q)
        v = judge(q, res["answer"], hits)
        m = re.match(r"判定[:：]\s*(\S+)", v)
        verdict = m.group(1) if m else "?"
        summary.append(verdict)
        out += [
            f"## Q{i}　{q}",
            "",
            f"- **类型**：{'跨公司全景题' if item.get('cross') else '单公司事实题'}",
            f"- **判定**：{verdict}",
            "",
            "**召回块（出处）**",
            "",
        ]
        for h in hits:
            snippet = re.sub(r"\s+", " ", h["text"])[:110]
            out.append(f"- `{h['id']}`（{h['company']} {h['year']} 第{h['page']} 页｜{h['section'] or '—'}）{snippet}…")
        out += ["", "**答案**", "", "```", res["answer"].strip(), "```", "", "**考官判语**", "", "```", v.strip(), "```", ""]
    out += ["## 汇总", "", "| 题号 | 类型 | 判定 |", "|---|---|---|"]
    for i, item in enumerate(QUESTIONS, 1):
        out.append(f"| Q{i} | {'跨公司' if item.get('cross') else '单公司'} | {summary[i-1]} |")
    out.append("")
    with open("问答记录.md", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n判定汇总：", summary, flush=True)
    print("已写 问答记录.md", flush=True)


if __name__ == "__main__":
    run()
