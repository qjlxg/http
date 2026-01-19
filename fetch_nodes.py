import requests
import base64
import yaml
import os
import csv
import urllib3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
INPUT_FILE = 'http.txt'
OUTPUT_BASE_DIR = 'nodes'
MAX_WORKERS = 100  # 并行线程数

def get_content(url):
    """尝试通过 https 和 http 获取内容"""
    url = url.strip()
    if not url: return None, None, 0
    
    clean_url = url.replace('https://', '').replace('http://', '')
    for protocol in ['https://', 'http://']:
        target = f"{protocol}{clean_url}"
        try:
            # 缩短超时时间以提高并行效率
            response = requests.get(target, timeout=10, verify=False)
            if response.status_code == 200:
                return response.text, protocol, response.status_code
        except Exception:
            continue
    return None, None, "Error"

def parse_nodes(content):
    """解析内容，支持 Base64, YAML 和明文"""
    nodes = set()
    if not content: return nodes
    try:
        # YAML 尝试
        data = yaml.safe_load(content)
        if isinstance(data, dict) and 'proxies' in data:
            return {str(p).strip() for p in data['proxies']}
    except: pass
    try:
        # Base64 尝试
        b64_str = content.replace('\r', '').replace('\n', '').strip()
        missing_padding = len(b64_str) % 4
        if missing_padding: b64_str += '=' * (4 - missing_padding)
        decoded = base64.b64decode(b64_str).decode('utf-8')
        nodes.update(decoded.splitlines())
    except:
        # 明文
        nodes.update(content.splitlines())
    return {n.strip() for n in nodes if n.strip() and not n.startswith('#')}

def process_url(url):
    """单个URL的处理逻辑，供线程调用"""
    content, protocol, status = get_content(url)
    nodes = parse_nodes(content) if content else set()
    return {
        'url': url,
        'protocol': protocol or "None",
        'nodes': nodes,
        'count': len(nodes),
        'status': "Success" if content else f"Failed({status})"
    }

def main():
    if not os.path.exists(INPUT_FILE):
        print("错误: 找不到 http.txt")
        return

    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip()]

    all_nodes_global = set()
    stats_data = []
    
    print(f"开始并行处理 {len(urls)} 个域名...")

    # 使用线程池进行并发请求
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        
        for future in as_completed(future_to_url):
            result = future.result()
            all_nodes_global.update(result['nodes'])
            stats_data.append([result['url'], result['protocol'], result['count'], result['status']])
            print(f"[{result['status']}] {result['url']} -> 找到 {result['count']} 个节点")

    # 结果归档逻辑
    now = datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    current_month_dir = os.path.join(OUTPUT_BASE_DIR, now.strftime('%Y-%m'))
    os.makedirs(current_month_dir, exist_ok=True)

    # 保存 TXT
    node_path = os.path.join(current_month_dir, f"fetch_nodes_{timestamp}.txt")
    with open(node_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(all_nodes_global)))

    # 保存 CSV
    csv_path = os.path.join(current_month_dir, f"fetch_nodes_{timestamp}.csv")
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Domain', 'Protocol', 'NodeCount', 'Status'])
        writer.writerows(stats_data)
        writer.writerow(['TOTAL UNIQUE', '-', len(all_nodes_global), '-'])

    print(f"\n任务完成！总去重节点数: {len(all_nodes_global)}")

if __name__ == "__main__":
    main()
