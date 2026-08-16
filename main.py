import requests
import concurrent.futures
import csv
import time
import itertools
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 输入文件：每行一个域名
INPUT_FILE = "domains.txt"

# 输出文件
OUTPUT_FILE = "result.csv"

# 并发数
MAX_WORKERS = 40

# 请求超时时间
TIMEOUT = 10

# 重试次数
RETRIES = 2

# ============================================================
# 字符组与域名模板
# ============================================================

# domains.txt 里的每一行是一个"域名模板"：由字面文本和字符组引用组成。
# 模板里出现某个字符组的名字（区分大小写）时，它会被展开成该组的每一个
# 条目；展开后的所有具体域名都会被检查。不含任何字符组引用的行就是普通
# 域名，只检查一个。
#
# 展开后，如果某个词里没有点号（"."），它会被当成"裸名字"，程序会给它
# 拼上 RDAP_SERVERS 里的每一个后缀（tld）去检查。例如：
#   google     → google.com、google.net、google.org、google.io ...
# 词里已有 ".tld" 的则原样检查，不额外拼后缀。
#
# 可选组：把字符组引用用括号包起来，例如 (C) 或 (<A)，表示该组可以
# 省略（生成"没这个组"的域名，也生成"有这个组"的域名）。
#   orbio(CV).com → orbio.com、orbioba.com、orbiobe.com ...（含或略 CV）
#   <AorbB>.com   → 有 <A 和 B>：如 ioiorb.io 等
#                 → 也生成省略 <A 或 B> 的：如 orbio.com、iorb.com 等
#   注意：只有「空的条目列表」或「组条目全为空字符串」才等价于省略；
#   (C) 里的 C 是单字符组，会生成所有含 C 与不含 C 的组合。
#
# 字符组：一个名字 → 一组条目。
#   字符串  "bcdf..."       → 每个字符是一个条目（单字符）
#   列表    ["io", "ix"]    → 每个字符串是一个条目（多字符）

CHAR_GROUPS = {
    "SOFT":"lmnrwv",
    "FRICATIVE":"fsvzh",
    "STRONG":"kgxz",
    "BRAND":"bcdghjklmnprstvz",
    "SONORANTS":"lmnrwjy",
    "ONSET":"bcdfghjklmnpqrstvwz",


    "A":"abcdefghijklmnopqrstuvwxyz",
    "C": "bcdfghjklmnpqrstvwxyz",   # 辅音
    "V": "aeiou",                    # 元音
    "P": "ptkbdg",

    # -- 前缀组（多字符字符串）--
    "<": ["ae", "al", "el", "io", "ka", "la", "lu", "mi", "na", "ne", "no", "nu", "or", "ve", "vi", "vo", "ze", "neo", "nova", "lumi", "aura", "vero"],

    # -- 后缀组（多字符字符串）--
    ">": ["a", "e", "i", "o", "ia", "io", "ea", "is", "on", "en", "or", "ar", "er", "el", "al", "um", "us", "ova", "ora", "era", "ino", "iva", "ivo", "lia", "ria", "via", "neo"]
}

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
# 读取并展开域名模板
# ============================================================

def expand_template(template, groups):

    names = sorted(groups, key=len, reverse=True)

    tokens = []
    i = 0

    while i < len(template):

        matched = None
        optional = False
        matched_len = 0

        if i + 1 < len(template) and template[i] == "(":

            for name in names:
                if template.startswith("(" + name, i):
                    matched = name
                    optional = True
                    matched_len = len(name) + 1
                    break

        if matched is None:

            for name in names:
                if template.startswith(name, i):
                    matched = name
                    matched_len = len(name)
                    break

        if matched:

            entries = list(groups[matched])

            if optional:

                i += matched_len + 1

                if entries:
                    tokens.append(("group", matched, [""] + entries))

            else:

                i += matched_len

                if entries:
                    tokens.append(("group", matched, entries))

        else:

            if template[i] in "()":

                tokens.append(("literal", "", None))
                i += 1

            else:

                tokens.append(("literal", template[i], None))
                i += 1

    groups_found = [
        token
        for token in tokens
        if token[0] == "group"
    ]

    if not groups_found:
        return ["".join(name for kind, name, _ in tokens if kind == "literal")]

    entries_list = [entries for _, _, entries in groups_found]

    expanded = []

    for combo in itertools.product(*entries_list):

        it = iter(combo)

        word = "".join(
            next(it) if kind == "group" else name or ""
            for kind, name, _ in tokens
        )

        expanded.append(word)

    return expanded


def expand_tlds(word):

    if "." in word:
        return [word]

    return [f"{word}.{tld}" for tld in RDAP_SERVERS]


def load_domains(filename):

    path = Path(filename)

    if not path.exists():

        print(f"找不到输入文件：{filename}")

        print("请创建 domains.txt，例如：")
        print()
        print("orbioCV.com")
        print("qualia.com")

        return []

    domains = []

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            template = line.strip()

            if not template:
                continue

            expanded = expand_template(template, CHAR_GROUPS)

            for word in expanded:
                domains.extend(expand_tlds(word))

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

            if status == "available":

                print(
                    f"[{completed}/{total}] "
                    f"{domain:<30} "
                    f"{status}"
                )

    # --------------------------------------------------------
    # 保存 CSV（只写可注册的）
    # --------------------------------------------------------

    available_results = [
        r
        for r in results
        if r["status"] == "available"
    ]

    available_results.sort(
        key=lambda x: (len(x["domain"]), x["domain"])
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
        writer.writerows(available_results)

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