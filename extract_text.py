"""
把 data/ 下的年报 PDF 抽成 Markdown 文本（带页码 + 章节），存 text/。

用 pymupdf4llm：表格会被还原成 Markdown 表格（行/列对齐），这正是作业要求的
「表格按行列还原」——纯 get_text() 会把表格拍平成一行，数字对不上。

输出格式（每页一段）：
    [page 12]
    [section 第三节 管理层讨论与分析]
    ......markdown......
"""
import os
import re
import time
import pymupdf4llm
from config import DATA_DIR, TEXT_DIR

SEC_RE = re.compile(r"第[一二三四五六七八九十]+节\s*[^\n|]{0,30}")
PAGE_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


def extract_pdf(path):
    pages = pymupdf4llm.to_markdown(path, page_chunks=True)
    out = []
    section = ""
    for i, chunk in enumerate(pages, 1):
        text = chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)
        # 去掉页眉页脚里的 "N / M" 页码行
        text = "\n".join(PAGE_RE.sub("", ln).rstrip() for ln in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        # 章节跟踪：页内出现「第X节」就更新
        m = SEC_RE.search(text)
        if m:
            section = m.group(0).strip()
        out.append((i, section, text))
    return out


def main():
    os.makedirs(TEXT_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(".pdf"))
    for fn in files:
        pdf = os.path.join(DATA_DIR, fn)
        out = os.path.join(TEXT_DIR, fn.replace(".pdf", ".md"))
        if os.path.exists(out) and os.path.getsize(out) > 2000:
            print(f"[txt] 已存在，跳过 {fn}")
            continue
        t = time.time()
        try:
            pages = extract_pdf(pdf)
        except Exception as e:
            print(f"[txt] {fn} 抽取失败：{e}")
            continue
        with open(out, "w", encoding="utf-8") as f:
            for no, section, text in pages:
                f.write(f"\n[page {no}]\n")
                f.write(f"[section {section}]\n" if section else "")
                f.write(text + "\n")
        print(f"[txt] {fn} -> {os.path.basename(out)}（{len(pages)} 页，{time.time()-t:.0f}s）")


if __name__ == "__main__":
    main()
