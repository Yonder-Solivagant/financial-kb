"""
下载年报 PDF 到 data/（巨潮资讯网 cninfo 公开接口）。

要点（都是实测踩出来的）：
1. 查公告必须带 orgId，接口参数 stock = "代码,orgId"；只传代码永远返回 0 条。
2. pageSize 上限 30，要翻页取全（年报披露在次年 3~4 月，按披露年份查）。
3. 标题过滤：排除「摘要 / 英文版 / 更正 / 修订 / 取消」。
"""
import os
import time
import requests
from config import COMPANIES, DATA_DIR, FISCAL_YEARS

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"}
TOP_SEARCH = "http://www.cninfo.com.cn/new/information/topSearch/query"
QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC = "http://static.cninfo.com.cn/"

EXCLUDE = ["摘要", "英文", "更正", "修订", "取消", "问询", "说明", "关于", "意见", "回复"]


def _org_id(code, session):
    r = session.post(TOP_SEARCH, data={"keyWord": code, "maxNum": 10}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    for it in r.json():
        if it.get("code") == code:
            return it.get("orgId")
    return None


def _announcements(code, org_id, market, publish_year, session):
    out = []
    for page in range(1, 21):
        payload = {
            "pageNum": page, "pageSize": 30, "tabName": "fulltext",
            "column": "szse" if market == "sz" else "sse",
            "stock": f"{code},{org_id}",
            "seDate": f"{publish_year}-01-01~{publish_year}-12-31",
            "isHL": "", "catName": "", "keys": "", "sortName": "", "sortType": "",
            "limit": "", "showTitle": "",
        }
        r = session.post(QUERY, data=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        anns = r.json().get("announcements") or []
        out += anns
        if len(anns) < 30:
            break
        time.sleep(0.3)
    return out


def pick_annual(anns, fiscal_year):
    """从公告列表里挑出 '<公司><fiscal>年年度报告' 全文版"""
    hits = []
    for a in anns:
        title = (a.get("announcementTitle") or "").replace(" ", "")
        if f"{fiscal_year}年年度报告" not in title:
            continue
        if any(b in title for b in EXCLUDE):
            continue
        hits.append(a)
    return hits


def download_reports(companies=None, years=None, force=False):
    companies = companies or COMPANIES
    years = years or FISCAL_YEARS
    os.makedirs(DATA_DIR, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    ok, fail = [], []

    for c in companies:
        try:
            org_id = _org_id(c["code"], session)
            if not org_id:
                print(f"[dl] {c['name']} 查不到 orgId")
                fail.append(c["name"])
                continue
            for fiscal in years:
                out_path = os.path.join(DATA_DIR, f"{c['name']}_{c['code']}_{fiscal}年报.pdf")
                if os.path.exists(out_path) and not force:
                    print(f"[dl] 已存在，跳过：{os.path.basename(out_path)}")
                    ok.append(out_path)
                    continue
                publish_year = fiscal + 1
                anns = _announcements(c["code"], org_id, c["market"], publish_year, session)
                hits = pick_annual(anns, fiscal)
                if not hits:
                    print(f"[dl] {c['name']} {fiscal} 年报未找到（披露年 {publish_year}）")
                    fail.append(f"{c['name']}-{fiscal}")
                    continue
                ann = hits[0]
                url = STATIC + ann["adjunctUrl"]
                print(f"[dl] {c['name']} {fiscal} 年报 <- {ann.get('announcementTitle')}")
                with session.get(url, headers=HEADERS, timeout=300, stream=True) as r:
                    r.raise_for_status()
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(65536):
                            f.write(chunk)
                size = os.path.getsize(out_path)
                print(f"[dl] 已存 {os.path.basename(out_path)}（{size/1024/1024:.1f} MB）")
                ok.append(out_path)
                time.sleep(1)
        except Exception as e:
            print(f"[dl] {c['name']} 失败：{e}")
            fail.append(c["name"])
        time.sleep(1)
    print(f"[dl] 合计成功 {len(ok)}，失败 {len(fail)} {fail}")
    return ok, fail


if __name__ == "__main__":
    download_reports()
