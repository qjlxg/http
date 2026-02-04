import requests
import re
import os
import time
import base64
from datetime import datetime

# 1. 扩大正则匹配范围
# 匹配订阅链接、Base64 字符串以及可能的配置文件
SUB_PATTERN = r'https?://[^\s^"\'\(\)]+/api/v1/client/subscribe\?token=[a-zA-Z0-9]+'
BASE64_PATTERN = r'^[a-zA-Z0-9+/=]{50,}$' # 匹配长串 Base64

# 2. 深度矿场列表
# 包含订阅转换器后端、公开的配置收集站等
SOURCES = [
    "https://t.me/s/v2ray_free_conf",
    "https://t.me/s/V2ray_Free_Conf",
    "https://t.me/s/SSR_V2RAY_Clash",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    # 增加一些已知的公开订阅池接口（示例，需根据实际寻找）
    "https://sub.xeton.dev/", 
]

def decode_base64(text):
    """尝试解码 Base64 并提取链接"""
    try:
        decoded = base64.b64decode(text).decode('utf-8')
        return re.findall(SUB_PATTERN, decoded)
    except:
        return []

def fetch_content(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        # 增加对 raw 链接和普通页面的处理
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.text
    except:
        pass
    return ""

def main():
    all_found = set()
    print(f"[{datetime.now()}] 🛠️ 启动深度扫描收割模式...")

    for url in SOURCES:
        print(f"📡 扫描源: {url}")
        content = fetch_content(url)
        if not content: continue

        # 模式1：直接提取
        links = re.findall(SUB_PATTERN, content)
        all_found.update(links)

        # 模式2：对可能的 Base64 块进行尝试
        # 针对 GitHub 上的那种单行大文件
        if len(content) > 100 and " " not in content:
            links_from_b64 = decode_base64(content)
            all_found.update(links_from_b64)

        print(f"   ✨ 累计捕获: {len(all_found)}")
        time.sleep(0.5)

    # 结果保存
    os.makedirs("results", exist_ok=True)
    final_list = sorted(list(all_found))

    with open("results/subscriptions.txt", "w", encoding="utf-8") as f:
        f.write(f"# 深度采集时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Shanghai)\n")
        f.write(f"# 捕获总数: {len(final_list)}\n\n")
        for l in final_list:
            f.write(l + "\n")

    print(f"\n✅ 完成！最终捕获: {len(final_list)}。即使结果为 0，说明源需要更新。")

if __name__ == "__main__":
    main()
