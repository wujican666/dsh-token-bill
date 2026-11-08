#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Token 总账 —— 把 DeepSeek Harness 的会话日志算成一张离线网页账单。

特点：
  * 全在本机算：解压 ~/.dsh/sessions 里的日志，读每次模型请求的 usage，不联网、不上传。
  * 不挑平台：日志里记了 provider / model，谁免费谁自费由规则判定，换学校、换平台都能用。
  * 零第三方依赖：Python 3.14+ 用标准库 compression.zstd；3.12/3.13 用 pip 的 zstandard 兜底。

判定规则（见 CLASSIFY 一节）：
  1) 命中 free_providers 关键词            -> 免费（白嫖）
  2) 命中 paid_providers 关键词            -> 自费
  3) 端点长相像学校 / 自建（.edu、univ、campus、localhost、ollama…）-> 免费（自动判定）
  4) 以上都不中                            -> 待确认（不算进任何一边，页面上单独列出让你拍板）

用法：
  python token_bill.py                 # 起本地小页面（推荐）：认不出的平台点按钮就能改
  python token_bill.py --static        # 只生成一张静态网页（老方式）
  python token_bill.py --print         # 只在控制台看摘要
  python token_bill.py --doctor        # 自检：日志在哪、格式、每个 provider 怎么判定的
  python token_bill.py --json          # 机器可读
  python token_bill.py --init-config   # 按你本机数据生成一份配置文件
  python token_bill.py --demo          # 假数据演示页
"""

import argparse
import base64
import datetime as _dt
import html as _html
import io
import json
import os
import re
import subprocess
import sys

__version__ = "1.3.0"

CONFIG_NAME = "token-bill.config.json"
DEFAULT_OUT = "token-账单.html"
LINK = "https://github.com/wujican666/dsh-token-bill"

# 可选图标（assets/icons/<name>.ico|.png），只在网页上选，用于桌面快捷方式
ICON_CHOICES = (
    ("bill", "收据"),
    ("campus", "学士帽"),
    ("coin", "金币"),
    ("chart", "柱状图"),
    ("whale", "小鲸鱼"),
)
DEFAULT_ICON = "coin"
SHORTCUT_NAME = "DSH Token 总账.lnk"

# ---------------------------------------------------------------- 判定规则 --

# 中国高校英文缩写：很多学校自建 API 的 provider 就叫这个（sjtucs、zju-llm 这种）
# 只在 provider 字段里模糊匹配；故意不收 mit/hit/bit 这类会撞普通单词的缩写。
UNIV_CODES = (
    "csu", "zju", "tju", "nju", "scu", "fdu", "xmu", "bnu", "whu", "lzu", "jlu", "seu",
    "neu", "hdu", "ustc", "sjtu", "hust", "nuaa", "buaa", "cqu", "swu", "xjtu", "nwpu",
    "nwafu", "dlut", "hrbeu", "ncepu", "cug", "upc", "sdut", "qdu", "hfut", "ahu", "zzu",
    "henu", "hbnu", "ccnu", "ecnu", "snnu", "shnu", "gzhu", "szu", "jnu", "fzu", "gdut",
    "ynu", "gzu", "swjtu", "cdut", "usst", "ecust", "sues", "shu", "tongji", "nankai",
    "ruc", "bnu", "cau", "pku", "tsinghua", "thu", "ucas", "cqupt", "cqut", "hznu",
    "zjnu", "hdu", "nbu", "wzu", "hznu", "sdu", "sdnu", "qlnu", "ytu", "sdust",
)

# 免费的：学校/校园网关、公司内网网关、免费模型、本机自建
DEFAULT_FREE_KEYWORDS = [
    "csu", "glm", "edu", "ac.cn", "ac.uk", "univ", "university", "college",
    "campus", "校内", "学校", "校园", "公司", "集团", "内网",
    "ollama", "lmstudio", "lm studio", "localhost", "127.0.0.1", "vllm", "llama.cpp", "llamacpp",
]

# 自费的：商业平台/官方付费通道
DEFAULT_PAID_KEYWORDS = [
    "deepseek-account", "deepseek-official", "api.deepseek.com", "platform.deepseek.com",
    "aliyun", "bailian", "百炼", "dashscope", "siliconflow", "openrouter", "moonshot",
    "kimi", "zhipu", "bigmodel", "openai", "anthropic", "claude", "gemini",
    "generativelanguage", "xai", "grok", "groq", "together", "fireworks", "volcengine",
    "volces", "qianfan", "baidu", "hunyuan", "tencent", "minimax", "stepfun", "mistral",
    "cohere", "perplexity", "nvidia", "azure", "bedrock", "vertex", "replicate",
    "modelscope", "302.ai", "novita", "deepinfra", "hyperbolic", "cerebras", "sambanova",
    "openrouter.ai", "poe.com", "chatglm", "spark", "xfyun", "iflytek",
]

# 都没命中时，看端点长相：像学校 / 像公司内网 / 本机自建，都算"免费额度"（页面上标明是自动判定）
SCHOOL_PATTERN = re.compile(
    r"(\.edu|\.ac\.|\.sch\.|univ|college|campus|校内|学校|校园"
    r"|chat\.\w+\.(cn|com|net)|\.edu\.cn)",
    re.I,
)
CORP_PATTERN = re.compile(
    r"(internal|intranet|corp|company|gateway|proxy|\.internal\b|\.corp\b|\.lan\b"
    r"|公司|集团|内网|oa-|sg-|ai\.\w+\.(internal|corp|cn))",
    re.I,
)
LOCAL_PATTERN = re.compile(
    r"(localhost|127\.0\.0\.1|0\.0\.0\.0|::1|\.local\b|192\.168\.|10\.\d{1,3}\."
    r"|172\.(1[6-9]|2\d|3[01])\.|ollama|vllm|lmstudio|llama\.cpp)",
    re.I,
)

FREE, PAID, UNKNOWN = "FREE", "PAID", "UNKNOWN"
CLASS_LABEL = {FREE: "免费额度", PAID: "自费", UNKNOWN: "待确认"}


def base_dir():
    """冻结成 exe 时用 exe 所在目录，否则用脚本所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def default_dsh_home():
    env = os.environ.get("DSH_HOME")
    if env and os.path.isdir(env):
        return env
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, ".dsh"), os.path.join(home, "dsh")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(home, ".dsh")


def load_config(path=None):
    cfg = {
        "dsh_home": "",
        "output": DEFAULT_OUT,
        "free_providers": list(DEFAULT_FREE_KEYWORDS),
        "paid_providers": list(DEFAULT_PAID_KEYWORDS),
        "unknown_class": "skip",
        "icon": DEFAULT_ICON,
        "list_price": {"input": 2.0, "cache_read": 0.2, "output": 3.0},
        "bill_rate": 0.0401,
        "paid_actual_cny": None,
        "paid_actual_date": "",
    }
    p = path or os.path.join(base_dir(), CONFIG_NAME)
    if os.path.isfile(p):
        try:
            with io.open(p, "r", encoding="utf-8") as f:
                user = json.load(f)
            if isinstance(user, dict):
                for k, v in user.items():
                    if k in ("free_providers", "paid_providers") and isinstance(v, list):
                        cfg[k] = [str(x) for x in v]
                    elif k == "list_price" and isinstance(v, dict):
                        cfg["list_price"].update(v)
                    else:
                        cfg[k] = v
        except Exception as e:  # 配置写坏了也不能让账单跑不出来
            cfg["_config_error"] = "%s: %s" % (p, e)
    cfg["_config_path"] = p
    return cfg


def write_example_config(path, free=None, paid=None):
    data = {
        "dsh_home": "",
        "output": DEFAULT_OUT,
        "free_providers": free if free else list(DEFAULT_FREE_KEYWORDS),
        "paid_providers": paid if paid else list(DEFAULT_PAID_KEYWORDS),
        "unknown_class": "skip",
        "_unknown_class说明": "认不出来的 provider 怎么处理：skip=单独列出来（默认）/ free=当免费额度 / paid=当自费",
        "icon": DEFAULT_ICON,
        "_icon说明": "网页上选的图标（bill/campus/coin/chart/whale），只用于桌面快捷方式",
        "list_price": {"input": 2.0, "cache_read": 0.2, "output": 3.0},
        "bill_rate": 0.0401,
        "paid_actual_cny": None,
        "paid_actual_date": "",
    }
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


