# -*- coding: utf-8 -*-
"""dsh-token-bill —— 把 DSH 的会话日志算成一张离线网页账单。

数据源：$DSH_HOME/sessions/**/session*.jsonl.zstd（默认 ~/.dsh/sessions）
  - assistant/message.data.usage   每次模型请求的用量（模型看最近一次 request/*）
  - compaction/summary.data.usage  每次上下文压缩的用量（自带 provider/model）

全部在本机解压统计，不联网、不上传、不调用任何 API，所以零花费。

用法：
  dsh-token-bill                     生成网页并用默认浏览器打开
  dsh-token-bill --no-open           只生成
  dsh-token-bill --json              输出机器可读 JSON
  dsh-token-bill --demo              用假数据渲染一张演示页（测试/截图用）
  dsh-token-bill --dsh-home PATH     指定 DSH 目录
  dsh-token-bill --paid 26.5 --paid-date 2026-11-05
                                     填账号后台的真实实付金额（比牌价估算准）
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import sys

__version__ = "1.0.0"

APP_NAME = "DSH Token 总账"
CONFIG_NAME = "token-bill.config.json"
DEFAULT_OUT = "token-账单.html"
DEFAULT_FREE_PROVIDERS = ["csu", "glm"]
DEFAULT_LIST_PRICE = {"input": 2.0, "cache_read": 0.2, "output": 3.0}
# 社区口径：缓存为主的账号实测均价 ≈ 4 分/百万 token，仅作"按量付费大概多少钱"的旁证
DEFAULT_BILL_RATE = 0.0401

DEFAULT_CONFIG = {
    "dsh_home": "",
    "output": DEFAULT_OUT,
    "free_providers": DEFAULT_FREE_PROVIDERS,
    "list_price": DEFAULT_LIST_PRICE,
    "bill_rate": DEFAULT_BILL_RATE,
    "paid_actual_cny": None,
    "paid_actual_date": "",
}

# ---------------------------------------------------------------- 环境与配置


def base_dir() -> str:
    """exe 旁边 or 脚本旁边——单文件 exe 解包到临时目录，必须用 sys.executable。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def default_dsh_home() -> str:
    return os.environ.get("DSH_HOME", "").strip() or os.path.join(
        os.path.expanduser("~"), ".dsh")


def load_config(path: str | None = None) -> tuple[dict, str | None]:
    """读 token-bill.config.json（没有就全用默认值），返回 (config, 实际读到的路径)。"""
    cfg = dict(DEFAULT_CONFIG)
    cfg["list_price"] = dict(DEFAULT_LIST_PRICE)
    cfg["free_providers"] = list(DEFAULT_FREE_PROVIDERS)
    candidates = [path] if path else [
        os.path.join(base_dir(), CONFIG_NAME),
        os.path.join(os.getcwd(), CONFIG_NAME),
    ]
    used = None
    for c in candidates:
        if c and os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in ("list_price", "free_providers") and isinstance(v, type(cfg[k])):
                            cfg[k] = v
                        elif v is not None:
                            cfg[k] = v
                    used = c
            except Exception as ex:
                print("配置读取失败，改用默认值：%s（%s）" % (c, ex), file=sys.stderr)
            break
    return cfg, used


