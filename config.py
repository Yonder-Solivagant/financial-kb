"""
作业 3 · 方向 A 财报知识库 —— 配置
默认 10 家白酒上市公司（作业示例行业）。换行业/公司只改 COMPANIES 即可。

数据源：巨潮资讯网（cninfo）公开接口 —— 拿交易所披露的年报 PDF 原文。
"""
import os
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"))

# 公司列表：code 为 A 股代码，market 为 sh/sz（用于 cninfo 列名）
COMPANIES = [
    {"name": "贵州茅台", "code": "600519", "market": "sh"},
    {"name": "五粮液",   "code": "000858", "market": "sz"},
    {"name": "泸州老窖", "code": "000568", "market": "sz"},
    {"name": "洋河股份", "code": "002304", "market": "sz"},
    {"name": "山西汾酒", "code": "600809", "market": "sh"},
    {"name": "古井贡酒", "code": "000596", "market": "sz"},
    {"name": "今世缘",   "code": "603369", "market": "sh"},
    {"name": "舍得酒业", "code": "600702", "market": "sh"},
    {"name": "迎驾贡酒", "code": "603198", "market": "sh"},
    {"name": "口子窖",   "code": "603589", "market": "sh"},
]

# 要抓的会计年度（年报在次年 3~4 月披露，cninfo 按披露年份检索）
FISCAL_YEARS = [2025, 2024]

# 路径
DATA_DIR = os.path.join(BASE, "data")        # 下载的年报 PDF
TEXT_DIR = os.path.join(BASE, "text")        # 抽取出的纯文本（带页码/章节）
INDEX_FILE = os.path.join(BASE, "kb_index.json")
EMB_FILE = os.path.join(BASE, "kb_emb.npy")

# 切块/检索
CHUNK_CHARS = 700        # 正文块长度
CHUNK_OVERLAP = 120
TOP_K = 8                # 融合后取多少块
PER_COMPANY_K = 3        # 跨公司题：每家公司各取多少块（分层抽样）
RRF_K = 60               # RRF 常数

# LLM（回答 + 引用）
LLM_BASE = os.environ.get("LLM_BASE", "https://api.deepseek.com")
LLM_KEY = os.environ.get("LLM_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

# 向量模型（智谱 embedding-3，OpenAI 兼容风格接口）
EMB_BASE = os.environ.get("EMB_BASE", "https://open.bigmodel.cn/api/paas/v4")
EMB_KEY = os.environ.get("EMB_KEY", "")
EMB_MODEL = os.environ.get("EMB_MODEL", "embedding-3")
EMB_BATCH = int(os.environ.get("EMB_BATCH", "16"))
