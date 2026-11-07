# dsh-token-bill

把 **DeepSeek Harness（DSH）** 的会话日志算成一张离线网页账单：白嫖了多少 token、自费了多少、每天烧了多少。

> A tiny offline token-bill generator for DeepSeek Harness.
> It decompresses your local `~/.dsh/sessions/**` logs (zstd or plain), counts the tokens of
> every request, and renders one self-contained HTML page. **No network, no API calls, no telemetry.**

**不挑平台**：谁免费、谁自费不是写死的名单，而是「关键词 → 端点特征 → 待确认」三层判定，
所以学校换名字（`csu` / `CSU DeepSeek` / `api.chat.xxx.edu.cn`）、公司内网网关、
本机 ollama、阿里云百炼……都能各归各位；实在认不出的会**单独列出来让你一句话拍板**，
绝不悄悄给你算错账。

![预览](assets/screenshot.png)

*（上图是 `--demo` 假数据渲染的演示页：故意混了别的学校、公司内网网关和认不出来的 provider。）*

---

## 快速开始

### 方式一：下载压缩包（Windows，解压就能用）

1. 到本仓库的 [Releases](../../releases) 下载 `dsh-token-bill-v1.2.0-win64.zip`
2. **解压**（别在压缩包里直接双击），进 `dsh-token-bill` 文件夹
3. 双击 `dsh-token-bill.exe` → 同目录生成 `token-账单.html`，并用默认浏览器打开
4. 前提：这台机器上**装过 DSH 并且用过**（要有 `~/.dsh/sessions` 里的日志）

里面已经带了打包好的 Python 运行时，**不需要你自己装 Python**。
压缩包里同时附了源码 `token_bill.py` 和 `run-source.cmd`——**万一 exe 被系统安全策略挡住**（见下面的 FAQ），
装了 Python 的人双击 `run-source.cmd` 就能跑，不用再回来下载。

> 为什么是文件夹而不是单个 exe？试过 `--onefile` 单文件模式，在 Windows 11 build 26200 +
> PyInstaller 6.22 + Python 3.15 上启动时会 `Could not create temporary directory!`（换 %TEMP%、
> 换父进程都复现），文件夹模式没这个毛病，启动还更快、也不容易被杀软误判。

### 方式二：源码运行

```bash
# 需要 Python 3.14+（用的是标准库里的 compression.zstd）
python token_bill.py                 # 生成网页并打开
python token_bill.py --print         # 只在控制台打印摘要
python token_bill.py --doctor        # 自检：日志在哪、每个 provider 怎么判定的
python token_bill.py --json          # 输出机器可读 JSON
python token_bill.py --demo          # 用假数据渲染一张演示页（测试用）
```

Python 3.12 / 3.13 也能跑，但要额外装解压库：`pip install zstandard`。

---

## 它到底在算什么

| 项 | 说明 |
|---|---|
| 数据源 | `%DSH_HOME%\sessions\**\session*.{jsonl.zstd,jsonl.zst,jsonl,zstd}`（默认 `~/.dsh/sessions`） |
| 用量字段 | `assistant/message.data.usage`（每次模型请求）、`compaction/summary.data.usage`（每次上下文压缩） |
| 字段兼容 | DSH 原生 `inputTokens/outputTokens/cacheReadTokens`，也认 OpenAI 风格 `prompt_tokens/completion_tokens/prompt_tokens_details.cached_tokens` |
| 模型归属 | 取该请求之前最近一次 `request/context` 或 `request/header` 里的 provider/model |
| 免费价值 | 按官方无缓存牌价折算（输入 ¥2 / 输出 ¥3 每百万 token）——校园 / 公司 / 自建 API 一般不计缓存价 |
| 自费牌价 | 输入 ¥2 + 缓存读 ¥0.2 + 输出 ¥3 每百万 token |
| 自费实付 | **推荐手填**：账号后台的真实账单金额，比任何估算都准（见下面的配置） |

**不在统计范围内的**：网页版对话、DSH 自己生成的会话标题、任何不经 DSH 会话日志的调用。
装机之前的历史也无记录——这是一份「日志里有什么就算什么」的账。

