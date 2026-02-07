import requests
import os
import concurrent.futures

# 配置
INPUT_FILE = 'duplicate.txt'
OUTPUT_FILE = 'scan_alist.txt'
MAX_THREADS = 20  # 最大并行线程数
TIMEOUT = 5       # 每个请求超时时间（秒）

def get_alist_list(base_url, path="/"):
    """调用 AList V3 API 获取文件列表"""
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    payload = {"path": path, "password": "", "page": 1, "per_page": 0}
    try:
        resp = requests.post(api_url, json=payload, timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def scan_recursive(base_url, current_path, local_results):
    """递归扫描，结果存入当前线程的 local_results 字典"""
    items = get_alist_list(base_url, current_path)
    if not items:
        return

    for item in items:
        full_path = os.path.join(current_path, item['name']).replace("\\", "/")
        if item.get('is_dir'):
            scan_recursive(base_url, full_path, local_results)
        else:
            _, ext = os.path.splitext(item['name'])
            ext = ext.lower() if ext else ".no_ext"
            download_url = f"{base_url.rstrip('/')}/d{full_path}"
            if ext not in local_results:
                local_results[ext] = []
            local_results[ext].append(f"{item['name']} | {download_url}")

def process_url(url):
    """单个 URL 的处理逻辑，由线程池调用"""
    print(f"正在扫描: {url}")
    thread_data = {}
    scan_recursive(url, "/", thread_data)
    return thread_data

def main():
    if not os.path.exists(INPUT_FILE):
        return

    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip().startswith('http')]

    final_results = {}

    # 使用线程池并行运行
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            thread_data = future.result()
            # 合并各个线程的结果
            for ext, links in thread_data.items():
                if ext not in final_results:
                    final_results[ext] = []
                final_results[ext].extend(links)

    # 按扩展名保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for ext in sorted(final_results.keys()):
            f.write(f"\n[{ext}]\n")
            for line in sorted(final_results[ext]):
                f.write(line + "\n")
    print("扫描完成，结果已保存。")

if __name__ == "__main__":
    main()
