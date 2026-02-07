import requests
import os
import concurrent.futures
from collections import deque

# 配置
INPUT_FILE = 'duplicate.txt'
OUTPUT_FILE = 'scan_alist.txt'
MAX_THREADS = 15  
TIMEOUT = 5       
MAX_DEPTH = 10    

def get_alist_list(base_url, path="/"):
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    payload = {"path": path, "password": "", "page": 1, "per_page": 0}
    try:
        # 忽略 SSL 证书错误
        resp = requests.post(api_url, json=payload, timeout=TIMEOUT, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url):
    """扫描单个站点"""
    local_data = [] # 存储结构: (ext, filename, download_url)
    queue = deque([("/", 0)]) 
    visited_paths = {"/"}      

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
            full_path = f"{current_path.rstrip('/')}/{name}"
            
            if is_dir:
                if full_path not in visited_paths:
                    visited_paths.add(full_path)
                    queue.append((full_path, depth + 1))
            else:
                _, ext = os.path.splitext(name)
                ext = ext.lower() if ext else ".no_ext"
                download_url = f"{url.rstrip('/')}/d{full_path}"
                
                # 记录该文件的元组，用于后续去重
                local_data.append((ext, name, download_url))
                
    return local_data

def main():
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        return

    with open(INPUT_FILE, 'r') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    final_registry = set() # 使用集合记录 (文件名, 下载链接) 的唯一组合

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                # 线程返回的是该站点下的所有文件列表
                site_files = future.result()
                for item in site_files:
                    # 只有文件名和下载链接完全一样才会被 set 去重
                    final_registry.add(item) 
            except Exception as e:
                print(f"站点扫描异常: {e}")

    # 将结果按扩展名组织归类
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map:
            ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    # 写入文件
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# 扫描完成时间: {time_now()}\n")
        for ext in sorted(ext_map.keys()):
            f.write(f"\n[{ext}]\n")
            # 同一后缀下的文件按名称排序
            for line in sorted(ext_map[ext]):
                f.write(line + "\n")

def time_now():
    from datetime import datetime
    import pytz
    tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

if __name__ == "__main__":
    main()