---

## 它是怎么判断「免费 / 自费」的

没有写死的平台名单，靠四层依次判定（**免费优先**，因为算错成自费最让人难受）：

| 顺序 | 规则 | 例子 |
|---|---|---|
| ① | 命中配置里的 `free_providers` 关键词 | `csu`、`glm`、`ollama`、`localhost`、`公司` |
| ② | 命中配置里的 `paid_providers` 关键词 | `aliyun`、`openrouter`、`openai`、`deepseek-account` |
| ③ | provider 名像高校自建 API（内置 60+ 中国高校缩写） | `sjtucs`、`zju-llm`、`nwafu-ai`、`CSU DeepSeek` |
| ④ | 端点长得像学校 / 公司内网 / 本机自建 | `api.chat.hdu.edu.cn`、`llm-gateway.corp.internal`、`192.168.1.5` |
| ⑤ | 都不中 → **待确认**，不算钱，页面单独列出来 | `our-lab-llm`、老日志里没记 provider |

页面底部有一张「**每个 provider 是怎么判定的**」表，逐条写清命中哪条规则、算了多少 token——
你随时能验证它有没有冤枉你的某个平台。

实测覆盖的写法（都是 `--demo`/测试里跑过的）：

| provider 写法 | 判定 | 依据 |
|---|---|---|
| `csu` / `CSU DeepSeek` | 免费额度 | 命中关键词 `csu` |
| `api.chat.hdu.edu.cn` | 免费额度 | 端点像校园网关 |
| `sjtucs` / `zju-llm` / `nwafu-ai` | 免费额度 | 高校缩写 |
| `llm-gateway.corp.internal` / `company-llm` | 免费额度 | 像公司内网网关 |
| `ollama` / `lmstudio` / `localhost` | 免费额度 | 本机自建 |
| `aliyun-bailian` / `deepseek-account` / `openai` | 自费 | 命中商业平台关键词 |
| `our-lab-llm`（自定义名字） | 待确认 | 等你加一行配置 |

**认不出来的怎么办**（两条路，任选）：

1. 页面会把认不出的 provider 列出来，并给出一段可以直接粘贴的配置：
   把名字加进 `token-bill.config.json` 的 `free_providers`（学校 / 公司 / 自建）或 `paid_providers`（真花钱的平台）。
2. 懒得一个个挑：`dsh-token-bill --unknown free`（认不出的都当免费额度）或 `--unknown paid`。

> 想让我把你们学校 / 公司的写法加进内置规则？跑一下 `dsh-token-bill --rules`，
> 把输出的平台清单（**只有平台名，没有金额和 token 数**）贴到 issue 里就行。

---

## 配置（可选）

把 `token-bill.config.example.json` 复制成 `token-bill.config.json`，放在 exe / 脚本旁边：

```json
{
  "dsh_home": "",
  "output": "token-账单.html",
  "free_providers": ["csu", "glm", "edu", "公司", "ollama", "localhost"],
  "paid_providers": ["aliyun", "bailian", "openrouter", "openai", "anthropic", "deepseek-account"],
  "unknown_class": "skip",
  "list_price": { "input": 2.0, "cache_read": 0.2, "output": 3.0 },
  "bill_rate": 0.0401,
  "paid_actual_cny": null,
  "paid_actual_date": ""
}
```

| 字段 | 作用 |
|---|---|
| `dsh_home` | DSH 目录；留空则用 `%DSH_HOME%`，再退回 `~/.dsh` |
| `output` | 网页输出路径（相对路径按 exe / 脚本所在目录算） |
| `free_providers` | 哪些 provider / 模型算「免费额度」，大小写不敏感，子串匹配 |
| `paid_providers` | 哪些算「自费」，同样是子串匹配（**先查免费，再查自费**） |
| `unknown_class` | 认不出来的怎么处理：`skip`（默认，单独列出）/ `free` / `paid` |
| `list_price` | 官方牌价（元/百万 token），用来折算「这些调用如果按量付费值多少钱」 |
| `bill_rate` | 你实测的均价（元/百万 token），默认 4.01 分/百万 |
| `paid_actual_cny` | **你账号后台的真实实付金额**；填了它，页面上的「自费」就显示真钱而不是估算，白嫖率也跟着变准 |
| `paid_actual_date` | 上面那个金额是哪天查的 |

