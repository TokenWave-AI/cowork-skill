# cowork-model-report：用 agent 逐题分析 SWE-CoWork 轨迹，产出每个模型的论文级报告

## 它做什么

核心是**每道题起一个 codex agent 分析这道题的轨迹**，一共两轮。100 道题就是 100 + 100 个 agent，并发跑。

- **第 1 轮，盲审**（`skills/cowork-trajectory-analysis`）：agent 只能看到这道题的轨迹，看不到分数。
  它按 16 个维度（10 项策略、6 项协作）打分，并给出策略阶段、关键情节、提前停止判断和质量问题。
  每条结论都引用轨迹原文的行号。
- **第 2 轮，失败诊断**（`skills/cowork-failure-diagnosis`）：agent 能看到这道题的测试结果、需求表、
  题目完整规格和第 1 轮报告。对每条没通过的需求，它在轨迹里追完整条链：最先看到 → 提问 → 回复 →
  决定 → 写代码 → 自测 → 交付说明怎么写的。然后判断丢在哪个阶段、属于哪种机制、哪一步本可以避免，
  并核对交付说明有没有虚报。最后写出意外的职场表现发现，以及一段可以直接放进论文的案例。

控制器（`scripts/stages/review_runner.py`）负责几件事：
- 并发调度，遇到 429 自动减半并发。
- 每份报告的引用都用程序逐条核对；不合格就让 agent 修，最多修 2 次。
- 断了能接着跑。

每个 agent 都在独立沙箱里运行（`scripts/agent_runtime.py`）：
- 只能写自己的目录，shell 不能联网。
- 看不到其他题；第 1 轮还看不到分数。
- API key 不进 agent 的环境。

agent 的结果再和脚本统计合并，产出与论文同口径的分析。每条轨迹里能取到的信息都尽量留在报告目录里，
读报告的人不用再去找原始轨迹。

**论文用的部分**
- `statistics.json`：报告、LaTeX 和图里的全部数字都只来自这一个文件。
- `report.md` 第 1–11 节按论文结构组织：结果、开销、需求获取、四阶段丢失归因、协作指标、
  16 维行为 rubric、停止、职场基本功（交付声明 / 延期追问 / 提问时机 / 测试规则）、分层、
  案例候选、数据覆盖与对账。
- `paper_rows.tex`：可直接粘贴进论文 Table main / cost / attrib / ask / strata 的行。
  `tables/*.tex` 是论文同格式的完整表，`figures/*.pdf` 是论文同名的 4 张图。
- `scripts/cross_model.py`：把多个模型的 `statistics.json` 合并成多模型表和图。

**论文之外的完整细节**
- `report.md` 第 12 节：遥测分布（工具调用与错误、重试、观测到的 token、读取的看板/文档/会话数、
  重复调用）、逐工具用量、失败节点的失败类别、补丁规模、审查者标注的情节/阶段/质量问题，以及
  逐题总表（每题一行，可点进该题档案）。
- `runs/NNN/`：每题一份档案。
  - `RUN.md`：身份、结果、遥测，逐需求表（持有人、是否拿到、提问次数、节点通过数、丢失阶段、
    交付说明怎么写的），失败节点及 grader 输出，延期线程，发出的问题，工具用量，补丁逐文件统计，
    审查者结论和 16 维评分。
  - `conversation.md`：按时间排列的全部同事往来，含发出的问题和收到的回复/通知全文，以及环境侧的
    披露、延期和通知记录和完整 sidecar 事件日志。
  - `transcript.md`：完整轨迹，包括助手文字、推理、每次工具调用的输入和完整返回。
  - 另有 `SOLUTION.md`（交付说明）、`model.patch` 和 `PATCH_STAT.csv`、`review.md`/`review.json`
    （审查报告全文）、`REQUIREMENTS.csv`、`NODES.csv`。
- `data/RUN_SUMMARY.csv`：逐题宽表，汇总所有逐题指标。
- `review/reviews/rows/NNN/report.{json,md}`：第 1 轮 agent 的报告；汇总在 `review/summary/`。
- `diagnosis/rows/NNN/report.{json,md}`：第 2 轮 agent 的报告；汇总在 `diagnosis/summary/`：
  - `DIAGNOSES.csv`：每条失败需求一行（阶段、机制、责任、交付说明是否属实、本可避免的那一步）。
  - `RUNS.csv`：每题的一句话结论和案例段落。
  - `FINDINGS.csv`、`REVISIONS.csv`、`SUMMARY.json`。
- `data/`、`telemetry/communication/`、`review/summary/`：各阶段的中间 CSV/JSONL。每个问题、
  回复、披露、通知链都在这里。

脚本是论文原有构建脚本的拷贝，只把路径和模型名参数化，统计口径不变。

## 本仓库不含的东西

仓库公开，所以以下内容不在仓库里，向维护者索取内部数据包：
- **题包级数据**（`--package`）：`requirement_links/NNN.json`（F2P 节点 → 需求 → 持有人）、
  `release101_tasks.json`（题目元数据，用于分层）、`repository_domains.json`。还有 Opus-5.5
  的回归数据：论文数字 `opus55_paper_numbers.json` 和交付声明盲审样本。
- **公开题包**（`--bundle`）和**评测轨迹**（`--campaign`）。
- **API key**：agent 轮次需要一个 Responses API 的地址和 key。

## 前置条件

- Python 3，需要 matplotlib、numpy、scipy、jinja2。
- 已按下面布局整理好的 campaign 目录；或者评测 status 目录加上能 SSH 到轨迹主机，由 prepare
  阶段整理。
- 内部数据包，放在任意位置，用 `--package` 指过去。

campaign 目录布局：

