# 衍生品交易报告合规审查工作台

这是一个面向求职作品集展示的个人 RegTech 产品原型。项目把 OTC 衍生品交易报告规则、ANNA-DSB UPI 产品定义、UTI/LEI 标识符校验、CFTC/EMIR/MAS 监管路径和事件合约分类边界整合成一条可复现的数据审查流程。

核心展示入口是中英文 dashboard：

```text
dashboard/dashboard.html
```

## 产品定位

这个原型回答一个监管科技产品问题：

> 当传统 OTC 衍生品、数据质量缺陷和事件合约类新型风险转移工具混在同一组合中时，合规系统如何同时给出字段校验、报告范围判断和监管结论？

目标用户包括：

- 金融机构交易报告、合规运营和监管变更团队
- RegTech / SupTech 产品经理和解决方案顾问
- 需要解释 UPI、UTI、LEI、报告范围和产品分类边界的风险管理人员

核心价值：

- 把原始交易记录转成可审计的监管判断链路
- 区分数据质量、报告范围和最终监管结论，避免把所有问题都压成一个 `overall_status`
- 对 T026-T028 事件合约单独建模，展示传统 OTC 报告基础设施面对预测市场/事件合约时的可见性缺口
- 通过 dashboard 和结构化 JSON/CSV 同时支持产品演示、技术审查和监管论证

## 快速体验

```bash
cd <项目目录>
python tools/prepare_data.py
python tests_smoke.py
python run_compliance_check.py --input data/processed/trades.json --regimes CFTC,EMIR
```

项目主要依赖 Python 标准库；`requirements.txt` 保留为环境说明。如需确认环境，可运行：

```bash
python -m pip install -r requirements.txt
```

然后直接打开：

```text
dashboard/dashboard.html
```

如需通过本地 URL 查看：

```bash
python -m http.server 8000
```

访问：

```text
http://localhost:8000/dashboard/dashboard.html
```

dashboard 内置 Plotly 资源，离线也可以打开。
页面右上角支持中文 / English 切换，四个全屏视图会沿用同一语言设置。

## 展示流程

1. 进入 `dashboard/dashboard.html`，先看顶部 KPI：总交易数、数据质量不合规记录、事件合约数量和发现项数量。
2. 查看“合规热力图”，识别每笔交易在解析、UPI、LEI、UTI、时间戳、货币、保证金和监管规则上的状态。
3. 查看“规则频次”，区分真正的字段/标识符错误和单独展示的报告范围判断。
4. 查看“资产类别分布”，比较 Rates、FX、Equity、Credit、Commodities 与 EventContract 的风险结构。
5. 查看“事件合约分类边界”，重点解释 T026、T027、T028 为什么不能被普通 OTC parser 粗暴归为失败。
6. 通过全屏视图链接分别打开热力图、规则频次、资产分布和分类边界，演示同一套审查结果的不同查看方式。

## 项目结构

```text
src/                         规则引擎、解析、UPI、合规检查、分类分析和输出逻辑
config/product_aliases.json  产品标签归一化配置
data/raw/trades.json         不可变原始案例数据
data/processed/trades.json   运行时规范化交易数据
data/product_definitions/    ANNA-DSB Product-Definitions 本地副本
output/compliance_results.json  每笔交易的完整结构化结果
output/summary.json          组合级摘要
output/findings.csv          扁平化发现项表
dashboard/dashboard.html     中英文产品原型主入口
tools/prepare_data.py        数据准备脚本
tests_smoke.py               核心规则和展示层文本审计测试
```

## 数据准备链路

`tools/prepare_data.py` 负责让项目自包含：

- 保留 `data/raw/trades.json` 作为原始事实层
- 写出 `data/processed/trades.json` 作为可复现运行层
- 复制或链接 ANNA-DSB Product-Definitions 到 `data/product_definitions`
- 写出 `data/data_manifest.json`，记录 raw / processed SHA-256 摘要

如果本地没有 ANNA-DSB 副本，可使用：

```bash
python tools/prepare_data.py --download
```

该命令会克隆 `https://github.com/ANNA-DSB/Product-Definitions.git`，因此需要联网。当前仓库已经包含所需产品定义，常规演示不需要重新下载。