也可以不建配置文件，直接用命令行临时指定：

```
dsh-token-bill --paid 26.5 --paid-date 2026-11-05
dsh-token-bill --dsh-home D:\somewhere\.dsh
dsh-token-bill --unknown free
```

想生成一份配置模板：`dsh-token-bill --init-config`（它会顺便把你本机识别到的平台分好类，写进模板）。

---

## 命令行参数

| 参数 | 作用 |
|---|---|
| （无参数） | 生成网页 + 打开浏览器 + 打印摘要 |
| `--no-open` | 只生成，不打开浏览器 |
| `--out 路径` | 指定输出 html（等同 `--html`） |
| `--print` | 只在控制台打印摘要（含 provider 判定表） |
| `--doctor` | 自检：Python / 运行方式 / 日志在哪找到几个 / 每个 provider 怎么判定的 |
| `--rules` | 导出识别到的平台清单（只有平台名和判定结果，可安全分享） |
| `--unknown skip\|free\|paid` | 认不出来的 provider 怎么算 |
| `--json` | 输出 JSON（含 `by_model` / `by_day`） |
| `--demo` | 用假数据渲染演示页 |
| `--dsh-home 路径` | 指定 DSH 目录 |
| `--config 路径` | 指定配置文件 |
| `--init-config` | 写一份默认配置文件后退出 |
| `--paid 金额`、`--paid-date 日期` | 覆盖真实实付金额 / 日期 |
| `--version` | 版本号 |

---

## 常见问题

**页面上一片 0 / 提示没找到日志？**
先跑 `--doctor`，它会告诉你找过哪些目录、找到几个日志、格式是压缩还是纯文本。
这台机器没装 DSH，或者还没用它跑过对话时也会这样。日志在别的位置就用 `--dsh-home 路径` 指过去；
装在 Program Files 这种写不进去的地方，程序会自己把网页改存到「文档」目录并提示你。

**同学那边显示的是 `CSU DeepSeek`，能认出来吗？**
能。`csu` 是子串匹配，大小写不敏感，`CSU DeepSeek`、`csu-api`、`api.csu.edu.cn` 都命中。
学校名不带这些字母（比如自定义的 `our-lab-llm`）才会落到「待确认」，加一行配置就好。

**「白嫖」和「自费」分错了？**
① 先看页面底部那张判定表，它会写清为什么这么判；② 改配置里的 `free_providers` / `paid_providers`；
③ 或者干脆 `--unknown free`。

**公司 / 学校给的是「免费额度」不是「白嫖」，能改叫法吗？**
页面上这一档本来就叫「免费额度」，副标题写的是「学校 / 公司 / 本机自建的额度」。

**自费金额不对？**
页面上默认给的是**牌价估算**。真实金额去你 API 平台的账单页看，填进 `paid_actual_cny` 就准了。

**Windows Defender / 杀软报毒？**
PyInstaller 打包 exe 的老毛病（自解压行为容易被启发式盯上）。不放心就用源码方式跑，逻辑全在这一个 `token_bill.py` 里，一眼能看完。

**双击 exe 没反应，或者提示「应用控制策略已阻止此文件」？**
这是 Windows 自己的代码完整性策略挡住**没签名的 exe**，不是程序坏了。典型三条路：

1. 自己的电脑：设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制 → 智能应用控制 → 关闭。
   （⚠️ 智能应用控制**一旦关闭，除非重装系统否则打不开**，请自己权衡。）
2. 学校 / 公司统一下发策略（WDAC）的电脑：改不了，直接走源码方式——压缩包里就带着 `token_bill.py`
   和 `run-source.cmd`，装个 Python 双击即可。