```
CAMP/manifests/manifest.json
CAMP/inputs/NNN/behavior/{INPUTS.json,actions.jsonl,evidence.jsonl,sidecar.jsonl,message_exposures.jsonl,submission/}
CAMP/inputs/NNN/outcome.json                     # score_snapshot 为权威分数
CAMP/inputs/NNN/raw-private/run/verifier/logs/   # 逐节点结果来源（恢复运行在 accepted-recovery-private/）
```

## 新模型约 5 条命令

```sh
SK=/path/to/cowork-skill
R="python3 $SK/scripts/run_model_report.py --model <显示名> --campaign <CAMP> \
   --bundle <公开题包目录> --package <内部数据包>/release101-20260928 --out <OUT>"

# 1) 拉取并规范化轨迹（只读 SSH；每题约 1–3 分钟，可断点续跑）
$R --stages prepare --prepare-args "--status-dir <评测 status 目录> --hosts-bundle <BUNDLE.json> --excluded-rows <无分题号>"

# 2) 全部非 LLM 阶段：telemetry → nodes → collab → basics → dossier → stats → report（99 题约 1 分钟）
$R

# 3) agent 环境（两轮共用）
export CMR_CODEX_BIN=<codex 可执行文件> CMR_REVIEW_BASE_URL=https://<api>/v1 CMR_REVIEW_API_KEY=<key> \
       CMR_REVIEW_PYTHON=<装了 jsonschema 的 python>

# 4) 第 1 轮盲审：每题一个 agent。先试 1–4 题、看报告，再全量
$R --stages review --review-rows 5 --review-concurrency 1
$R --stages review --review-concurrency 20
$R --stages review-merge,dossier

# 5) 第 2 轮失败诊断：每题一个 agent，同样先试再全量
$R --stages diagnose --review-rows 5 --review-concurrency 1
$R --stages diagnose --review-concurrency 20
$R --stages diagnose-merge,stats,report

# 6) 多模型对比
python3 $SK/scripts/cross_model.py <OUT_A> <OUT_B> ... --dest <DEST>
```

每个阶段做完要检查什么、怎么续跑，见 `SKILL.md`。所有输出都只写到 `--out`，campaign 和题包
只读。

agent 成本参考（第 1 轮，99 题，gpt-6-astra xhigh；第 2 轮单题量级相近）：
- 每次尝试中位约 26 分钟，平均每题约 1.8 次尝试。
- 并发 16–20 时全量约 3.5 小时。
- 单题中位输入约 710 万 token（绝大部分命中缓存），输出约 3.2 万。

## 输出大小

99 题的 `runs/` 约 190 MB，其中 `transcript.md` 约 120 MB。`--dossier-result-chars N` 会把每条
工具返回截成首尾 N 字符；N=3000 时约 150 MB。默认 0，即保留全部。

## 目录

```
SKILL.md                       Claude Code skill 运行手册（逐阶段命令、检查、续跑）
scripts/run_model_report.py    唯一入口，按阶段编排
scripts/common.py              参数与目录约定
scripts/stages/                各阶段脚本；build_dossiers.py 生成逐题档案
scripts/figures/               observed_style.py + model_figures.py（4 张图）
scripts/make_report.py         statistics.json → report.md / paper_rows.tex / tables / figures
scripts/cross_model.py         多模型合并
scripts/check_paper_numbers.py 回归检查：statistics.json 对照论文数字（数字文件在内部数据包）
templates/report.md.j2         报告模板
references/definitions.md      口径定义（附录 H + 实现细则）
references/paper_mapping.md    statistics.json 字段 → 论文表格单元格 / 句子
skills/cowork-trajectory-analysis/   第 1 轮 agent 的 skill（rubric、schema、validate_report.py）
skills/cowork-failure-diagnosis/     第 2 轮 agent 的 skill（机制表、schema、validate_diagnosis.py）
scripts/agent_runtime.py       单个 agent 的沙箱启动器
scripts/stages/review_runner.py      两轮共用的并发控制器（--phase review|diagnosis）
```

## 已知注意事项

1. **requirement links 只适用于对应题包。** 内部数据包里的 links 对应 20260928 修复包，同一题包
   上的任何模型都可直接复用。换题包或题目版本需要重建 links 和 `release101_tasks.json`。缺
   links 的题会列在报告第 11 节，不会被悄悄计为 0。
2. **交付声明分类器是关键词启发式。** 论文的盲审里，约三分之一"声称完成但测试失败"的样本在别处
   有保留或不是声明，所以 claimed-done 数字应视为上界，并同时报告 strict 和 broad 两种读法。
   新模型如需精度数字，要另做盲审，结果通过 `--claims-blind-check` 传入。
3. **同事调用失败分类被有意排除。** 论文不报告，报告里也不出现。
4. **逐节点对账要求精确相等。** 某题的 verifier 日志如果复现不出报告分数，该题整题记为
   unresolved，并从节点级分析和交付声明中排除。遇到新的日志格式时，在 `build_node_outcomes.py`
   的 `supplemental()` 里按题加规则，不要放宽相等条件。
5. **两轮都是模型标注。** 第 1 轮 rubric 没有人类一致性，Spearman 相关只用于探索。第 2 轮的
   归因和案例段落引用的证据是程序核对过的，但"为什么失败"仍然是 agent 的判断。写进论文前要抽查，
   尤其是 `stage_agrees=false` 的条目。
6. **本流水线不产出以下列。** Oracle-Spec、pass^k、token 总量和 κ 一致性需要额外实验，
   `paper_rows.tex` 中对应单元格保留为 `\tbd`。第 12 节的 token 数是轨迹里观测到的值，只能当下界。
7. **案例只是候选。** 案例按固定规则自动挑选，写进论文前必须看证据（`runs/NNN/`）。
