import requests
import os
import concurrent.futures
from collections import deque

# 配置
INPUT_FILE = 'duplicate.txt'
OUTPUT_FILE = 'scan_alist.txt'
MAX_THREADS = 15  # 降低一点线程数，提高稳定性
TIMEOUT = 5       
MAX_DEPTH = 10    # 限制最大扫描深度，防止死循环

def get_alist_list(base_url, path="/"):
    """调用 AList V3 API 获取文件列表"""
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    payload = {"path": path, "password": "", "page": 1, "per_page": 0}
    try:
        # 增加 verify=False 忽略某些站点的 SSL 证书错误
        resp = requests.post(api_url, json=payload, timeout=TIMEOUT, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url):
    """使用队列迭代（广度优先）代替递归，防止递归溢出"""
    print(f"正在扫描: {url}")
    local_results = {}
    queue = deque([("/", 0)]) # (路径, 当前深度)
    visited_paths = {"/"}      # 防止某些站点循环引用

    while queue:
        current_path, depth = queue.popleft()
        
        if depth > MAX_DEPTH:
            continue

        items = get_alist_list(url, current_path)
        if not items:
            continue

        for item in items:
            name = item.get('name')
            is_dir = item.get('is_dir')
            # 处理路径拼接
            full_path = f"{current_path.rstrip('/')}/{name}"
            
            if is_dir:
                if full_path not in visited_paths:
                    visited_paths.add(full_path)
                    queue.append((full_path, depth + 1))
            else:
                _, ext = os.path.splitext(name)
                ext = ext.lower() if ext else ".no_ext"
                download_url = f"{url.rstrip('/')}/d{full_path}"
                
                if ext not in local_results:
                    local_results[ext] = []
                local_results[ext].append(f"{name} | {download_url}")
                
    return local_results

def main():
    # 忽略 SSL 警告
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        print("未找到 duplicate.txt")
        return

    with open(INPUT_FILE, 'r') as f:
        urls = [line.strip() for line in f if line.strip().startswith('http')]

    final_results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                thread_data = future.result()
                for ext, links in thread_data.items():
                    if ext not in final_results:
                        final_results[ext] = []
                    final_results[ext].extend(links)
            except Exception as e:
                print(f"任务执行出错: {e}")

    # 按扩展名保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for ext in sorted(final_results.keys()):
            f.write(f"\n[{ext}]\n")
            # 去重并排序
            unique_links = sorted(list(set(final_results[ext])))
            for line in unique_links:
                f.write(line + "\n")
    print(f"扫描完成，结果已保存至 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
