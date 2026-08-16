import requests
import concurrent.futures
import csv
import time
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 输入文件：每行一个域名
INPUT_FILE = "domains.txt"

# 输出文件
OUTPUT_FILE = "result.csv"

# 并发数
MAX_WORKERS = 20

# 请求超时时间
TIMEOUT = 10

# 重试次数
RETRIES = 2

# ============================================================
# RDAP 服务器
# ============================================================

RDAP_SERVERS = {
    "com": "https://rdap.verisign.com/com/v1/domain/",
    "net": "https://rdap.verisign.com/net/v1/domain/",
    "org": "https://rdap.publicinterestregistry.org/rdap/domain/",
    "io": "https://rdap.identitydigital.services/rdap/domain/",
    "ai": "https://rdap.identitydigital.services/rdap/domain/",
    "dev": "https://rdap.identitydigital.services/rdap/domain/",
    "app": "https://rdap.identitydigital.services/rdap/domain/",
    "xyz": "https://rdap.nic.xyz/domain/",
}

# ============================================================
# Session
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "DomainChecker/1.0",
    "Accept": "application/rdap+json, application/json",
})


# ============================================================
# 判断域名后缀
# ============================================================

def get_tld(domain):
    domain = domain.lower().strip().rstrip(".")

    if "." not in domain:
        return None

    return domain.rsplit(".", 1)[1]


# ============================================================
# 查询单个域名
# ============================================================

def check_domain(domain):

    domain = domain.strip().lower().rstrip(".")

    if not domain:
        return None

    tld = get_tld(domain)

    if not tld:
        return {
            "domain": domain,
            "status": "invalid",
            "http_status": "",
        }

    base_url = RDAP_SERVERS.get(tld)

    if not base_url:
        return {
            "domain": domain,
            "status": "unsupported_tld",
            "http_status": "",
        }

    url = base_url + domain

    for attempt in range(RETRIES + 1):

        try:

            response = session.get(
                url,
                timeout=TIMEOUT
            )

            # ------------------------------------------------
            # 200 = 已注册
            # 404 = RDAP 找不到该域名，通常表示未注册
            # ------------------------------------------------

            if response.status_code == 200:

                try:
                    data = response.json()
                    events = data.get("events", [])

                    registration_date = ""

                    for event in events:
                        if event.get("eventAction") == "registration":
                            registration_date = event.get(
                                "eventDate",
                                ""
                            )

                    return {
                        "domain": domain,
                        "status": "registered",
                        "http_status": 200,
                        "registration_date": registration_date,
                    }

                except Exception:

                    return {
                        "domain": domain,
                        "status": "registered",
                        "http_status": 200,
                        "registration_date": "",
                    }

            elif response.status_code == 404:

                return {
                    "domain": domain,
                    "status": "available",
                    "http_status": 404,
                    "registration_date": "",
                }

            elif response.status_code == 429:

                # Too Many Requests
                time.sleep(2 ** attempt)

            else:

                return {
                    "domain": domain,
                    "status": f"http_{response.status_code}",
                    "http_status": response.status_code,
                    "registration_date": "",
                }

        except requests.RequestException:

            if attempt < RETRIES:
                time.sleep(1)

    return {
        "domain": domain,
        "status": "error",
        "http_status": "",
        "registration_date": "",
    }


# ============================================================
# 读取域名
# ============================================================

def load_domains(filename):

    path = Path(filename)

    if not path.exists():

        print(f"找不到输入文件：{filename}")

        print("请创建 domains.txt，例如：")
        print()
        print("qualia.com")
        print("qualio.com")
        print("qualiva.com")
        print("qualivo.com")

        return []

    domains = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            domain = line.strip()

            if domain:
                domains.append(domain)

    # 去重
    domains = list(dict.fromkeys(domains))

    return domains


# ============================================================
# 主程序
# ============================================================

def main():

    domains = load_domains(INPUT_FILE)

    if not domains:
        return

    print("=" * 60)
    print("批量域名查询器")
    print("=" * 60)

    print(f"域名数量：{len(domains)}")
    print(f"并发数量：{MAX_WORKERS}")
    print()

    results = []

    completed = 0
    total = len(domains)

    start_time = time.time()

    # --------------------------------------------------------
    # 并发查询
    # --------------------------------------------------------

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(check_domain, domain): domain
            for domain in domains
        }

        for future in concurrent.futures.as_completed(
            future_map
        ):

            domain = future_map[future]

            try:
                result = future.result()

            except Exception as e:

                result = {
                    "domain": domain,
                    "status": "error",
                    "http_status": "",
                    "registration_date": "",
                }

            results.append(result)

            completed += 1

            if not result:
                raise Exception("The result is none")

            status = result["status"]

            print(
                f"[{completed}/{total}] "
                f"{domain:<30} "
                f"{status}"
            )

    # --------------------------------------------------------
    # 保存 CSV
    # --------------------------------------------------------

    results.sort(
        key=lambda x: x["domain"]
    )

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "status",
                "http_status",
                "registration_date",
            ]
        )

        writer.writeheader()
        writer.writerows(results)

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    available = sum(
        1
        for r in results
        if r["status"] == "available"
    )

    registered = sum(
        1
        for r in results
        if r["status"] == "registered"
    )

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("查询完成")
    print("=" * 60)

    print(f"总数：      {total}")
    print(f"可注册：    {available}")
    print(f"已注册：    {registered}")
    print(f"耗时：      {elapsed:.2f} 秒")
    print()
    print(f"结果已保存到：{OUTPUT_FILE}")


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    main()