# ------------------------------------------------------------------ 读日志 --

ZSTD_SUFFIXES = (".zstd", ".zst")
PLAIN_SUFFIXES = (".jsonl", ".json", ".log", ".txt")


def zstd_lines(path):
    """按行读 zstd 压缩的日志；Python < 3.14 时回退到 pip 的 zstandard。"""
    try:
        from compression import zstd  # Python 3.14+ 标准库
        with open(path, "rb") as f:
            data = f.read()
        raw = zstd.decompress(data) if hasattr(zstd, "decompress") else None
        if raw is None:  # 3.14 的模块接口
            d = zstd.ZstdDecompressor()
            raw = d.decompress(data)
        for line in raw.decode("utf-8", "replace").splitlines():
            yield line
        return
    except ImportError:
        pass
    try:
        import zstandard  # pip install zstandard（Python 3.12/3.13）
    except ImportError:
        raise SystemExit(
            "这台机器的 Python 读不了 .zstd 日志。\n"
            "办法一：用 Python 3.14+ 跑（标准库自带 zstd）。\n"
            "办法二：pip install zstandard 后重试。"
        )
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as f:
        with dctx.stream_reader(f) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
            for line in text:
                yield line.rstrip("\n")


def iter_lines(path):
    low = path.lower()
    if low.endswith(ZSTD_SUFFIXES):
        for line in zstd_lines(path):
            yield line
    else:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line.rstrip("\n")


def find_logs(dsh_home):
    """找会话日志：sessions 子目录优先，找不到就看 DSH 目录本身。

    兼容 .jsonl.zstd / .jsonl.zst / .jsonl / .zstd 几种存法（不同 DSH 版本不一样）。
    """
    roots = [os.path.join(dsh_home, "sessions"), dsh_home]
    searched = []
    for root in roots:
        searched.append(root)
        if not os.path.isdir(root):
            continue
        hits = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
            for fn in filenames:
                low = fn.lower()
                if "session" not in low:
                    continue
                if low.endswith(ZSTD_SUFFIXES) or low.endswith(PLAIN_SUFFIXES):
                    hits.append(os.path.join(dirpath, fn))
        if hits:
            return hits, searched
    return [], searched


def _num(*vals):
    for v in vals:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            return int(v.strip())
    return 0


def parse_usage(u):
    """从 usage 里取四类 token。兼容 DSH 原生字段和 OpenAI 风格的字段名。"""
    if not isinstance(u, dict):
        return None
    native = any(k in u for k in ("inputTokens", "input_tokens", "outputTokens", "output_tokens"))
    prompt = _num(u.get("inputTokens"), u.get("input_tokens"))
    completion = _num(u.get("outputTokens"), u.get("output_tokens"))
    cache_r = _num(u.get("cacheReadTokens"), u.get("cache_read_tokens"))
    cache_w = _num(u.get("cacheWriteTokens"), u.get("cache_write_tokens"))
    if not native:  # OpenAI 风格：prompt_tokens 含缓存，别重复计
        prompt = _num(u.get("prompt_tokens"), u.get("promptTokens"))
        completion = _num(u.get("completion_tokens"), u.get("completionTokens"))
        details = u.get("prompt_tokens_details") or u.get("promptTokensDetails") or {}
        cached = 0
        if isinstance(details, dict):
            cached = _num(details.get("cached_tokens"), details.get("cachedTokens"))
            prompt = max(0, prompt - cached)
        cache_r = cached
        cache_w = 0
    total = prompt + completion + cache_r + cache_w
    if total <= 0 and not any((prompt, completion, cache_r, cache_w)):
        return None
    return {"input": prompt, "output": completion, "cache_read": cache_r, "cache_write": cache_w}


def classify_detail(provider, model, free_kw, paid_kw):
    """返回 (档位, 判定依据)。免费优先，其次自费，再看端点长相，最后待确认。

    判定顺序就是"普适度"的来源：名字不认识的平台，只要端点长得像学校/公司/内网，
    也能自动归到免费额度那一档，不会给你算成自费。
    """
    p = (provider or "").strip()
    m = (model or "").strip()
    if p.lower() in ("", "?", "none", "unknown") and m.lower() in ("", "?", "none", "unknown"):
        return UNKNOWN, "日志里没记 provider/model"
    text = ("%s %s" % (p, m)).lower()
    for kw in free_kw:
        kw = str(kw).strip().lower()
        if kw and kw in text:
            return FREE, "命中免费关键词 “%s”" % kw
    for kw in paid_kw:
        kw = str(kw).strip().lower()
        if kw and kw in text:
            return PAID, "命中自费关键词 “%s”" % kw
    pl = p.lower()
    for code in UNIV_CODES:
        if code in pl:
            return FREE, "provider 名像高校自建 API “%s”（自动判定）" % code
    if LOCAL_PATTERN.search(text):
        return FREE, "本机/内网自建端点（自动判定）"
    if SCHOOL_PATTERN.search(text):
        return FREE, "端点像学校校园网关（自动判定）"
    if CORP_PATTERN.search(text):
        return FREE, "端点像公司/单位内网网关（自动判定）"
    return UNKNOWN, "认不出来，等你拍板"


def add_money(cfg, tokens, cls):
    """按牌价折算金额。免费这边不算缓存读价（校园 API 一般没有缓存计费）。"""
    lp = cfg.get("list_price") or {}
    pin = float(lp.get("input", 2.0))
    pout = float(lp.get("output", 3.0))
    pcr = float(lp.get("cache_read", 0.2))
    if cls == FREE:
        cny = tokens["input"] / 1e6 * pin + tokens["output"] / 1e6 * pout
    else:
        cny = (tokens["input"] / 1e6 * pin + tokens["cache_read"] / 1e6 * pcr
               + tokens["output"] / 1e6 * pout)
    return cny


# -------------------------------------------------------------------- 统计 --

def day_of(ev, path):
    """把事件时间归到某一天。兼容 ISO 字符串、秒/毫秒时间戳（DSH 用的是时间戳）。"""
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    for ts in (ev.get("timestamp"), ev.get("time"), ev.get("createdAt"), ev.get("created_at"),
               data.get("timestamp"), data.get("createdAt"), data.get("created_at"),
               data.get("time")):
        if ts in (None, ""):
            continue
        s = str(ts).strip()
        m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            return m.group(1)
        if s.replace(".", "", 1).isdigit():
            v = float(s)
            while v > 4e9:  # 毫秒（甚至微秒）
                v /= 1000.0
            if 9e8 < v < 4e9:  # 2000-01-01 ~ 2096-11-20
                try:
                    return _dt.datetime.fromtimestamp(v).strftime("%Y-%m-%d")
                except Exception:
                    pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else "未知日期"


