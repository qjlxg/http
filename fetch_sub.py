import requests
import re
import os
import urllib.parse
import random
import time
from datetime import datetime

# 1. 筛选出的最强 SearXNG 实例 (来自你提供的实时数据)
SEARCH_INSTANCES = [
    "https://searxng.site/search",
    "https://searx.tiekoetter.com/search",
    "https://searx.rhscz.eu/search",
    "https://find.xenorio.xyz/search",
    "https://search.indst.eu/search",
    "https://searx.dresden.network/search",
    "https://paulgo.io/search",
    "https://searx.perennialte.ch/search"
]

# 2. 搜索关键词 (Dorks)
DORKS = [
    'inurl:"/api/v1/client/subscribe?token="',
    '"/api/v1/client/subscribe?token=" site:pastebin.com',
    '"/api/v1/client/subscribe?token=" site:t.me',
    '"/api/v1/client/subscribe?token=" site:github.com'
]

# 3. 订阅链接正则
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]{16,32}'

def fetch_from_instance(instance, query):
    encoded_query = urllib.parse.quote(query)
    # 强制请求 Google 引擎结果，很多实例默认不开启 Google
    url = f"{instance}?q={encoded_query}&engines=google,bing,duckduckgo&format=json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # 使用 json 格式获取结果通常比解析 HTML 更稳定
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            # 直接在返回的文本中搜索正则
            links = re.findall(SUB_PATTERN, response.text)
            return set(links)
    except:
        pass
    return set()

def main():
    all_found = set()
    print(f"[{datetime.now()}] 🚀 正在利用实时优质实例进行收割...")

    for dork in DORKS:
        # 每个 Dork 随机选 3 个实例尝试，增加成功率并防止被封
        selected_instances = random.sample(SEARCH_INSTANCES, 3)
        for ins in selected_instances:
            print(f"🔍 正在使用 [{ins}] 搜索: {dork}")
            links = fetch_from_instance(ins, dork)
            if links:
                print(f"   ✨ 发现 {len(links)} 条链接!")
                all_found.update(links)
            time.sleep(1) # 稍微停顿

    # 保存结果
    os.makedirs("results", exist_ok=True)
    file_path = "results/subscriptions.txt"
    
    # 过滤掉重复和已知的测试链接
    final_list = sorted([l for l in all_found if "example.com" not in l])

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"# 采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Shanghai)\n")
        f.write(f"# 资源来源: SearXNG Cluster (High Uptime Instances)\n")
        f.write(f"# 有效链接总数: {len(final_list)}\n\n")
        for link in final_list:
            f.write(link + "\n")

    print(f"\n✅ 任务完成！共捕获 {len(final_list)} 条有效订阅。")

if __name__ == "__main__":
    main()
