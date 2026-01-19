import requests
import base64
import yaml
import os
import csv
from datetime import datetime
import urllib3

# 禁用不安全请求警告（针对某些自签名证书域名）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'

def get_content(url):
    """尝试通过 https 和 http 获取内容"""
    url = url.strip()
    if not url: return None, None
    
    clean_url = url.replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        target = f"{protocol}{clean_url}"
        try:
            response = requests.get(target, timeout=15, verify=False)
            if response.status_code == 200:
                return response.text, protocol
        except Exception:
            continue
    return None, None

def parse_nodes(content):
    """解析内容，支持 Base64, YAML 和明文"""
    nodes = set()
    if not content:
        return nodes

    # 1. 尝试解析 YAML
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict) and 'proxies' in data:
            for p in data['proxies']:
                # 简单处理：将proxy对象转回字符串或标识，根据需求可调
                nodes.add(str(p))
            return nodes
    except:
        pass

    # 2. 尝试 Base64 解码
    try:
        # 处理可能的换行和填充
        b64_str = content.replace('\r', '').replace('\n', '')
        missing_padding = len(b64_str) % 4
        if missing_padding:
            b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        nodes.update(decoded.splitlines())
    except:
        # 3. 视为明文处理
        nodes.update(content.splitlines())
    
    return {n.strip() for n in nodes if n.strip() and not n.startswith('#')}

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}")
        return

    all_nodes_global = set()
    stats_data = [] # 用于存储CSV数据
    
    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    current_month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(current_month_dir, exist_ok=True)

    for url in urls:
        content, used_protocol = get_content(url)
        if content:
            nodes = parse_nodes(content)
            count = len(nodes)
            all_nodes_global.update(nodes)
            stats_data.append([url, used_protocol, count, "Success"])
            print(f"域名 {url} 抓取成功: 得到 {count} 个节点")
        else:
            stats_data.append([url, "None", 0, "Failed"])
            print(f"域名 {url} 抓取失败")

    # 保存节点汇总文件
    node_filename = f"fetch_nodes_{timestamp}.txt"
    node_file_path = os.path.join(current_month_dir, node_filename)
    with open(node_file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(all_nodes_global)))

    # 保存统计 CSV 文件
    csv_filename = f"fetch_nodes_{timestamp}.csv"
    csv_file_path = os.path.join(current_month_dir, csv_filename)
    with open(csv_file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Domain', 'Protocol', 'NodeCount', 'Status'])
        writer.writerows(stats_data)
        writer.writerow([])
        writer.writerow(['TOTAL UNIQUE NODES', '', len(all_nodes_global), ''])

    print(f"处理完成。总去重节点: {len(all_nodes_global)}")

if __name__ == "__main__":
    main()
