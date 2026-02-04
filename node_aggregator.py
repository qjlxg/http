import requests
import re
import os
import time
import socket
import json
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# --- 配置区 ---
GITHUB_TOKEN = os.getenv("MY_GITHUB_TOKEN")
OUTPUT_DIR = "results"
# 完善协议匹配正则，确保能抓取到带参数的复杂链接
NODE_PATTERN = r'(vmess|vless|ss|ssr|trojan|tuic|hysteria2|hysteria)://[^\s^"\'\(\)]+'
# 扩充黑名单，过滤掉更多垃圾节点
BAD_KEYWORDS = ['过期', '流量', '耗尽', '到期', '0GB', '剩余', '官网', '维护', '重置', '测试', '购买']

# 精品节点池（直接存放节点的文件地址）
RAW_NODE_SOURCES = [
    "https://raw.githubusercontent.com/vless-free/free/main/v2ray",
    "https://raw.githubusercontent.com/freefq/free/master/v2ray",
    "https://raw.githubusercontent.com/Pawdroid/Free-v2ray/main/v2ray.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/latest/all_export.txt",
    "https://raw.githubusercontent.com/mueiba/free-nodes/main/nodes.txt"
]

# GitHub 搜索 Dorks：锁定包含原始节点的文本文件
GITHUB_DORKS = [
    'extension:txt "vmess://"',
    'extension:txt "vless://"',
    'extension:txt "trojan://"',
    'extension:txt "hysteria2://"',
    'filename:nodes.txt "ss://"',
    'filename:sub.txt "vmess://"',
    'filename:README.md "更新时间" "vmess://"'
]

# --- 核心过滤逻辑 ---

def check_tcp_alive(node_url):
    """TCP 探测：确保节点服务器是通的"""
    try:
        host, port = None, None
        if node_url.startswith(('ss://', 'trojan://', 'vless://', 'ssr://', 'hysteria2://', 'hysteria://', 'tuic://')):
            # 兼容标准协议格式
            if '@' in node_url:
                part = node_url.split('@')[1].split('#')[0].split('?')[0]
                if ':' in part:
                    host, port = part.split(':')[0], int(part.split(':')[1])
        elif node_url.startswith('vmess://'):
            # 解码 vmess json 格式
            b64_data = node_url.replace('vmess://', '')
            b64_data += '=' * (-len(b64_data) % 4)
            data = json.loads(base64.b64decode(b64_data).decode('utf-8'))
            host, port = data['add'], int(data['port'])
        
        if host and port:
            # 建立物理连接测试，超时设为 1.5s 以过滤掉高延迟垃圾
            with socket.create_connection((host, port), timeout=1.5):
                return True
    except:
        pass
    return False

def get_github_raw_nodes():
    """利用 API 搜索包含原始节点的文件内容"""
    if not GITHUB_TOKEN: 
        print("⚠️ 警告: 未发现 MY_GITHUB_TOKEN，将跳过 GitHub API 搜索。")
        return set()
    
    found_nodes = set()
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.text-match+json"
    }
    
    for dork in GITHUB_DORKS:
        try:
            print(f"🔍 正在执行 Dork: {dork}")
            url = f"https://api.github.com/search/code?q={dork}&sort=indexed&order=desc"
            response = requests.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                items = response.json().get('items', [])
                for item in items:
                    raw_url = item['html_url'].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                    try:
                        content = requests.get(raw_url, timeout=10).text
                        nodes = re.findall(NODE_PATTERN, content)
                        found_nodes.update(nodes)
                    except: continue
            elif response.status_code == 403:
                print("🚫 API 速率受限，稍后继续...")
                time.sleep(10)
            
            time.sleep(3) # 遵守 API 调用频率
        except Exception as e:
            print(f"⚠️ 搜索任务中断: {e}")
    return found_nodes

def main():
    start_time = datetime.now()
    print(f"[{start_time}] 🛰️ 启动全网原始节点收割模式...")
    
    all_collected = set()

    # 1. 抓取已知精品节点池
    for src in RAW_NODE_SOURCES:
        print(f"📡 扫描精品源: {src}")
        try:
            content = requests.get(src, timeout=15).text
            nodes = re.findall(NODE_PATTERN, content)
            all_collected.update(nodes)
            print(f"   ✨ 发现 {len(nodes)} 个节点候选")
        except: pass

    # 2. 搜索 GitHub 上的隐藏节点文件
    all_collected.update(get_github_raw_nodes())

    # 3. 铁血清洗与 TCP 验证
    print(f"⚙️ 原始获取 {len(all_collected)} 条数据，开始活体检测...")
    
    def verify_node(node):
        # 排除黑名单关键词
        if any(word in node for word in BAD_KEYWORDS): return None
        # 探测存活，不通的直接扔掉
        if check_tcp_alive(node): return node
        return None

    # 并发 50 线程测速
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(verify_node, list(all_collected)))
        final_nodes = [r for r in results if r]

    # 4. 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(f"{OUTPUT_DIR}/nodes.txt", "w", encoding="utf-8") as f:
        # 去重并按照字典序排列
        unique_nodes = sorted(list(set(final_nodes)))
        f.write("\n".join(unique_nodes))

    print(f"✅ 完成！最终捕获真·活节点: {len(unique_nodes)} 个")
    print(f"📁 结果已保存至 {OUTPUT_DIR}/nodes.txt")
    print(f"⏱️ 总耗时: {datetime.now() - start_time}")

if __name__ == "__main__":
    main()
