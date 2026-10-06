# cowork-model-report：任意模型的 SWE-CoWork 轨迹分析报告

## 它做什么

给定某个模型在 SWE-CoWork 上的一批 CoWork 运行，产出与论文同口径的分析，并把每条轨迹里能取到的
信息尽量都留在报告目录里。这样读报告的人不用再去找原始轨迹。

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
- `data/`、`telemetry/communication/`、`review/summary/`：各阶段的中间 CSV/JSONL。每个问题、
  回复、披露、通知链都在这里。

脚本是论文原有构建脚本的拷贝，只把路径和模型名参数化，统计口径不变。

## 本仓库不含的东西

仓库公开，所以以下内容不在仓库里，向维护者索取内部数据包：
- **题包级数据**（`--package`）：`requirement_links/NNN.json`（F2P 节点 → 需求 → 持有人）、
  `release101_tasks.json`（题目元数据，用于分层）、`repository_domains.json`。还有 Opus-5.5
  的回归数据：论文数字 `opus55_paper_numbers.json` 和交付声明盲审样本。
- **公开题包**（`--bundle`）和**评测轨迹**（`--campaign`）。
- **LLM 审查运行时**：`reviewer_runtime.py`、API key、带 jsonschema ≥ 4 的 Python。只有可选的
  review 阶段需要。

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

# 3)（可选，花钱）LLM rubric 审查：先 dry-run，再小批试审，最后全量
export CMR_REVIEWER_RUNTIME=<reviewer_runtime.py> CMR_REVIEW_PYTHON=<python with jsonschema>=4> CMR_REVIEW_API_KEY=<key>
$R --stages review --review-dry-run --review-rows 1,2
$R --stages review --review-concurrency 20

# 4) 合并审查结果，重出档案、统计和报告
$R --stages review-merge,dossier,stats,report

# 5) 多模型对比
python3 $SK/scripts/cross_model.py <OUT_A> <OUT_B> ... --dest <DEST>
```

每个阶段做完要检查什么、怎么续跑，见 `SKILL.md`。所有输出都只写到 `--out`，campaign 和题包
只读。

LLM 审查成本参考（99 题，gpt-6-astra xhigh）：
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
vendor/cowork-trajectory-analysis/   1.2 版行为标注 skill（rubric、schema、validate_report.py）
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
5. **rubric 是模型标注。** 没有人类一致性；Spearman 相关只用于探索。
6. **本流水线不产出以下列。** Oracle-Spec、pass^k、token 总量和 κ 一致性需要额外实验，
   `paper_rows.tex` 中对应单元格保留为 `\tbd`。第 12 节的 token 数是轨迹里观测到的值，只能当下界。
7. **案例只是候选。** 案例按固定规则自动挑选，写进论文前必须看证据（`runs/NNN/`）。