3. 换台没开这个策略的电脑（大多数个人电脑默认是关的，所以同学那边多半能直接双击）。

> 这个坑是本地实测出来的：2026-11-07 之后，本机新编译的 exe 会被判
> `Code Integrity determined that a process ... violated code integrity policy (Event ID 3077)`，
> 而同目录下**早就跑过的 v1.0.0 exe 仍能正常运行**——说明程序本身没问题，是新文件还没有系统信誉分。

**会把我数据传到哪吗？**
哪都不传。整个过程就是「读本地日志 → 算 → 写一个 html」，没有网络代码，没有第三方依赖（源码方式只依赖 Python 标准库）。

**为什么不用 API 平台的账单接口？**
因为那要 key、要联网、还只能看到一家平台。会话日志包含所有 provider，离线、免费、一秒出结果。

---

## 自己打包

```cmd
build.cmd
```

或者手动（文件夹模式，推荐）：

```cmd
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onedir --console ^
  --name dsh-token-bill --icon "%CD%\assets\token-icon.ico" ^
  --hidden-import compression.zstd --hidden-import _zstd ^
  --distpath dist --workpath build --specpath build token_bill.py
```

产物在 `dist\dsh-token-bill\`，整个文件夹压缩一下就是发行包。
想要单文件就把 `--onedir` 换成 `--onefile`——但在部分机器上会撞上
`Could not create temporary directory!`（见上面的说明），发布前记得先在自己机器上双击试一次。

---

## 设计取舍与踩坑（真实记录）

这些东西都是踩出来的，写下来给下一个折腾的人省时间：

- **判定规则不能写死名单**：第一版把「免费」写成 `["csu","glm"]`，换个学校、换个公司网关立刻被算成自费。改成
  「关键词 → 高校缩写 → 端点特征 → 待确认」四层之后，认不出来的会明确列出来而不是默默算错——
  会算错的工具比不会算的工具更糟。
- **数据源选日志而不是账单 API**：账单一要 key、二要联网、三只覆盖一家平台。DSH 的会话日志里本来就记着每次请求的 `usage`，本地解压就能算全，零花费、零隐私风险。
- **日志格式不止一种**：不同 DSH 版本可能写 `.jsonl.zstd`、`.jsonl.zst`，也可能是不压缩的 `.jsonl`。只认一种的话，别人电脑上就是「一片 0」，所以按后缀分派读取。
- **时间戳是秒级 epoch，不是 ISO 字符串**：第一版直接 `str(ts)[:10]` 当日期，结果「按天」图上写着 `1793682070`。要同时兼容字符串、秒、毫秒三种。
- **`compression.zstd` 要 Python 3.14+**：这是标准库里的 zstd，3.12/3.13 上不存在，会 `ModuleNotFoundError`。所以代码里留了 `zstandard` 第三方包的回退路径，两条路都能读。
- **PyInstaller 的 `--icon` 相对路径会被解析到 `--specpath` 目录下**：写成 `--icon assets\x.ico` 会报 `build\assets\x.ico not found`，必须给绝对路径。
- **`.cmd` 启动器必须纯 ASCII**：cmd 按 OEM 码页（GBK）解析批处理文件，UTF-8 中文会被拆坏报「不是内部命令」。所以所有中文都在 `.py` 里，`.cmd` 里只有英文。
- **双击控制台乱码**：Python 3.15 默认输出 UTF-8，而双击时控制台是 GBK 码页，要自己 `SetConsoleOutputCP(65001)`。
- **exe 旁边不一定写得进去**：放在 `Program Files` 或只读盘上时，写 html 会失败，所以加了「退回家目录文档」的兜底。
- **想让它定时自动重算**：注册计划任务时务必关掉 `DisallowStartIfOnBatteries`（默认开着，笔记本上任务会永远卡在 Queued）。
- **网页自动刷新**：生成的页面带 `<meta http-equiv="refresh" content="1800">`，配合每小时/每两小时重算的计划任务，挂在那儿就是一块实时仪表盘。

---

## License

[MIT](LICENSE)