def collect(dsh_home, cfg):
    free_kw = cfg.get("free_providers") or DEFAULT_FREE_KEYWORDS
    paid_kw = cfg.get("paid_providers") or DEFAULT_PAID_KEYWORDS
    unknown_default = {"free": FREE, "paid": PAID}.get(
        str(cfg.get("unknown_class") or "skip").strip().lower(), UNKNOWN)

    logs, searched = find_logs(dsh_home)
    r = {
        "dsh_home": dsh_home,
        "searched": searched,
        "logs": len(logs),
        "log_zstd": sum(1 for p in logs if p.lower().endswith(ZSTD_SUFFIXES)),
        "log_plain": sum(1 for p in logs if not p.lower().endswith(ZSTD_SUFFIXES)),
        "sessions": 0,
        "requests": 0,
        "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
        "by_model": {},
        "by_day": {},
        "by_class": {FREE: 0, PAID: 0, UNKNOWN: 0},
        "by_class_tokens": {FREE: 0, PAID: 0, UNKNOWN: 0},
        "providers": {},
        "errors": [],
    }

    for path in logs:
        provider, model = "?", "?"
        got = False
        try:
            for line in iter_lines(path):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                etype = ev.get("type") or ev.get("event") or ""
                data = ev.get("data") or {}
                if not isinstance(data, dict):
                    continue
                if etype in ("request/context", "request/header"):
                    hdr = data.get("header") if isinstance(data.get("header"), dict) else {}
                    conf = hdr.get("config") if isinstance(hdr.get("config"), dict) else {}
                    provider = (data.get("provider") or conf.get("provider")
                                or hdr.get("provider") or provider or "?")
                    model = (data.get("model") or conf.get("model")
                             or hdr.get("model") or model or "?")
                    continue
                usage = None
                if etype in ("assistant/message", "compaction/summary"):
                    usage = parse_usage(data.get("usage"))
                if usage is None:
                    usage = parse_usage(data.get("usage")) if "usage" in data else None
                if usage is None:
                    continue
                got = True
                r["requests"] += 1
                for k in r["tokens"]:
                    r["tokens"][k] += usage[k]
                total = sum(usage.values())
                cls, how = classify_detail(provider, model, free_kw, paid_kw)
                if cls == UNKNOWN and unknown_default in (FREE, PAID):
                    how = "%s（按配置归入%s）" % (how, CLASS_LABEL[unknown_default])
                    cls = unknown_default
                key = "%s / %s" % (provider, model)
                row = r["by_model"].setdefault(key, {"provider": provider, "model": model,
                                                     "cls": cls, "how": how, "n": 0,
                                                     "tokens": {"input": 0, "output": 0,
                                                                "cache_read": 0, "cache_write": 0}})
                row["n"] += 1
                for k in row["tokens"]:
                    row["tokens"][k] += usage[k]
                r["by_class"][cls] += 1
                r["by_class_tokens"][cls] += total
                prov = r["providers"].setdefault(provider, {"n": 0, "total": 0, "cls": cls,
                                                            "how": how, "models": set()})
                prov["n"] += 1
                prov["total"] += total
                prov["models"].add(model)
                ts = ev.get("timestamp") or ev.get("time") or data.get("timestamp") or ""
                day = day_of(ev, path)
                d = r["by_day"].setdefault(day, {"n": 0, "total": 0})
                d["n"] += 1
                d["total"] += total
        except Exception as e:
            r["errors"].append("%s: %s" % (os.path.basename(path), e))
            continue
        if got:
            r["sessions"] += 1

    days = sorted(k for k in r["by_day"] if k != "未知日期")
    r["date_min"] = days[0] if days else ""
    r["date_max"] = days[-1] if days else ""
    r["session_count"] = r["sessions"]

    for key, row in r["by_model"].items():
        row["total"] = sum(row["tokens"].values())
        row["cny"] = add_money(cfg, row["tokens"], row["cls"])
    for pname, prov in r["providers"].items():
        prov["models"] = sorted(prov["models"])

    free_t = r["by_class_tokens"][FREE]
    paid_t = r["by_class_tokens"][PAID]
    r["free_tokens"] = free_t
    r["paid_tokens"] = paid_t
    r["unknown_tokens"] = r["by_class_tokens"][UNKNOWN]
    r["free_token_rate"] = (free_t / (free_t + paid_t)) if (free_t + paid_t) > 0 else 0.0
    # 金额：免费按无缓存牌价，自费按完整牌价
    r["free_cny"] = sum(row["cny"] for row in r["by_model"].values() if row["cls"] == FREE)
    r["paid_cny"] = sum(row["cny"] for row in r["by_model"].values() if row["cls"] == PAID)
    r["total_cny"] = r["free_cny"] + r["paid_cny"]
    r["free_rate"] = (r["free_cny"] / r["total_cny"]) if r["total_cny"] > 0 else 0.0
    r["paid_actual_cny"] = cfg.get("paid_actual_cny")
    if isinstance(r["paid_actual_cny"], (int, float)) and paid_t > 0:
        r["paid_shown_cny"] = float(r["paid_actual_cny"])
        r["paid_is_actual"] = True
    else:
        r["paid_shown_cny"] = r["paid_cny"]
        r["paid_is_actual"] = False
    # 白嫖率用"实付口径"重算：免费牌价 / (免费牌价 + 实付)
    denom = r["free_cny"] + r["paid_shown_cny"]
    r["free_rate_shown"] = (r["free_cny"] / denom) if denom > 0 else 0.0
    r["unknown"] = sorted(
        [{"provider": row["provider"], "model": row["model"], "total": row["total"], "n": row["n"]}
         for row in r["by_model"].values() if row["cls"] == UNKNOWN],
        key=lambda x: -x["total"])
    r["free_kw"] = list(free_kw)
    r["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return r


def fmt(n):
    n = float(n or 0)
    if n >= 1e8:
        return "%.2f亿" % (n / 1e8)
    if n >= 1e4:
        return "%.1f万" % (n / 1e4)
    return "%d" % int(n)


# --------------------------------------------------------------- 演示数据 --

def demo_result(cfg):
    """假数据：故意混入别的学校、别的平台、公司内网、以及认不出来的 provider。"""
    rows = [
        ("csu", "DeepSeek", 2.31e8),
        ("csu", "GLM", 4.09e7),
        ("api.chat.hdu.edu.cn", "DeepSeek-R1", 1.8e7),
        ("zju-llm", "Qwen3-72B", 9.4e6),
        ("llm-gateway.corp.internal", "qwen3-max", 7.1e6),
        ("ollama", "qwen3:32b", 3.2e6),
        ("deepseek-account", "deepseek-flash", 1.22e8),
        ("aliyun-bailian", "deepseek-v4.1-flash", 1.21e7),
        ("our-lab-llm", "Qwen3-32B", 6.5e6),
    ]
    free_kw = cfg.get("free_providers") or DEFAULT_FREE_KEYWORDS
    paid_kw = cfg.get("paid_providers") or DEFAULT_PAID_KEYWORDS
    r = {"dsh_home": "(演示数据)", "searched": [], "logs": 7, "log_zstd": 7, "log_plain": 0,
         "sessions": 7, "requests": 1114, "by_model": {}, "by_day": {}, "errors": [],
         "by_class": {FREE: 0, PAID: 0, UNKNOWN: 0},
         "by_class_tokens": {FREE: 0, PAID: 0, UNKNOWN: 0},
         "providers": {}, "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}}
    for prov, model, total in rows:
        cls, how = classify_detail(prov, model, free_kw, paid_kw)
        tk = {"input": total * 0.4, "output": total * 0.02, "cache_read": total * 0.58,
              "cache_write": 0}
        key = "%s / %s" % (prov, model)
        r["by_model"][key] = {"provider": prov, "model": model, "cls": cls,
                              "how": how, "n": 100, "tokens": tk, "total": total}
        r["by_class"][cls] += 100
        r["by_class_tokens"][cls] += total
        p = r["providers"].setdefault(prov, {"n": 0, "total": 0, "cls": cls, "how": how,
                                             "models": set()})
        p["n"] += 100
        p["total"] += total
        p["models"].add(model)
        for k in r["tokens"]:
            r["tokens"][k] += tk[k]
    for i, total in enumerate([3.8e7, 6.1e7, 1.18e8, 8.4e7, 5.2e7, 3.3e7, 2.7e7]):
        day = "2026-11-0%d" % (i + 1)
        r["by_day"][day] = {"n": 159, "total": total}
    r["date_min"], r["date_max"] = "2026-11-01", "2026-11-07"
    for row in r["by_model"].values():
        row["total"] = sum(row["tokens"].values())
        row["cny"] = add_money(cfg, row["tokens"], row["cls"])
    for p in r["providers"].values():
        p["models"] = sorted(p["models"])
    r["free_tokens"] = r["by_class_tokens"][FREE]
    r["paid_tokens"] = r["by_class_tokens"][PAID]
    r["unknown_tokens"] = r["by_class_tokens"][UNKNOWN]
    r["free_token_rate"] = (r["free_tokens"] / (r["free_tokens"] + r["paid_tokens"])
                            if (r["free_tokens"] + r["paid_tokens"]) else 0.0)
    r["free_cny"] = sum(x["cny"] for x in r["by_model"].values() if x["cls"] == FREE)
    r["paid_cny"] = sum(x["cny"] for x in r["by_model"].values() if x["cls"] == PAID)
    r["total_cny"] = r["free_cny"] + r["paid_cny"]
    r["free_rate"] = r["free_cny"] / r["total_cny"] if r["total_cny"] else 0
    r["paid_actual_cny"] = cfg.get("paid_actual_cny")
    r["paid_shown_cny"] = r["paid_cny"]
    r["paid_is_actual"] = False
    denom = r["free_cny"] + r["paid_shown_cny"]
    r["free_rate_shown"] = r["free_cny"] / denom if denom else 0
    r["unknown"] = sorted([{"provider": x["provider"], "model": x["model"],
                            "total": x["total"], "n": x["n"]}
                           for x in r["by_model"].values() if x["cls"] == UNKNOWN],
                          key=lambda x: -x["total"])
    r["free_kw"] = list(cfg.get("free_providers") or DEFAULT_FREE_KEYWORDS)
    r["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    r["is_demo"] = True
    return r


# -------------------------------------------------------------------- 网页 --

RING = ('<svg viewBox="0 0 120 120" class="ring">'
        '<circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,.09)" stroke-width="12"/>'
        '<circle cx="60" cy="60" r="52" fill="none" stroke="%(color)s" stroke-width="12" '
        'stroke-linecap="round" stroke-dasharray="%(dash)s" transform="rotate(-90 60 60)"/>'
        '</svg>')


def ring(pct, color="#0A84FF"):
    pct = max(0.0, min(1.0, float(pct)))
    c = 2 * 3.14159265 * 52
    return RING % {"color": color, "dash": "%.1f %.1f" % (c * pct, c * (1 - pct))}


def esc(s):
    return _html.escape(str(s if s is not None else ""), quote=True)


def render_html(r, cfg, serve=False):
    cls_color = {FREE: "#0A84FF", PAID: "#8E8E93", UNKNOWN: "#FF9F0A"}
    rows = sorted(r["by_model"].values(), key=lambda x: -x["total"])
    top = rows[0]["total"] if rows else 1

    bars = []
    for row in rows[:12]:
        pct = (row["total"] / top * 100) if top else 0
        tag = CLASS_LABEL[row["cls"]]
        if row["cls"] == FREE and "自动" in row["how"]:
            tag = "免费·自动"
        bars.append(
            '<div class="bar-row"><div class="bar-name" title="%s / %s">%s / %s '
            '<span class="tag %s">%s</span></div>'
            '<div class="bar-wrap"><div class="bar" style="width:%.1f%%;background:%s"></div></div>'
            '<div class="bar-val">%s</div></div>'
            % (esc(row["provider"]), esc(row["model"]), esc(row["provider"]), esc(row["model"]),
               row["cls"].lower(), esc(tag), pct, cls_color[row["cls"]], fmt(row["total"])))

    days = sorted([d for d in r["by_day"] if d != "未知日期"])
    daymax = max([r["by_day"][d]["total"] for d in days], default=1)
    day_cols = []
    for d in days[-14:]:
        v = r["by_day"][d]["total"]
        h = max(2, int(v / daymax * 120)) if daymax else 2
        day_cols.append('<div class="day"><div class="day-v">%s</div>'
                        '<div class="day-bar" style="height:%dpx"></div>'
                        '<div class="day-d">%s</div></div>' % (fmt(v), h, esc(d[5:])))

    prov_rows = []
    for pname, prov in sorted(r["providers"].items(), key=lambda kv: -kv[1]["total"]):
        models = "、".join(prov["models"][:3]) + ("…" if len(prov["models"]) > 3 else "")
        prov_rows.append(
            '<div class="prov"><div class="prov-n">%s<span class="prov-m">%s</span></div>'
            '<div class="prov-c %s">%s</div><div class="prov-h">%s</div>'
            '<div class="prov-t">%s</div></div>'
            % (esc(pname), esc(models), prov["cls"].lower(), esc(CLASS_LABEL[prov["cls"]]),
               esc(prov["how"]), fmt(prov["total"])))

    unknown_card = ""
    if r["unknown"]:
        names = []
        for u in r["unknown"]:
            if u["provider"] not in names:
                names.append(u["provider"])
        snippet_free = json.dumps(list(r["free_kw"]) + names, ensure_ascii=False)
        usable = [nm for nm in names if nm not in ("?", "(未知)", "", "None")]
        if serve and usable:
            ask = []
            for nm in usable:
                ask.append(
                    '<div class="ask" data-p="%s"><div class="ask-n">%s</div>'
                    '<div class="ask-b"><button class="pill free" onclick="setCls(this,\'free\')">'
                    '学校的 / 公司的（免费额度）</button>'
                    '<button class="pill paid" onclick="setCls(this,\'paid\')">我自费的</button>'
                    '</div></div>' % (esc(nm), esc(nm)))
            note = ""
            if len(usable) < len(names):
                note = ('<div class="note">日志里没写 provider 名的（%s）没法判定，先不参与算钱。</div>'
                        % esc("、".join(n for n in names if n not in usable)))
            unknown_card = (
                '<div class="card warn"><h2>有 %d 个 provider 认不出来，点一下就行</h2>'
                '<p class="warn-p">它们既不算白嫖也不算自费，免得给你算错账：%s。'
                '点完立刻重算，并写进 <code>%s</code>（<code>free_providers</code> / '
                '<code>paid_providers</code>），以后自动生效，不用再点。</p>%s%s'
                '<details><summary>也可以手动改配置</summary><pre>%s</pre></details></div>'
                % (len(names), esc("、".join(names)), esc(CONFIG_NAME), "".join(ask), note,
                   esc(snippet_free)))
        else:
            unknown_card = (
                '<div class="card warn"><h2>有 %d 个 provider 认不出来</h2>'
                '<p class="warn-p">它们既不算白嫖也不算自费，免得给你算错账：%s。'
                '确认是免费额度（学校 / 公司 / 本机自建）就把名字加进配置文件 <code>%s</code> 的 '
                '<code>free_providers</code>，付费平台加到 <code>paid_providers</code>，再跑一次即可。'
                '不想手动挑，也可以跑 <code>--unknown free</code>（认不出的都当免费额度）；'
                '不带 <code>--static</code> 直接运行时，这一步可以在网页上点按钮完成。</p>'
                '<pre>%s</pre></div>'
                % (len(names), esc("、".join(names)), esc(CONFIG_NAME), esc(snippet_free)))

    free_pct = r["free_rate_shown"] * 100
    paid_label = "自费（实付）" if r.get("paid_is_actual") else "自费（牌价估算）"
    paid_extra = ""
    if r.get("paid_is_actual"):
        paid_extra = "按 token-bill.config.json 里填的 paid_actual_cny 显示，非估算"
    else:
        paid_extra = "牌价 %s；想显示真实实付就填配置里的 paid_actual_cny" % fmt(r["paid_cny"])

    demo_banner = ""
    if r.get("is_demo"):
        demo_banner = ('<div class="banner">这是 <b>--demo</b> 演示数据，不是真实账单。'
                       '里面故意混了别的学校、别的平台和认不出来的 provider。</div>')

    errors = ""
    if r.get("errors"):
        errors = '<div class="foot-err">%s 个日志读不动：%s</div>' % (
            len(r["errors"]), esc("；".join(r["errors"][:3])))

    empty_hint = ""
    if r["sessions"] == 0:
        empty_hint = (
            '<div class="card warn"><h2>没找到可用的会话日志</h2>'
            '<p class="warn-p">找过这些位置：%s。'
            '如果 DSH 装在别处、或者日志不在默认位置，用 <code>--dsh-home 路径</code> '
            '指一下，或者写进 <code>%s</code> 的 <code>dsh_home</code>。</p></div>'
            % (esc("、".join(r["searched"])), esc(CONFIG_NAME)))

    ic = current_icon(cfg)
    head_icon, favicon = "", ""
    uri = icon_data_uri(ic)
    if uri:
        head_icon = '<img class="logo" src="%s" alt="%s">' % (uri, esc(ic))
        favicon = '<link rel="icon" href="%s">' % uri

    actions, serve_banner = "", ""
    if serve:
        picks = []
        for nm, label in ICON_CHOICES:
            picks.append(
                '<button class="ic%s" onclick="pickIcon(\'%s\',this)">'
                '<img src="%s" alt="%s"><span>%s</span></button>'
                % (" on" if nm == ic else "", nm, icon_data_uri(nm), esc(label), esc(label)))
        actions = (
            '<div class="card"><h2>图标与快捷方式</h2><div class="icons">%s</div>'
            '<div class="act-row"><button class="pill blue" onclick="mkShortcut(this)">'
            '在桌面放一个快捷方式</button><span id="actmsg" class="actmsg"></span></div>'
            '<div class="note">图标只影响桌面快捷方式（exe 自带的图标是打包时定死的，'
            '运行中换不了）。选好图标再点左边这个按钮，桌面上就会出现「DSH Token 总账」。</div>'
            '</div>' % "".join(picks))
        serve_banner = ('<div class="banner ok">本机小服务版：认不出的平台，点按钮就能改，'
                        '改完立刻重算。关掉那个黑窗口就停止服务。</div>')

    body = HTML_TMPL
    repl = {
        "{{GENERATED}}": esc(r["generated_at"]),
        "{{VERSION}}": __version__,
        "{{LINK}}": LINK,
        "{{DEMO_BANNER}}": demo_banner,
        "{{BANNER}}": serve_banner,
        "{{HEAD_ICON}}": head_icon,
        "{{FAVICON}}": favicon,
        "{{ACTIONS}}": actions,
        "{{EMPTY_HINT}}": empty_hint,
        "{{UNKNOWN_CARD}}": unknown_card,
        "{{SESSIONS}}": str(r["sessions"]),
        "{{REQUESTS}}": str(r["requests"]),
        "{{DATERANGE}}": ("%s ~ %s" % (r["date_min"], r["date_max"])
                          if r["date_min"] else "无数据"),
        "{{FREE_CNY}}": "%.0f" % r["free_cny"],
        "{{FREE_TOKENS}}": fmt(r["free_tokens"]),
        "{{FREE_RATE}}": "%.0f" % free_pct,
        "{{PAID_CNY}}": "%.0f" % r["paid_shown_cny"],
        "{{PAID_TOKENS}}": fmt(r["paid_tokens"]),
        "{{PAID_LABEL}}": esc(paid_label),
        "{{PAID_EXTRA}}": esc(paid_extra),
        "{{TOTAL_TOKENS}}": fmt(sum(r["tokens"].values())),
        "{{IN_TOKENS}}": fmt(r["tokens"]["input"]),
        "{{OUT_TOKENS}}": fmt(r["tokens"]["output"]),
        "{{CACHE_TOKENS}}": fmt(r["tokens"]["cache_read"]),
        "{{UNKNOWN_TOKENS}}": fmt(r["unknown_tokens"]),
        "{{UNKNOWN_LEGEND}}": ('<span><i class="dot" style="background:#FF9F0A"></i>待确认 %s</span>'
                               % fmt(r["unknown_tokens"])) if r["unknown_tokens"] else "",
        "{{RING_FREE}}": ring(r["free_rate"]),
        "{{RING_TOKEN}}": ring(r["free_token_rate"]),
        "{{FREE_TOKEN_RATE}}": "%.0f" % (r["free_token_rate"] * 100),
        "{{BARS}}": "".join(bars) or '<div class="none">没有数据</div>',
        "{{DAYS}}": "".join(day_cols) or '<div class="none">没有数据</div>',
        "{{PROVIDERS}}": "".join(prov_rows) or '<div class="none">没有数据</div>',
        "{{PLATFORMS}}": esc(len(r["providers"])),
        "{{FREELIST}}": esc("、".join(p for p in sorted(r["providers"])
                                      if r["providers"][p]["cls"] == FREE) or "无"),
        "{{ERRORS}}": errors,
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    return body


HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>Token 总账</title>{{FAVICON}}
<style>
:root{--bg:#0A0A0C;--card:#1C1C1E;--line:rgba(255,255,255,.08);--tx:#F5F5F7;--dim:#8E8E93;--accent:#0A84FF;--warn:#FF9F0A}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font:15px/1.6 -apple-system,"SF Pro SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;padding:48px 24px 64px;letter-spacing:.01em}
.wrap{max-width:1120px;margin:0 auto}
.kicker{color:var(--dim);font-size:13px;letter-spacing:.06em}
h1{font-size:40px;font-weight:700;letter-spacing:-.02em;margin:6px 0 4px}
.sub{color:var(--dim);font-size:15px}
.banner{margin:22px 0;padding:14px 18px;border-radius:14px;background:rgba(255,159,10,.12);color:#FFD08A;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:26px 0}
.metric{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px}
.metric .l{color:var(--dim);font-size:13px}
.metric .v{font-size:34px;font-weight:700;letter-spacing:-.02em;margin:6px 0 2px}
.metric .v.blue{color:var(--accent)}
.metric .d{color:var(--dim);font-size:12.5px;line-height:1.5}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px 28px;margin:18px 0}
.card h2{font-size:19px;font-weight:650;margin-bottom:18px}
.card.warn{background:rgba(255,159,10,.07);border-color:rgba(255,159,10,.28)}
.warn-p{color:#F0DCC0;font-size:14px;margin-bottom:14px}
.card pre{background:rgba(0,0,0,.42);border:1px solid var(--line);border-radius:12px;padding:14px 16px;color:#9AE6B4;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;overflow-x:auto;white-space:pre-wrap;word-break:break-all}
code{background:rgba(255,255,255,.08);border-radius:5px;padding:1px 6px;font:12.5px ui-monospace,Menlo,monospace}
.rings{display:flex;gap:64px;justify-content:center;padding:6px 0 2px}
.rings .item{text-align:center;position:relative}
.rings .ring{width:172px;height:172px}
.rings .mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.rings .mid b{font-size:29px;font-weight:700;letter-spacing:-.02em}
.rings .mid span{color:var(--dim);font-size:12px;max-width:136px;line-height:1.35}
.legend{display:flex;gap:22px;justify-content:center;color:var(--dim);font-size:13px;margin-top:4px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:1px}
.bar-row{display:grid;grid-template-columns:minmax(220px,330px) 1fr 96px;align-items:center;gap:16px;padding:9px 0}
.bar-name{color:var(--tx);font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-m{color:var(--dim);font-size:12px}
.bar-wrap{background:rgba(255,255,255,.06);height:9px;border-radius:5px;overflow:hidden}
.bar{height:100%;border-radius:5px;background:var(--accent)}
.bar-val{text-align:right;color:var(--dim);font-size:13px;font-variant-numeric:tabular-nums}
.tag{display:inline-block;margin-left:6px;padding:1px 8px;border-radius:20px;font-size:11px;line-height:1.7;vertical-align:1px}
.tag.free{background:rgba(10,132,255,.16);color:#7FBBFF}
.tag.paid{background:rgba(255,255,255,.09);color:#B9B9BE}
.tag.unknown{background:rgba(255,159,10,.16);color:#FFC966}
.days{display:flex;gap:14px;align-items:flex-end;justify-content:space-between;padding-top:12px;overflow-x:auto}
.day{flex:1;min-width:44px;text-align:center}
.day-bar{background:var(--accent);border-radius:8px 8px 4px 4px;margin:6px auto 8px;width:100%;max-width:62px}
.day-v{color:var(--dim);font-size:11.5px;white-space:nowrap}
.day-d{color:var(--dim);font-size:12px}
.prov{display:grid;grid-template-columns:minmax(190px,260px) 84px 1fr 92px;gap:14px;align-items:baseline;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.prov:last-child{border-bottom:0}
.prov-n{font-size:13.5px;word-break:break-all}
.prov-m{display:block;color:var(--dim);font-size:11.5px}
.prov-c{font-size:12.5px}
.prov-c.free{color:#7FBBFF}.prov-c.paid{color:#B9B9BE}.prov-c.unknown{color:#FFC966}
.prov-h{color:var(--dim);font-size:12.5px}
.prov-t{text-align:right;color:var(--dim);font-size:13px;font-variant-numeric:tabular-nums}
.note{color:var(--dim);font-size:12.5px;line-height:1.75;margin-top:14px}
.foot{color:var(--dim);font-size:12px;margin-top:26px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.foot-err{color:#FF9F9F;font-size:12px;margin-top:6px}
.none{color:var(--dim);font-size:13px;padding:8px 0}
.head{display:flex;align-items:center;gap:16px}
.logo{width:58px;height:58px;border-radius:16px;box-shadow:0 8px 22px rgba(0,0,0,.55)}
.banner.ok{background:rgba(10,132,255,.12);color:#9CCBFF}
.pill{border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--tx);font-size:13px;padding:9px 14px;border-radius:11px;cursor:pointer;transition:.15s}
.pill:hover{background:rgba(255,255,255,.12)}
.pill:disabled{opacity:.45;cursor:default}
.pill.free{border-color:rgba(10,132,255,.5);color:#9CCBFF}
.pill.free:hover{background:rgba(10,132,255,.18)}
.pill.paid{border-color:rgba(255,255,255,.16)}
.pill.blue{background:var(--accent);border-color:transparent;color:#fff;font-weight:600}
.pill.blue:hover{background:#0A74E0}
.ask{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.06);flex-wrap:wrap}
.ask:last-of-type{border-bottom:0}
.ask-n{font-size:14px;word-break:break-all}
.ask-b{display:flex;gap:10px;flex-wrap:wrap}
.icons{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.icons .ic{background:transparent;border:2px solid transparent;border-radius:16px;padding:6px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px;color:var(--dim);font-size:12px;transition:.15s}
.icons .ic:hover{background:rgba(255,255,255,.06)}
.icons .ic.on{border-color:var(--accent);background:rgba(10,132,255,.12);color:var(--tx)}
.icons .ic img{width:56px;height:56px;border-radius:13px;display:block}
.act-row{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.actmsg{font-size:12.5px;color:var(--dim)}
.actmsg.ok{color:#7FD8A0}
.actmsg.bad{color:#FF9F9F}
details{margin-top:14px}
summary{cursor:pointer;color:var(--dim);font-size:13px}
@media(max-width:820px){.grid{grid-template-columns:1fr}.bar-row{grid-template-columns:1fr 70px}.bar-wrap{grid-column:1/-1}.prov{grid-template-columns:1fr 70px}.prov-h{display:none}.rings{gap:24px}.rings .ring{width:140px;height:140px}}
</style></head><body><div class="wrap">
<div class="kicker">DSH Token 总账 · 生成于 {{GENERATED}} · 数据源：本机会话日志（解压后统计，零 API 花费）</div>
<div class="head">{{HEAD_ICON}}<h1>Token 总账</h1></div>
<div class="sub">{{DATERANGE}} · {{SESSIONS}} 个会话 · {{REQUESTS}} 次请求 · 覆盖 {{PLATFORMS}} 个 provider</div>
{{DEMO_BANNER}}
{{BANNER}}
{{EMPTY_HINT}}
<div class="grid">
  <div class="metric"><div class="l">白嫖价值 · 免费额度</div><div class="v blue">¥{{FREE_CNY}}</div>
    <div class="d">{{FREE_TOKENS}} token · 学校 / 公司 / 本机自建的额度，按官方牌价折算的等价价值</div></div>
  <div class="metric"><div class="l">{{PAID_LABEL}}</div><div class="v">¥{{PAID_CNY}}</div>
    <div class="d">{{PAID_TOKENS}} token · {{PAID_EXTRA}}</div></div>
  <div class="metric"><div class="l">白嫖率（按钱算）</div><div class="v">{{FREE_RATE}}%</div>
    <div class="d">免费 {{FREE_CNY}} 元 vs 自费 {{PAID_CNY}} 元；待确认的 {{UNKNOWN_TOKENS}} token 未计入</div></div>
</div>
{{UNKNOWN_CARD}}
<div class="card"><h2>两个视角</h2>
  <div class="rings">
    <div class="item">{{RING_FREE}}<div class="mid"><b>¥{{FREE_CNY}}</b><span>白嫖的等价价值</span></div></div>
    <div class="item">{{RING_TOKEN}}<div class="mid"><b>{{FREE_TOKEN_RATE}}%</b><span>白嫖 token 占比</span></div></div>
  </div>
  <div class="legend"><span><i class="dot" style="background:#0A84FF"></i>免费 {{FREE_TOKENS}}</span>
  <span><i class="dot" style="background:#8E8E93"></i>自费 {{PAID_TOKENS}}</span>
  {{UNKNOWN_LEGEND}}</div>
</div>
<div class="card"><h2>按模型</h2>{{BARS}}</div>
<div class="card"><h2>按天</h2><div class="days">{{DAYS}}</div></div>
<div class="card"><h2>每个 provider 是怎么判定的</h2>{{PROVIDERS}}
  <div class="note">判定顺序：① 命中 <code>free_providers</code> 关键词 → 免费　② 命中 <code>paid_providers</code> → 自费
  ③ 端点长相像学校/内网/自建（.edu、univ、campus、localhost、ollama…）→ 免费（自动判定）
  ④ 都不中 → 待确认，不参与算钱。规则都能在 <code>token-bill.config.json</code> 里改，不用改代码。</div>
</div>
{{ACTIONS}}
<div class="card"><h2>口径说明</h2>
  <div class="note">统计范围 {{DATERANGE}}，共 {{SESSIONS}} 个会话、{{REQUESTS}} 次请求、{{TOTAL_TOKENS}} token
  （输入 {{IN_TOKENS}} + 输出 {{OUT_TOKENS}} + 缓存读 {{CACHE_TOKENS}}）。
  免费额度按官方无缓存牌价折算（输入 ¥2.0/百万、输出 ¥3.0/百万）；自费按输入 ¥2.0 + 缓存读 ¥0.2 + 输出 ¥3.0/百万。
  只统计 DSH 会话日志里的调用：网页版对话、会话标题生成不计入，日志里没有的历史也没有。
  当前判定为免费的 provider：{{FREELIST}}。</div>
  {{ERRORS}}
</div>
<div class="foot"><span>dsh-token-bill v{{VERSION}} · MIT · 只读本机日志，不联网</span><span>·</span><span>{{LINK}}</span></div>
</div>
<script>
function toast(msg, ok){var e=document.getElementById('actmsg');if(!e){alert(msg);return;}
  e.textContent=msg;e.className='actmsg '+(ok?'ok':'bad');}
async function post(url,body){
  return await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body||{})});}
async function setCls(btn,cls){
  var box=btn.closest('.ask'),p=box.dataset.p,y=window.scrollY;
  box.querySelectorAll('button').forEach(function(b){b.disabled=true;});
  btn.textContent='正在写入…';
  try{
    var r=await post('/api/classify',{provider:p,cls:cls});
    if(r.ok){var h=await r.text();document.open();document.write(h);document.close();
      window.scrollTo(0,y);return;}
    var j=await r.json().catch(function(){return{};});
    toast('没写成：'+(j.err||r.status),false);
  }catch(e){toast('没写成：'+e,false);}
  box.querySelectorAll('button').forEach(function(b){b.disabled=false;});
}
async function pickIcon(name,el){
  try{
    var r=await post('/api/icon',{icon:name});
    if(r.ok){document.querySelectorAll('.icons .ic').forEach(function(b){
        b.classList.toggle('on',b===el);});
      toast('图标记住了，桌面快捷方式会用它。',true);return;}
    toast('没保存成功。',false);
  }catch(e){toast('没保存成功：'+e,false);}
}
async function mkShortcut(btn){
  btn.disabled=true;toast('正在建快捷方式…',true);
  try{
    var r=await post('/api/shortcut',{});var j=await r.json().catch(function(){return{};});
    toast(j.ok?('已放到桌面：'+j.msg):('没建成：'+(j.msg||j.err||'')),!!j.ok);
  }catch(e){toast('没建成：'+e,false);}
  btn.disabled=false;
}
</script>
</body></html>
"""


# -------------------------------------------------------------------- 输出 --

def open_in_browser(path):
    errs = []
    try:
        os.startfile(path)  # noqa: 仅 Windows
        return True
    except Exception as e:
        errs.append("startfile: %s" % e)
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.isfile(exe):
            try:
                import subprocess
                subprocess.Popen([exe, path])
                return True
            except Exception as e:
                errs.append("%s: %s" % (os.path.basename(exe), e))
    try:
        import webbrowser
        if webbrowser.open(path):
            return True
        errs.append("webbrowser: 返回 False")
    except Exception as e:
        errs.append("webbrowser: %s" % e)
    try:
        with io.open(os.path.join(base_dir(), "open-error.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(errs) + "\n")
    except Exception:
        pass
    return False


def write_html(path, text):
    """写网页；目录不可写时退回家目录，别让程序直接崩。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path, None
    except OSError as e:
        alt = os.path.join(os.path.expanduser("~"), "Documents", os.path.basename(path))
        try:
            os.makedirs(os.path.dirname(alt), exist_ok=True)
            with io.open(alt, "w", encoding="utf-8") as f:
                f.write(text)
            return alt, "%s 写不进去（%s），改存到了 %s" % (path, e, alt)
        except OSError:
            return None, "哪里都写不进去：%s" % e


def print_summary(r, cfg):
    print("=" * 46)
    print("DSH Token 总账（本机 DSH 会话日志）")
    print("=" * 46)
    print("DSH 目录: %s" % r["dsh_home"])
    print("会话 %d 个（扫描日志 %d 个）| 时间 %s"
          % (r["sessions"], r["logs"], ("%s ~ %s" % (r["date_min"], r["date_max"])
                                        if r["date_min"] else "-")))
    t = r["tokens"]
    print("请求 %d 次 | 总计 %s token（输入%s 输出%s 缓存读%s）"
          % (r["requests"], fmt(sum(t.values())), fmt(t["input"]), fmt(t["output"]),
             fmt(t["cache_read"])))
    print("免费额度: %s token | 牌价价值 ≈ ¥%.2f" % (fmt(r["free_tokens"]), r["free_cny"]))
    print("自费: %s token | %s ¥%.2f"
          % (fmt(r["paid_tokens"]), "实付" if r["paid_is_actual"] else "牌价估算",
             r["paid_shown_cny"]))
    if r["unknown_tokens"]:
        print("待确认: %s token（%d 个 provider 认不出来，见下）"
              % (fmt(r["unknown_tokens"]), len({u["provider"] for u in r["unknown"]})))
    print("白嫖率（按钱算）: %.0f%%" % (r["free_rate_shown"] * 100))
    print("-" * 46)
    print("provider 判定：")
    for pname, prov in sorted(r["providers"].items(), key=lambda kv: -kv[1]["total"]):
        print("  %-28s %-4s %-26s %s"
              % (pname[:28], CLASS_LABEL[prov["cls"]], prov["how"][:26], fmt(prov["total"])))
    if r["unknown"]:
        names = sorted({u["provider"] for u in r["unknown"]})
        print("-" * 46)
        print("认不出来的 provider：%s" % "、".join(names))
        print("确认它们免费，就把名字写进 %s 的 free_providers（付费平台写 paid_providers），再跑一次。"
              % CONFIG_NAME)
    if r["errors"]:
        print("读不动的日志 %d 个：%s" % (len(r["errors"]), "；".join(r["errors"][:3])))


def doctor(r):
    print("=" * 46)
    print("自检（--doctor）")
    print("=" * 46)
    print("程序版本 : v%s" % __version__)
    print("Python   : %s" % sys.version.split()[0])
    print("运行方式 : %s" % ("打包的 exe" if getattr(sys, "frozen", False) else "源码"))
    print("配置     : %s" % (r and "" or ""))
    print("DSH 目录 : %s" % r["dsh_home"])
    print("找过这些位置：" + "、".join(r["searched"]))
    print("找到日志 : %d 个（压缩 %d / 纯文本 %d）"
          % (r["logs"], r["log_zstd"], r["log_plain"]))
    if r["logs"] == 0:
        print("→ 一个日志都没找到：确认 DSH 装过且聊过天，或用 --dsh-home 指向真实目录。")
        return 0
    print_summary(r, {})
    print("-" * 46)
    if r["sessions"] == 0:
        print("→ 找到了日志但里面没有 usage 记录，可能是 DSH 版本字段不同，"
              "把日志路径发到项目 issue 里看看。")
    else:
        print("→ 判定正常。有认不出来的 provider 就按上面的提示写进配置文件。")
    return 0


# --------------------------------------------------- 交互（本机小服务）--

def save_config(cfg, path):
    """把配置写回磁盘：保留用户自己的键，内部下划线键不写。"""
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        cfg["_config_path"] = path
        return True, ""
    except Exception as e:
        return False, str(e)


def add_rule(cfg, path, provider, cls):
    """把一个 provider 加进 free_providers / paid_providers（大小写不敏感去重）。"""
    provider = (provider or "").strip()
    if not provider or provider in ("?", "(未知)"):
        return False, "provider 名字不可用，改不了"
    key = "free_providers" if cls == FREE else "paid_providers"
    other = "paid_providers" if cls == FREE else "free_providers"
    low = provider.lower()
    cfg[key] = [x for x in cfg.get(key, []) if str(x).lower() != low] + [provider]
    cfg[other] = [x for x in cfg.get(other, []) if str(x).lower() != low]
    return save_config(cfg, path)


def icons_dir():
    """找 assets/icons：先看 exe / 脚本旁边，再往上一级。"""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(base_dir())
    for root in roots:
        for rel in ("assets", os.path.join("_internal", "assets"), ""):
            p = os.path.join(root, rel, "icons") if rel else os.path.join(root, "icons")
            if os.path.isdir(p):
                return p
        p = os.path.join(os.path.dirname(root), "assets", "icons")
        if os.path.isdir(p):
            return p
    return ""


def icon_file(name, ext):
    d = icons_dir()
    if not d or name not in [n for n, _ in ICON_CHOICES]:
        return ""
    p = os.path.join(d, "%s.%s" % (name, ext))
    return p if os.path.isfile(p) else ""


def icon_data_uri(name):
    """把图标内联进 HTML，静态页也能带着图标走。"""
    p = icon_file(name, "png")
    if not p:
        return ""
    try:
        with open(p, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


def current_icon(cfg):
    name = str(cfg.get("icon") or "")
    return name if name in [n for n, _ in ICON_CHOICES] else DEFAULT_ICON


def desktop_dir():
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"),
                 os.path.join(home, "桌面")):
        if os.path.isdir(cand):
            return cand
    return os.path.join(home, "Desktop")


def make_shortcut(icon_name):
    """在桌面放一个带指定图标的快捷方式（Windows）。"""
    if os.name != "nt":
        return False, "只有 Windows 能建快捷方式"
    ico = icon_file(icon_name, "ico") or icon_file(DEFAULT_ICON, "ico")
    if not ico:
        return False, "找不到图标文件（assets/icons/*.ico），压缩包可能没解压完整"
    if getattr(sys, "frozen", False):
        target = sys.executable
        wd = os.path.dirname(os.path.abspath(sys.executable))
    else:
        wd = base_dir()
        runner = os.path.join(wd, "run-source.cmd")
        target = runner if os.path.isfile(runner) else sys.executable
    lnk = os.path.join(desktop_dir(), SHORTCUT_NAME)
    ps = ("$ws=New-Object -ComObject WScript.Shell;"
          "$l=$ws.CreateShortcut('%s');"
          "$l.TargetPath='%s';$l.WorkingDirectory='%s';"
          "$l.IconLocation='%s';$l.Description='DSH Token 总账';$l.Save()"
          % (lnk, target, wd, ico))
    try:
        flags = 0x08000000 if os.name == "nt" else 0
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, creationflags=flags, timeout=90)
        if os.path.isfile(lnk):
            return True, lnk
        return False, (p.stderr or p.stdout or "powershell 没能建出快捷方式").strip()[:300]
    except Exception as e:
        return False, "建快捷方式失败：%s" % e


def serve(cfg, dsh_home, demo=False, port=0, open_browser=True):
    """起一个只绑本机的服务：认不出的 provider 可以在网页上点选，改完立刻重算。"""
    import http.server
    import socketserver
    import threading

    cfg_path = cfg.get("_config_path") or os.path.join(base_dir(), CONFIG_NAME)
    cfg["_config_path"] = cfg_path
    first = [port or 8730]

    def build():
        r = demo_result(cfg) if demo else collect(dsh_home, cfg)
        return render_html(r, cfg, serve=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "dsh-token-bill/" + __version__

        def log_message(self, *a):
            pass

        def _send(self, code, ctype, payload):
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            except Exception:
                pass

        def _local_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
            return host in ("127.0.0.1", "localhost", "::1", "")

        def do_GET(self):
            path = self.path.split("?")[0]
            if not self._local_ok():
                return self._send(403, "text/plain; charset=utf-8", "只允许本机访问")
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", build())
            if path.startswith("/icon/"):
                p = icon_file(path[6:].rsplit(".", 1)[0], "png")
                if p:
                    with open(p, "rb") as f:
                        return self._send(200, "image/png", f.read())
                return self._send(404, "text/plain", "no icon")
            return self._send(404, "text/plain; charset=utf-8", "没有这个地址")

        def do_POST(self):
            if not self._local_ok():
                return self._send(403, "application/json", '{"ok":false,"err":"只允许本机访问"}')
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads((self.rfile.read(n) or b"{}").decode("utf-8") or "{}")
            except Exception as e:
                return self._send(400, "application/json",
                                  json.dumps({"ok": False, "err": str(e)}, ensure_ascii=False))
            path = self.path.split("?")[0]
            if path == "/api/classify":
                cls = FREE if str(data.get("cls")) == "free" else PAID
                ok, msg = add_rule(cfg, cfg_path, str(data.get("provider") or ""), cls)
                if not ok:
                    return self._send(500, "application/json",
                                      json.dumps({"ok": False, "err": msg}, ensure_ascii=False))
                print("  记下了：%s -> %s" % (data.get("provider"), CLASS_LABEL[cls]))
                return self._send(200, "text/html; charset=utf-8", build())
            if path == "/api/icon":
                name = str(data.get("icon") or "")
                if name not in [n for n, _ in ICON_CHOICES]:
                    return self._send(400, "application/json",
                                      json.dumps({"ok": False, "err": "没有这个图标"}, ensure_ascii=False))
                cfg["icon"] = name
                ok, msg = save_config(cfg, cfg_path)
                return self._send(200 if ok else 500, "application/json",
                                  json.dumps({"ok": ok, "err": msg, "icon": name},
                                             ensure_ascii=False))
            if path == "/api/shortcut":
                ok, msg = make_shortcut(str(data.get("icon") or cfg.get("icon") or DEFAULT_ICON))
                return self._send(200 if ok else 500, "application/json",
                                  json.dumps({"ok": ok, "msg": msg}, ensure_ascii=False))
            return self._send(404, "application/json", '{"ok":false,"err":"没有这个接口"}')

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd, last = None, ""
    start = port or 8730
    for p in range(start, start + 20):
        try:
            httpd = Server(("127.0.0.1", p), Handler)
            first[0] = p
            break
        except OSError as e:
            last = str(e)
    if httpd is None:
        print("端口 8730~%d 都被占了（%s），用 --port 换一个。" % (start + 19, last))
        return 1

    url = "http://127.0.0.1:%d/" % first[0]
    print("-" * 46)
    print("账单页面已就绪：%s" % url)
    print("认不出的平台旁边有两个按钮，点一下立刻重算，并写进：%s" % cfg_path)
    print("关掉这个黑窗口 = 停止服务（已经写好的配置和账单都还在）。")
    if open_browser:
        threading.Timer(0.7, lambda: open_in_browser(url)).start()
    else:
        print("（--no-open：请自己复制上面这个地址到浏览器打开）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
    return 0


# -------------------------------------------------------------------- main --

def _fix_console():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _hold():
    """双击运行时留个窗口，别让结果一闪就没。"""
    if not getattr(sys, "frozen", False) or os.environ.get("DSH_TOKEN_BILL_NOHOLD"):
        return
    try:
        import time
        time.sleep(4)
    except Exception:
        pass


def main(argv=None):
    _fix_console()
    ap = argparse.ArgumentParser(description="DSH Token 总账 —— 本机会话日志账单")
    ap.add_argument("--dsh-home", default=None, help="DSH 目录（默认 %%DSH_HOME%% 或 ~/.dsh）")
    ap.add_argument("--config", default=None, help="配置文件路径")
    ap.add_argument("--out", "--html", dest="out", default=None, help="输出 html 路径")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--print", dest="do_print", action="store_true", help="只在控制台打印摘要")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--doctor", action="store_true", help="自检：日志在哪、每个 provider 怎么判定的")
    ap.add_argument("--rules", action="store_true", help="导出识别到的平台清单（分享/提建议用，不含金额）")
    ap.add_argument("--unknown", choices=["skip", "free", "paid"], default=None,
                    help="认不出来的 provider 怎么算：skip(默认)/free/paid")
    ap.add_argument("--init-config", action="store_true", help="按本机数据生成配置文件")
    ap.add_argument("--demo", action="store_true", help="用假数据演示")
    ap.add_argument("--serve", action="store_true", help="起本地小服务（网页上点按钮改判定）")
    ap.add_argument("--static", action="store_true", help="只生成静态 html（老方式，不起服务）")
    ap.add_argument("--port", type=int, default=0, help="--serve 用哪个端口（默认 8730，被占自动往后试）")
    ap.add_argument("--paid", type=float, default=None, help="真实实付金额（元）")
    ap.add_argument("--paid-date", default=None, help="查这个金额的日期")
    ap.add_argument("--version", action="version", version="dsh-token-bill v%s" % __version__)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.paid is not None:
        cfg["paid_actual_cny"] = args.paid
    if args.paid_date is not None:
        cfg["paid_actual_date"] = args.paid_date
    if args.unknown is not None:
        cfg["unknown_class"] = args.unknown
    if cfg.get("_config_error"):
        print("提示：配置文件读不了（%s），这次用默认规则。" % cfg["_config_error"])

    dsh_home = args.dsh_home or cfg.get("dsh_home") or default_dsh_home()

    if args.demo:
        r = demo_result(cfg)
    else:
        r = collect(dsh_home, cfg)

    if args.doctor:
        if args.demo:
            print("--doctor 忽略 --demo。")
        return doctor(collect(dsh_home, cfg))

    if args.init_config:
        p = os.path.join(base_dir(), CONFIG_NAME)
        free = list(DEFAULT_FREE_KEYWORDS)
        paid = list(DEFAULT_PAID_KEYWORDS)
        known = {}
        for pname, prov in r["providers"].items():
            known.setdefault(prov["cls"], []).append(pname)
        for pname in known.get(FREE, []):
            if pname.lower() not in [x.lower() for x in free] and pname not in ("?", ""):
                free.append(pname)
        for pname in known.get(PAID, []):
            if pname.lower() not in [x.lower() for x in paid] and pname not in ("?", ""):
                paid.append(pname)
        write_example_config(p, free, paid)
        print("已写出配置：%s" % p)
        for k in (FREE, PAID, UNKNOWN):
            names = known.get(k, [])
            if names:
                print("%s：%s" % (CLASS_LABEL[k], "、".join(names)))
        if known.get(UNKNOWN):
            print("认不出来的这几个，确认免费就留在 free_providers，付费就搬到 paid_providers。")
        return 0

    if args.rules:
        out = {"tool": "dsh-token-bill v%s" % __version__, "dsh_home": r["dsh_home"],
               "providers": [{"name": p, "class": v["cls"], "how": v["how"],
                              "models": v["models"]}
                             for p, v in sorted(r["providers"].items(),
                                                key=lambda kv: -kv[1]["total"])]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("# 只有平台名和判定结果，没有金额/token 数，可以直接贴给别人或提 issue。")
        return 0

    if args.json:
        out = {k: v for k, v in r.items() if k != "by_model"}
        out["by_model"] = [{"provider": x["provider"], "model": x["model"],
                            "class": x["cls"], "how": x["how"], "requests": x["n"],
                            "tokens": x["total"], "list_cny": round(x["cny"], 4)}
                           for x in sorted(r["by_model"].values(), key=lambda y: -y["total"])]
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.do_print:
        print_summary(r, cfg)
        return 0

    explicit = (args.demo or args.do_print or args.json or args.doctor or args.rules
                or args.init_config or args.static or args.out)
    if args.serve or not explicit:
        return serve(cfg, dsh_home, demo=args.demo, port=args.port,
                     open_browser=not args.no_open)

    out_path = args.out or cfg.get("output") or DEFAULT_OUT
    if not os.path.isabs(out_path):
        out_path = os.path.join(base_dir(), out_path)
    written, warn = write_html(out_path, render_html(r, cfg))
    print_summary(r, cfg)
    if warn:
        print("-" * 46)
        print("注意：%s" % warn)
    if written:
        print("-" * 46)
        print("网页已生成：%s" % written)
        if not args.no_open:
            if open_in_browser(written):
                print("已用浏览器打开。")
            else:
                print("浏览器没打开成功，手动双击上面这个 html 就行。")
    _hold()
    return 0


if __name__ == "__main__":
    sys.exit(main())