## 引擎架构

主运行命令：

```bash
python run_compliance_check.py --input data/processed/trades.json --regimes CFTC,EMIR
```

处理链路：

```text
data/raw/trades.json
  -> tools/prepare_data.py
  -> data/processed/trades.json
  -> run_compliance_check.py
       -> 交易解析与业务一致性检查
       -> ANNA-DSB UPI 模板查找和 codeset 校验
       -> CFTC + EMIR 或 CFTC + MAS 监管规则检查
       -> 事件合约分类边界分析
  -> output/compliance_results.json + output/summary.json + output/findings.csv + dashboard/dashboard.html
```

`src/engine.py` 是稳定共享实现层，负责核心编排、解析、UPI 查找、合规判断、事件合约分类、摘要和输出写入。`src/module1_parser.py`、`src/module2_upi.py`、`src/module3_compliance.py`、`src/module4_classification.py` 和 `src/reporting.py` 是轻量 wrapper，用来保持模块边界清晰，不复制业务逻辑。

当前支持 CFTC、EMIR 和 MAS。默认组合是 CFTC/EMIR；MAS 保留为新加坡 booking/trading nexus 的替代分析路径：

```bash
python run_compliance_check.py --input data/processed/trades.json --regimes CFTC,MAS
```

EMIR 与 MAS 在本项目中是产品原型级规则实现：覆盖 required field、null margin 和相关 scope 判断，不声称替代完整生产级监管申报系统。

## 关键产品设计

- 原始事实和引擎结论分离：`declared_parse_status` 是输入事实，`engine_parse_status` 是引擎生成结果。
- `overall_status` 为兼容字段保留；主展示改用 `data_quality_status`、`reporting_scope_status` 和 `regulatory_conclusion` 三维结果。
- EventContract 交易 T026-T028 被视为分类边界案例，而不是普通 parser failure。
- `NOT_REPORTABLE` 不等于干净或低风险；T027 虽然不在选定 CFTC/EMIR OTC 路径内，仍存在 LEI、UTI、USDC settlement 和 UPI taxonomy 可见性缺口。
- UPI template mapping 和 data caveat 与实质合规发现分开展示，避免 deterministic normalization 淹没真实风险。
- `XAU` 按 ANNA-DSB currency codeset 视为有效；`GBP-LIBOR-BBA` 是 legacy benchmark warning 而不是 hard failure。

## 输出资产

```text
output/compliance_results.json  每笔交易的完整结构化结果
output/findings.csv             可筛选的发现项明细
output/summary.json             组合级摘要
dashboard/dashboard.html        中英文产品原型主入口
```

## 测试

```bash
python tests_smoke.py
```

测试覆盖：

- LIBOR warning、XAU validity、partial timestamp/date、null margin failure
- LEI check digit、UTI namespace/suffix、EventContract T026-T028 处理
- CFTC/EMIR 与 CFTC/MAS 两条监管路径
- 展示层中文产品定位和旧版项目痕迹审计

## 产品路线图

下一阶段可以把这个原型继续推进为更完整的 RegTech 产品：

- 增加规则版本管理：按 jurisdiction、effective date 和 rule pack 组织规则。
- 增加审查工作流：为每条 finding 加入 owner、review status、evidence 和 remediation note。
- 增加完整 UPI request builder：从稀疏交易字段构造 DSB request payload，再做 schema/enum 校验。
- 增加场景化 explainability：为每个风险结论生成面向合规、业务和监管的不同解释层。
- 增加 API 服务层：把当前 batch pipeline 包装成可被前端或企业系统调用的审查服务。
- 增加事件合约监控视图：按 event、venue、settlement currency、counterparty identifier 和 jurisdiction 汇总监管可见性缺口。

## 边界说明

这是个人独立研究和产品原型，不是法律意见，也不是生产级交易报告替代系统。项目代码与示例数据用于个人研究和作品集展示，重点是展示如何把监管规则、数据质量、产品分类和可解释输出组合成一套可审计的 RegTech 工作台。

`data/product_definitions/` 来源于 ANNA-DSB Product-Definitions，本地副本仅用于 UPI 模板与 codeset 查验演示。第三方数据、标准和监管材料归其原始发布方所有。