def write_example_config(cfg: dict, path: str = "") -> str:
    path = path or os.path.join(base_dir(), CONFIG_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


# ---------------------------------------------------------------- 读日志


def zstd_lines(path: str):
    """逐行读 .zstd。Python 3.14+ 用标准库 compression.zstd；否则要 pip install zstandard。"""
    try:
        from compression import zstd  # Python 3.14+
        with zstd.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line
        return
    except ImportError:
        pass
    import zstandard  # type: ignore
    with open(path, "rb") as raw:
        with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
            for line in io.TextIOWrapper(reader, encoding="utf-8", errors="replace"):
                yield line


def fmt(n) -> str:
    n = n or 0
    if n >= 1e8:
        return "%.2f亿" % (n / 1e8)
    if n >= 1e4:
        return "%.1f万" % (n / 1e4)
    return str(n)


def make_classifier(free_providers):
    fps = [str(x).lower() for x in (free_providers or [])]

    def classify(provider, model):
        p = (provider or "").lower()
        m = (model or "").lower()
        if not p and not m:
            return "OTHER"
        for kw in fps:
            if kw and (kw in p or kw in m):
                return "FREE"
        if p in ("?", "") and m in ("?", ""):
            return "OTHER"
        return "PAID"

    return classify


def collect(dsh_home: str, free_providers) -> dict:
    root = os.path.join(dsh_home, "sessions")
    files = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if "session" in fn and fn.endswith(".zstd"):
                files.append(os.path.join(dirpath, fn))

    classify = make_classifier(free_providers)

    def new_b():
        return {"n": 0, "input": 0, "output": 0, "cacheR": 0, "cacheW": 0, "total": 0}

    by_model, by_class, by_day, days = {}, {}, {}, set()

    def bump(store, key, u, ts):
        b = store.setdefault(key, new_b())
        i, o = u.get("inputTokens") or 0, u.get("outputTokens") or 0
        cr, cw = u.get("cacheReadTokens") or 0, u.get("cacheWriteTokens") or 0
        vals = (("n", 1), ("input", i), ("output", o), ("cacheR", cr), ("cacheW", cw),
                ("total", i + o + cr + cw))
        for k, v in vals:
            b[k] += v
        if ts:
            day = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            days.add(day)
            db = by_day.setdefault(day, new_b())
            for k, v in vals:
                db[k] += v

    for path in files:
        cur = (None, None)
        try:
            for line in zstd_lines(path):
                if ('"assistant/message"' not in line and '"request/' not in line
                        and '"compaction/summary"' not in line):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type")
                data = obj.get("data") or {}
                ts = obj.get("time") or 0
                if t == "request/context":
                    cur = (data.get("provider"), data.get("model"))
                elif t == "request/header":
                    cfg = (data.get("header") or {}).get("config") or {}
                    if cfg.get("provider"):
                        cur = (cfg.get("provider"), cfg.get("model"))
                elif t == "assistant/message":
                    u = data.get("usage")
                    if not u:
                        continue
                    prov, model = cur if (cur and cur[0]) else ("?", "?")
                    bump(by_model, (prov, model), u, ts)
                    bump(by_class, classify(prov, model), u, ts)
                elif t == "compaction/summary":
                    u = data.get("usage")
                    if not u:
                        continue
                    prov = data.get("provider") or "?"
                    model = data.get("model") or "?"
                    bump(by_model, (prov, model), u, ts)
                    bump(by_class, classify(prov, model), u, ts)
        except Exception as ex:
            print("跳过(读取失败):", os.path.basename(path), ex, file=sys.stderr)

    empty = new_b()
    grand = dict(empty)
    for b in by_class.values():
        for k in grand:
            grand[k] += b[k]
    paid = by_class.get("PAID", dict(empty))
    free = by_class.get("FREE", dict(empty))
    other = by_class.get("OTHER", dict(empty))
    return {
        "dsh_home": dsh_home,
        "sessions": len(files),
        "days": sorted(days),
        "grand": grand,
        "by_class": {"PAID": paid, "FREE": free, "OTHER": other},
        "by_model": by_model,
        "by_day": dict(sorted(by_day.items())),
    }


def add_money(r: dict, cfg: dict) -> dict:
    lp = cfg.get("list_price") or DEFAULT_LIST_PRICE
    paid, free = r["by_class"]["PAID"], r["by_class"]["FREE"]
    rate = float(cfg.get("bill_rate") or DEFAULT_BILL_RATE)

    def list_cny(b, with_cache):
        v = (b["input"] * float(lp.get("input", 2.0))
             + b["output"] * float(lp.get("output", 3.0)))
        if with_cache:
            v += b["cacheR"] * float(lp.get("cache_read", 0.2))
        return v / 1e6

    paid_list = list_cny(paid, True)          # 自费：牌价（含缓存读低价）
    free_list = list_cny(free, False)         # 免费额度：牌价（校园 API 无缓存计价）
    paid_actual = cfg.get("paid_actual_cny")
    try:
        paid_actual = float(paid_actual) if paid_actual not in (None, "") else None
    except (TypeError, ValueError):
        paid_actual = None
    r["money"] = {
        "paid_cny_list": round(paid_list, 2),
        "paid_cny_actual": paid_actual,
        "paid_cny_date": cfg.get("paid_actual_date") or "",
        "paid_cny_bill": round(paid["total"] / 1e6 * rate, 2),
        "free_cny_list": round(free_list, 2),
        "free_cny_bill": round(free["total"] / 1e6 * rate, 2),
        "list_price": lp,
        "bill_rate": rate,
    }
    return r


# ---------------------------------------------------------------- 演示数据


def demo_result() -> dict:
    def b(n, i, o, cr=0):
        return {"n": n, "input": i, "output": o, "cacheR": cr, "cacheW": 0,
                "total": i + o + cr}

    by_model = {
        ("csu", "DeepSeek"): b(612, 41_200_000, 1_900_000, 188_000_000),
        ("csu", "GLM"): b(180, 9_400_000, 520_000, 31_000_000),
        ("deepseek-account", "deepseek-flash"): b(268, 24_600_000, 1_260_000, 96_000_000),
        ("aliyun-bailian", "deepseek-v4.1-flash"): b(54, 3_100_000, 210_000, 8_800_000),
    }
    by_day_raw = [("2026-11-01", 38_000_000), ("2026-11-02", 61_000_000),
                  ("2026-11-03", 118_000_000), ("2026-11-04", 84_000_000),
                  ("2026-11-05", 52_000_000), ("2026-11-06", 33_000_000),
                  ("2026-11-07", 27_000_000)]
    by_day = {}
    for d, t in by_day_raw:
        by_day[d] = {"n": 160, "input": int(t * .22), "output": int(t * .03),
                     "cacheR": int(t * .75), "cacheW": 0, "total": t}
    by_class = {}
    for key, cls in ((("csu", "DeepSeek"), "FREE"), (("csu", "GLM"), "FREE"),
                     (("deepseek-account", "deepseek-flash"), "PAID"),
                     (("aliyun-bailian", "deepseek-v4.1-flash"), "PAID")):
        tgt = by_class.setdefault(cls, {"n": 0, "input": 0, "output": 0, "cacheR": 0,
                                        "cacheW": 0, "total": 0})
        for k in tgt:
            tgt[k] += by_model[key][k]
    grand = {}
    for k in ("n", "input", "output", "cacheR", "cacheW", "total"):
        grand[k] = by_class["FREE"][k] + by_class["PAID"][k]
    return {
        "dsh_home": "（演示数据）",
        "demo": True,
        "sessions": 27,
        "days": [d for d, _ in by_day_raw],
        "grand": grand,
        "by_class": by_class,
        "by_model": by_model,
        "by_day": by_day,
    }


# ---------------------------------------------------------------- 渲染网页

RING = ('<svg viewBox="0 0 200 200" style="width:190px;height:190px">'
        '<circle cx="100" cy="100" r="80" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="16"/>'
        '<circle cx="100" cy="100" r="80" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" '
        'stroke-dasharray="{dash} {rest}" transform="rotate(-90 100 100)"/>'
        '<text x="100" y="97" text-anchor="middle" fill="#F5F5F7" font-size="27" font-weight="700">{center}</text>'
        '<text x="100" y="119" text-anchor="middle" fill="#98989D" font-size="12">{sub}</text></svg>')


def ring(color, pct, center, sub):
    dash = round(max(0.0, min(100.0, pct)) * 5.0265, 1)
    return RING.format(color=color, dash=dash, rest=round(502.65 - dash, 1),
                       center=center, sub=sub)


HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="1800">
<title>__TITLE__</title>
<style>
:root{--bg:#0A0A0C;--surface:#1C1C1E;--text:#F5F5F7;--dim:#98989D;
 --accent:#0A84FF;--paid:#636366;--radius:18px}
*{margin:0;box-sizing:border-box}
body{background:var(--bg);color:#F5F5F7;font-family:-apple-system,"SF Pro Display","PingFang SC","HarmonyOS Sans SC","Microsoft YaHei UI",sans-serif;padding:64px 24px;line-height:1.6;font-variant-numeric:tabular-nums}
.wrap{max-width:860px;margin:0 auto}
.meta{color:#98989D;font-size:13px;margin-bottom:16px}
h1{font-size:40px;font-weight:700;letter-spacing:-.5px}
.sub{color:#98989D;font-size:15px;margin:8px 0 40px}
.warn{background:rgba(255,159,10,.12);color:#FF9F0A;border-radius:14px;padding:16px 20px;font-size:14px;margin-bottom:28px}
.money-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:24px;margin-bottom:32px}
.money{background:var(--surface);border-radius:var(--radius);box-shadow:0 8px 30px rgba(0,0,0,.35);padding:32px}
.money .cap{color:#98989D;font-size:14px;margin-bottom:10px}
.money .num{font-size:42px;font-weight:700;letter-spacing:-1px;line-height:1.15}
.money .note{color:#98989D;font-size:13px;margin-top:8px}
.card{background:var(--surface);border-radius:var(--radius);box-shadow:0 8px 30px rgba(0,0,0,.35);padding:32px;margin-bottom:32px}
h2{font-size:22px;font-weight:700;margin-bottom:28px}
.rings{display:flex;gap:48px;flex-wrap:wrap;justify-content:space-around;align-items:flex-start}
.ring-box{text-align:center}
.legend{margin-top:14px;font-size:13px;color:#98989D;text-align:left}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin:0 6px 0 0;vertical-align:middle}
.bar-row{display:grid;grid-template-columns:250px 1fr 90px;align-items:center;gap:14px;margin-bottom:16px}
.bar-row .name{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-row .name .tag{font-size:11px;color:#98989D;margin-left:8px}
.track{height:10px;border-radius:999px;background:rgba(255,255,255,.06);overflow:hidden}
.fill{height:100%;border-radius:999px}
.bar-row .val{font-size:14px;color:#98989D;text-align:right;white-space:nowrap}
.day{display:flex;align-items:flex-end;gap:40px;height:210px}
.day .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:8px}
.day .bar{width:100%;max-width:130px;border-radius:14px 14px 6px 6px;background:var(--accent);opacity:.9}
.day .v{font-size:15px;font-weight:600}
.day .l{font-size:13px;color:#98989D}
.note{color:#98989D;font-size:13px;line-height:1.9;margin-top:8px}
.note b{color:#F5F5F7;font-weight:600}
.foot{color:#5A5A5E;font-size:12px;margin-top:24px}
</style>
</head>
<body>
<div class="wrap">
  <div class="meta">__TITLE__ · 生成于 __GEN__ · 数据源 __SRC__（本机解压，零 API 花费）</div>
  <h1>Token 总账</h1>
  <div class="sub">__SPAN__</div>
  __WARN__
  <div class="money-grid">
    <div class="money">
      <div class="cap">白嫖价值 · 免费额度（__FREE_LABEL__）</div>
      <div class="num" style="color:var(--accent)">¥__FREE_CNY__</div>
      <div class="note">__FREE_TOK__ token，按官方牌价折算</div>
    </div>
    <div class="money">
      <div class="cap">__PAID_CAP__</div>
      <div class="num">¥__PAID_CNY__</div>
      <div class="note">__PAID_TOK__ token · 牌价 __PAID_LIST__</div>
    </div>
    <div class="money">
      <div class="cap">白嫖率（按钱算）</div>
      <div class="num">__FREE_MONEY_PCT__%</div>
      <div class="note">全部服务牌价 ≈ ¥__ALL_CNY__，你只掏了零头</div>
    </div>
  </div>

  <div class="card">
    <h2>两个视角</h2>
    <div class="rings">
      <div class="ring-box">
        __RING_MONEY__
        <div class="legend">
          <div><i style="background:#0A84FF"></i>免费 ¥__FREE_CNY__（牌价）</div>
          <div><i style="background:#636366"></i>自费 ¥__PAID_LIST__（牌价__PAID_ACTUAL_TXT__）</div>
        </div>
      </div>
      <div class="ring-box">
        __RING_TOKEN__
        <div class="legend">
          <div><i style="background:#0A84FF"></i>免费 __FREE_TOK__</div>
          <div><i style="background:#636366"></i>自费 __PAID_TOK__</div>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>按模型</h2>
    __MODEL_BARS__
  </div>

  <div class="card">
    <h2>按天</h2>
    <div class="day">__DAY_COLS__</div>
  </div>

  <div class="note">
    <b>口径说明</b>：统计范围 __D0__ ~ __D1__，共 __NREQ__ 次请求、__TOTAL_TOK__ token（输入 __IN_TOK__ + 输出 __OUT_TOK__ + 缓存读 __CACHE_TOK__）。
    免费额度按官方无缓存牌价折算（校园 API 不计缓存）；自费牌价按输入 ¥__LP_IN__/百万、缓存读 ¥__LP_CR__/百万、输出 ¥__LP_OUT__/百万。
    只统计 DSH 会话日志里的调用：网页版对话、标题生成等不经日志的调用未计入。
  </div>
  <div class="foot">dsh-token-bill v__VER__ · MIT · 只读本机日志，不联网</div>
</div>
</body>
</html>"""


def render_html(r: dict, cfg: dict, generated_at: str) -> str:
    g = r["grand"]
    paid = r["by_class"]["PAID"]
    free = r["by_class"]["FREE"]
    m = r["money"]
    days = r["days"]
    span = "%s ~ %s" % (days[0], days[-1]) if days else "没有数据"

    free_cny = m["free_cny_list"]
    paid_list = m["paid_cny_list"]
    actual = m["paid_cny_actual"]
    all_cny = free_cny + paid_list
    free_money_pct = round(free_cny / all_cny * 100, 1) if all_cny > 0 else 0.0
    free_tok_pct = round(free["total"] / (g["total"] or 1) * 100, 1)

    if actual is not None:
        paid_cap = "实际自费（账号后台实付）"
        paid_num = "%.0f" % actual
        save_pct = round((1 - actual / all_cny) * 100, 1) if all_cny > 0 else 0.0
        paid_actual_txt = "；实付 ¥%g%s" % (actual, (" · " + m["paid_cny_date"]) if m["paid_cny_date"] else "")
    else:
        paid_cap = "自费（牌价估算）"
        paid_num = "%.0f" % paid_list
        save_pct = round(free_cny / all_cny * 100, 1) if all_cny > 0 else 0.0
        paid_actual_txt = "（填 token-bill.config.json 里的 paid_actual_cny 可显示真实实付）"

    rows = sorted(r["by_model"].items(), key=lambda kv: -kv[1]["total"])
    mx = max((v["total"] for _, v in rows), default=1) or 1
    labels = {"FREE": "免费", "PAID": "自费", "OTHER": "未知"}
    bars = ""
    for (prov, model), v in rows:
        cls = classify_cached(cfg, prov, model)
        color = "#0A84FF" if cls == "FREE" else "#636366"
        w = max(1.5, v["total"] / mx * 100)
        bars += ('<div class="bar-row"><div class="name">%s / %s'
                 '<span class="tag">%s</span></div>'
                 '<div class="track"><div class="fill" style="width:%.1f%%;background:%s"></div></div>'
                 '<div class="val">%s</div></div>'
                 % (prov, model, labels.get(cls, "其他"), w, color, fmt(v["total"])))
    if not bars:
        bars = '<div class="note">还没有读到任何模型请求。</div>'

    dmax = max((b["total"] for b in r["by_day"].values()), default=1) or 1
    day_cols = ""
    for d, b in r["by_day"].items():
        h = max(6, b["total"] / dmax * 150)
        day_cols += ('<div class="col"><div class="v">%s</div>'
                     '<div class="bar" style="height:%.0fpx"></div><div class="l">%s</div></div>'
                     % (fmt(b["total"]), h, d[5:]))
    if not day_cols:
        day_cols = '<div class="note">还没有按天的数据。</div>'

    warn = ""
    if r.get("demo"):
        warn = '<div class="warn">这是 <b>--demo</b> 演示数据，不是真实账单。</div>'
    elif r["sessions"] == 0:
        warn = ('<div class="warn">没找到 DSH 会话日志：<b>%s</b>。'
                '装了 DeepSeek Harness 并用过之后再来跑一次；'
                '日志在别处就用 <b>--dsh-home 路径</b> 指过来。</div>' % r["dsh_home"])

    lp = m["list_price"]
    html = (HTML_TMPL
            .replace("__TITLE__", APP_NAME)
            .replace("__GEN__", generated_at)
            .replace("__SRC__", "%s/sessions 全部会话日志" % r["dsh_home"])
            .replace("__SPAN__", "%s · %s 个会话 · %s 次请求" % (span, r["sessions"], "{:,}".format(g["n"])))
            .replace("__WARN__", warn)
            .replace("__FREE_LABEL__", "、".join(cfg.get("free_providers") or []))
            .replace("__FREE_CNY__", "%.0f" % free_cny)
            .replace("__FREE_TOK__", fmt(free["total"]))
            .replace("__PAID_CAP__", paid_cap)
            .replace("__PAID_CNY__", paid_num)
            .replace("__PAID_LIST__", "%.0f" % paid_list)
            .replace("__PAID_ACTUAL_TXT__", paid_actual_txt)
            .replace("__PAID_TOK__", fmt(paid["total"]))
            .replace("__FREE_MONEY_PCT__", "%.0f" % save_pct)
            .replace("__ALL_CNY__", "%.0f" % all_cny)
            .replace("__RING_MONEY__", ring("#0A84FF", free_money_pct, "¥%.0f" % free_cny,
                                           "免费价值占比（按牌价）"))
            .replace("__RING_TOKEN__", ring("#0A84FF", free_tok_pct, fmt(g["total"]),
                                            "token 合计（蓝=免费）"))
            .replace("__MODEL_BARS__", bars)
            .replace("__DAY_COLS__", day_cols)
            .replace("__D0__", days[0] if days else "-")
            .replace("__D1__", days[-1] if days else "-")
            .replace("__NREQ__", "{:,}".format(g["n"]))
            .replace("__TOTAL_TOK__", fmt(g["total"]))
            .replace("__IN_TOK__", fmt(g["input"]))
            .replace("__OUT_TOK__", fmt(g["output"]))
            .replace("__CACHE_TOK__", fmt(g["cacheR"]))
            .replace("__LP_IN__", str(lp.get("input")))
            .replace("__LP_CR__", str(lp.get("cache_read")))
            .replace("__LP_OUT__", str(lp.get("output")))
            .replace("__VER__", __version__))
    return html


_CLASSIFY = None


def classify_cached(cfg, prov, model):
    global _CLASSIFY
    if _CLASSIFY is None:
        _CLASSIFY = make_classifier(cfg.get("free_providers"))
    return _CLASSIFY(prov, model)


# ---------------------------------------------------------------- 打开网页


def open_in_browser(path: str) -> bool:
    """交给默认浏览器打开。pythonw / 打包后的 exe 没有控制台，失败原因写进日志。"""
    import subprocess
    url = "file:///" + path.replace("\\", "/")
    errs = []
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception as ex:
        errs.append("startfile: %s" % ex)
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, url])
                return True
            except Exception as ex:
                errs.append("edge: %s" % ex)
    try:
        import webbrowser
        if webbrowser.open(url):
            return True
        errs.append("webbrowser: 返回 False")
    except Exception as ex:
        errs.append("webbrowser: %s" % ex)
    try:
        with open(os.path.join(base_dir(), "open-error.log"), "a", encoding="utf-8") as fh:
            fh.write("%s -> %s\n" % (url, " | ".join(errs)))
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- 主流程


def print_summary(r, cfg):
    g, m = r["grand"], r["money"]
    paid, free = r["by_class"]["PAID"], r["by_class"]["FREE"]
    span = "%s ~ %s" % (r["days"][0], r["days"][-1]) if r["days"] else "-"
    line = "=" * 46
    print(line)
    print("%s（本机 DSH 会话日志）" % APP_NAME)
    print(line)
    print("会话 %d 个 | 时间 %s" % (r["sessions"], span))
    print("请求 %s 次 | 总计 %s token（输入%s 输出%s 缓存读%s）"
          % (fmt(g["n"]), fmt(g["total"]), fmt(g["input"]), fmt(g["output"]), fmt(g["cacheR"])))
    print("免费额度(%s): %s token | 牌价价值 ≈ ¥%s"
          % ("、".join(cfg.get("free_providers") or []), fmt(free["total"]), m["free_cny_list"]))
    if m["paid_cny_actual"] is not None:
        print("自费: %s token | 实付 ¥%g（%s）| 牌价 ¥%s"
              % (fmt(paid["total"]), m["paid_cny_actual"],
                 m["paid_cny_date"] or "账号后台查", m["paid_cny_list"]))
    else:
        print("自费: %s token | 牌价估算 ¥%s（想显示真实实付就填 %s 的 paid_actual_cny）"
              % (fmt(paid["total"]), m["paid_cny_list"], CONFIG_NAME))
    print("提示: 网页版对话、标题生成等不经 DSH 日志的调用不在统计里。")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dsh-token-bill", description="DSH token 总账（本机解压会话日志，零花费）")
    ap.add_argument("--html", nargs="?", const="", metavar="输出路径", help="生成网页账单（默认 %s）" % DEFAULT_OUT)
    ap.add_argument("--out", metavar="输出路径", help="同 --html")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    ap.add_argument("--no-open", action="store_true", help="只生成，不打开浏览器")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON（不生成网页）")
    ap.add_argument("--print", dest="print_only", action="store_true", help="只在控制台打印摘要")
    ap.add_argument("--demo", action="store_true", help="用假数据渲染演示页")
    ap.add_argument("--dsh-home", metavar="路径", help="DSH 目录（默认 %%DSH_HOME%% 或 ~/.dsh）")
    ap.add_argument("--config", metavar="路径", help="指定配置文件")
    ap.add_argument("--init-config", action="store_true", help="写一份默认配置文件后退出")
    ap.add_argument("--paid", type=float, metavar="金额", help="账号后台真实实付金额（元）")
    ap.add_argument("--paid-date", metavar="日期", help="查账单的日期，如 2026-11-05")
    ap.add_argument("--version", action="version", version="dsh-token-bill %s" % __version__)
    args = ap.parse_args(argv)

    cfg, cfg_path = load_config(args.config)
    if args.init_config:
        print("已写入配置文件：" + write_example_config(cfg, args.config or ""))
        return 0
    if args.dsh_home:
        cfg["dsh_home"] = args.dsh_home
    if args.paid is not None:
        cfg["paid_actual_cny"] = args.paid
    if args.paid_date:
        cfg["paid_actual_date"] = args.paid_date

    if args.demo:
        r = demo_result()
    else:
        dsh_home = cfg.get("dsh_home") or default_dsh_home()
        if not args.json and not args.print_only:
            print("正在统计 %s 的全部会话…" % os.path.join(dsh_home, "sessions"), flush=True)
        r = collect(dsh_home, cfg.get("free_providers"))
    r = add_money(r, cfg)
    if cfg_path:
        r["config_path"] = cfg_path

    out_path = args.out or (args.html if args.html else None)
    want_html = (not args.json and not args.print_only) or bool(out_path) or args.demo

    if args.json:
        out = dict(r)
        out["by_model"] = {"%s/%s" % (p, m): b for (p, m), b in r["by_model"].items()}
        out["config"] = cfg
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if args.print_only:
        print_summary(r, cfg)
        return 0

    if want_html:
        if not out_path:
            out_path = cfg.get("output") or DEFAULT_OUT
            if not os.path.isabs(out_path):
                out_path = os.path.join(base_dir(), out_path)
        html = render_html(r, cfg, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        out_abs = os.path.abspath(out_path)
        print_summary(r, cfg)
        print("网页账单：" + out_abs)
        if not args.no_open:
            ok = open_in_browser(out_abs)
            print("已交给默认浏览器打开" if ok else "浏览器打开失败，详见 open-error.log")
        return 0
    return 0


def _fix_console() -> None:
    """双击启动时控制台是 GBK 码页，而 Python 3.15 默认输出 UTF-8：不改就会乱码。"""
    try:
        import ctypes
        if sys.stdout is not None and sys.stdout.isatty():
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _hold(seconds: float) -> None:
    """双击运行时留点时间看结果（打包成 exe 才有意义）。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        import time
        if os.environ.get("DSH_TOKEN_BILL_NOHOLD"):
            return
        time.sleep(seconds)
    except Exception:
        pass


if __name__ == "__main__":
    _fix_console()
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\n出错了。把上面的内容截图发给 AI，然后按回车关闭。")
        except Exception:
            pass
        sys.exit(1)
    finally:
        _hold(4)
