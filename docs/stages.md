# 逐阶段运行指南

所有命令在项目根目录、专用Conda环境中运行。每阶段先检查产物，再进入下一阶段。

| 阶段 | 输入 | 输出 | 检查方式 |
|---|---|---|---|
| 01清单 | data/pdfs/*.pdf | papers.json、papers.csv | 标题、发表年份、纳入理由是否正确 |
| 02解析 | 清单、PDF | parsed/Pxxx.json | pages/page/text是否对应原PDF；页码为PDF页序号 |
| 03抽取 | 分页文本、DeepSeek配置 | candidates/、cache/、failures/ | quote是否原文、关系是否作者方法而非基线 |
| 04核验 | 人工审核候选、aliases.json | approved_graph.json、validation.json | 所有正式关系有审核者、有效原文来源 |
| 05构图 | 审核快照 | Neo4j、graph_snapshot.json | Browser查询、重复导入数量不变 |
| 自动分类 | 正式快照、DeepSeek（推断可选） | automatic_classification.json、classification_taxonomy.json | 三维标签、路径与原文依据、版本与不足信息 |
| 06高级分类实验 | 快照、完整人工任务标签 | experiments/classification.json、模型 | 留一预测、类别支持数量、防泄漏报告 |
| 07预测 | 快照 | experiments/prediction.json | 目标组隐藏、平均秩、覆盖率 |
| 08生成 | Neo4j、问题、API | experiments/answers/ | 实际检索子图、事实引用与原文 |
| 09导出 | 快照和结果 | outputs/demo、outputs/graph | 断网双击HTML |
| 10材料 | 正式数据与实验 | 报告、PPT、PDF、讲稿 | 数量、分数与同版本实验一致 |

## 三元组数据例（教学）

```json
{
  "subject": {"type":"Method", "name":"Teaching Method 01"},
  "relation":"USES_COMPONENT",
  "object":{"type":"Component", "name":"Global attention"},
  "page":1,
  "quote":"Teaching Method 01 uses Global attention as its principal component."
}
```

`quote`先通过同页文本核对，再由人判断语义是否支持。跨页表格、公式和图片可能解析不完整；不要通过编写不存在的原文绕过校验，应人工检查并修正解析或选择真实可定位证据。

## 高级监督学习实验标签格式（自动分类无需填写）

```json
{"P001":{"task_ids":["task_标准实体ID"],"verified":true,"reviewer":"姓名","note":"已通读任务定义"}}
```

网页“高级实验 → 审核论文标签”提供可视化选择。未检查完整性时verified=false；关系缺失不能自动充当负标签。

## 后台任务

`/api/run`创建作业，`/api/jobs`查询。作业状态为queued/running/complete/failed/interrupted；失败不会删除已完成块缓存。默认串行处理，防止导入与抽取同时覆盖文件。终端脚本应手动避开网页任务。

## 缓存与版本

- API缓存键由服务、模型、提示、文本和用途计算。
- `--force`忽略缓存，可能产生额外费用。
- 正式图谱导入成功后才保存实验快照；事务失败保留旧图。
- 更改标题、别名、审核状态或原文后，要重新校验并导入。
- 修改论文清单并排除论文不会删除历史候选，但下一次构图不再纳入该论文来源。

## 抽取后看到重复三元组怎么办

同一“主体—关系—客体”可能在摘要、方法章节或多篇论文里出现。现在候选列表和候选图按标准三元组聚合：一条事实显示一次，展开后查看全部来源证据。每条证据保留独立ID、页码、审核状态和历史，不把旧审核结论自动用于新证据。

- 同一PDF、同页、同原文的重复抽取自动跳过（忽略大小写/空白差异）。
- 不同原文或不同页是不同证据，保留并挂在同一事实下。
- 大小写、字符宽度和多余空白自动归一；缩写、全称或不同措辞通过别名表显式确认。
- 不进行模糊字符串自动合并，避免把不同模型或组件混为一谈。
- 同一主体客体的不同关系，例如TRAINED_ON与EVALUATED_ON，仍分别保留。

只读统计：`python scripts/11_inspect_duplicates.py`。老候选数据无需重抽取、删除或迁移；刷新网页就能按事实分组。候选分组不修改已导入Neo4j；修改别名后需重新校验并导入，图谱版本会相应变化。

## 删除论文及关联记录

实时网页“论文管理”每行提供“删除”按钮。确认后，清理清单、项目内PDF、正文解析、候选证据和审核记录、该论文抽取缓存、任务标签及图谱证据。共用关系只移除该篇证据，其他论文仍支持的关系/实体保留；其他论文引用被删论文时，该文献实体可作为外部引用继续存在。

旧实验模型、回答、运行记录和导出报告/PPT/图谱移入备份，防止旧结果继续展示已删除内容。静态Demo的数据快照同步刷新，页面资源保留。之后请重新运行评测、导出和材料生成。

```bash
python scripts/12_delete_paper.py --paper-id P001
# 上一行仅说明；确实要删除时显式加--yes
python scripts/12_delete_paper.py --paper-id P001 --yes
```

- 运行中有后台任务时拒绝删除。
- 已导入图谱的论文要求Neo4j可用，否则不修改文件。
- 删除内容备份在`data/deleted/<论文ID_随机标识>/`，`manifest.json`记录原路径与备份路径，可用于恢复；没有一键恢复入口。
- 项目外部目录的PDF不会删除，只移除项目登记；墓碑记录防止重新扫描时自动纳入。重新上传表示重新纳入，追加到当前论文清单末尾。
- 当前清单连续编号为P001至Pn。删除后，后面的论文编号依次前移；重新添加的论文使用当前末尾的下一个编号。内容哈希和证据ID保持不变，删除历史中的旧编号只表示当时的编号。
- 正式与教学数据分别处理；删除操作不会清理另一命名空间。

## 按论文和审核状态查看

“知识抽取与图谱”中的“三元组与证据审核”支持两个独立筛选条件：

- 论文下拉框：全部论文或指定论文。
- 审核标签：待审核、已通过、已拒绝，默认待审核。

标签旁数字表示当前论文范围的证据数量。同一三元组可以有不同论文、不同审核状态的证据，因此它可能分别出现在多个标签中；每个标签只展示相应证据。表头和行内全选只选择当前筛选结果，避免批量审核其他论文。

图谱上方的“选择要展示的论文”支持多选、全选和全不选。勾选后即时只保留所选论文来源的关系及证据，公共实体保留为共享节点。论文选择会保留到刷新后，教学图与正式图分开记录。

该勾选仅影响展示，不改变论文纳入状态、已有审核结果、Neo4j全量数据或应用任务的训练范围。选择“复制所选论文 Neo4j 查询”，可在Neo4j Browser粘贴运行，查看对应论文来源的关系。三论文局部案例也仅从勾选范围中寻找。

终端或外部客户端可使用：`GET /api/candidates?grouped=true&paper_id=P001&status=pending`；不提供筛选参数时仍返回原有全量数据。重新导出静态Demo后，也能离线使用相同筛选。

## 连续论文编号

例如删除P002后，原P003变为P002、原P004变为P003。解析文件、候选证据、任务标签、Neo4j节点与来源、API缓存和静态展示一起迁移；不会仅因编号变化重新调用DeepSeek。

旧编号可能在当前清单中复用，因此不能将P001视为永久身份。论文内容哈希保持不变，页面编辑/删除请求用哈希校验，防止旧页面操作错论文。编号变化后请刷新并重新勾选论文。

修复历史空号：`python scripts/13_renumber_papers.py`预览，增加`--yes`实际执行。已导入Neo4j时要求数据库在线；迁移前备份至`data/renumbered/`，失败回滚。旧实验、生成回答和导出材料归入备份，重新评测/导出。

## 清除运行记录与查看输出

运行记录右上角的“清除已结束记录”清理全部已完成、失败和中断的记录，以及`data/jobs/`中的对应输出副本。排队和运行中的任务保留，清除不会取消任务，也不会删除论文、审核、图谱、DeepSeek缓存或`experiments/`结果。该操作不会自动执行，需点击按钮。

页面每4秒轮询任务状态，运行记录按任务ID更新已有节点；展开“查看此阶段输出”后会保持展开和内部滚动位置，手动收起也会保持。静态Demo为只读，不提供服务器历史清理。

接口：`DELETE /api/jobs`，返回清理数量`cleared`及保留活跃任务数`kept_active`。回归验证：`python setup/check_job_history.py`，使用虚构记录，不清除用户真实历史。

## 类别体系版本回溯

自动分类的类别更新保留`experiments/classification_taxonomy_history/`不可变快照。页面“类别历史与恢复”可查看/比较/恢复；恢复生成新的操作记录，保留原版本，不覆盖图谱与论文结果。历史类别来自旧图谱时提示差异，论文结果按图谱、类别与内容哈希检查是否需要重跑。升级前仅能把现有体系建立为基线，无法追补已覆盖版本。历史类别快照跨论文删除及编号变更保留。


## 证据问答三类任务

输入与输出、检索与评价见 README“证据问答”及 [评价规范](evaluation.md)。网页与阶段 8 CLI 共用 `answer_question`，旧请求默认 `qa`；`summary` / `review` 仅须提供非空 `paper_ids`，不要求问题或实体。只有 `qa` 的 `paper_ids=[]` 表示全部正式入图论文。

请求通过 `/api/run` 的 `stage=ask` 提交，新增 `task_type`、`entity_ids`、`paper_ids`；`qa` 的 `question` 承载问题；`summary` / `review` 根据所选论文和内置指令直接生成，忽略残留问题及实体，不需要填写问题框。返回任务记录，交互结果分别写入 `experiments/generation_qa_latest.json`、`generation_summary_latest.json`、`generation_review_latest.json`，通过 `results.generation_by_task` 返回；保留 `generation_latest.json` 兼容旧入口。所有运行保存在 `experiments/answers/`；评测标记 `is_evaluation=true`，不覆盖三类交互输出。`answer.claims` 保持旧格式兼容并新增结论 ID；`answer.sections` 通过结论 ID 组织章节，`answer.suggestions` 保存建议、依据结论 ID、推理和待验证问题；`context.scope` 记录实际范围和截断状态。

题库继续使用 `/api/questions`，新增任务类型、实体范围、论文范围、`reference_points`、`should_abstain`；旧题缺省 `qa`。人工评价使用 `/api/generation-review`，保留版本时间戳校验；`manual` 与 `baseline_manual` 对应相同量表，汇总结果新增 `by_task` 与 `baseline`。删除论文或重新编号后，相关题目会迁移引用或标记待核对，旧结果和生成缓存按既有生命周期处理。

正式验收前，必须填写真实实体和人工参考内容并完成 18 题人工评价。仓库中的模拟测试及题目模板不构成正式研究结果。
