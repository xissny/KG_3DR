# 3DR Knowledge Lab · 前馈式三维重建知识图谱

面向课程学习的分阶段项目：**PDF → DeepSeek → 人工审核 → Neo4j → 分类 / 预测 / 生成**。

> 当前没有用户正式论文和 DeepSeek 密钥。教学数据均为虚构，独立存放在 `examples/`，不能充当不少于20篇论文的正式结果。生成的报告/PPT会如实标注缺失内容。

## 1. 当前服务器启动

在项目根目录执行：

```bash
conda activate "$PWD/.conda/kg3dr"
python setup/services.py start
python setup/services.py status
```

通过编辑器转发 **8000、7474、7687**：

- Demo：<http://localhost:8000>
- Neo4j Browser：<http://localhost:7474/browser/>
- Browser 连接：`bolt://localhost:7687`，用户 `neo4j`，密码在服务器项目 `.env` 中。

通过 SSH 也可转发：

```bash
ssh -L 8000:127.0.0.1:8000 -L 7474:127.0.0.1:7474 -L 7687:127.0.0.1:7687 <你的服务器登录地址>
```

`.env` 中填写 `DEEPSEEK_API_KEY`；官方接口使用 `DEEPSEEK_BASE_URL=https://api.deepseek.com`、`DEEPSEEK_MODEL=deepseek-flash`。旧模型名 `deepseek-chat` 已过时。随后重启 Demo，使进程重新读取环境：

```bash
python setup/services.py stop
python setup/services.py start
```

不要将 `.env` 放到前端或提交版本库。不需要密钥即可上传、解析、学习示例、浏览已保存结果。

## 2. 重新安装

已安装环境无需重复安装。新部署时，使用现有 Conda 的 Python 执行：

```bash
python setup/install.py
conda activate "$PWD/.conda/kg3dr"
```

安装脚本创建项目内 Python 3.11 环境，并下载 Python 包、Java21、Neo4j、Cytoscape.js、中文字体。不会修改系统 Java。环境错误时停止，不自动删除已有环境。

- 实际 Python 版本：`.conda/kg3dr/bin/python --version`
- 精确依赖记录：`requirements-lock.txt`
- 下载来源与 SHA256：`runtime/installation.json`
- 日志：`runtime/web.log`、`runtime/neo4j/logs/`

默认只监听服务器回环地址，通过转发访问。不要使用多个 Uvicorn worker：后台任务为单进程串行队列。

## 3. 网页操作

1. **论文管理**：选择 PDF → 上传 → 生成论文清单 → 编辑元数据和筛选依据。
2. **抽取与图谱**：先选3篇试抽取 → 检查候选原文 → 审核 → 校验 → 导入 Neo4j。
3. **分类**：选择论文 → 分类全部或所选论文 → 按主题、方法、任务浏览 → 查看图谱与原文依据。无需人工标签；监督学习评测放在高级实验区。
4. **预测**：运行补全评测 → 选择方法查看组件建议和路径。
5. **证据问答**：问题回答选择模板和实体或自行输入问题；主题总结与研究方向综述只需勾选论文后直接生成 → 逐结论查看事实、原文和 PDF 页码。高级评测提供题目维护及人工 A/B 评价表单。
6. **概览**：导出静态 Demo，生成报告和18页可编辑 PPT。

所有阶段产物均保留，刷新页面不丢后台任务。服务重启时未完成任务标为中断，重新提交可复用块级API缓存。

## 4. 终端分阶段运行

```bash
python scripts/01_build_paper_list.py --pdf-dir data/pdfs
python scripts/02_parse_pdfs.py --paper-list data/papers.csv
python scripts/03_extract_deepseek.py --paper-id P001
python scripts/04_validate_facts.py --export-review data/review.json
# 人工编辑review.json中的candidate/status/reviewer/note
python scripts/04_validate_facts.py --review-file data/review.json
python scripts/05_import_neo4j.py --approved-only
python scripts/06_run_classification.py --mode label-draft
# 人工编辑data/labels.json，确认完整标签后设置verified=true及reviewer
python scripts/06_run_classification.py --mode evaluate
python scripts/07_run_prediction.py --mode evaluate
python scripts/08_run_generation.py --question "<替换为真实方法名>采用哪些组件？"
python scripts/09_export_demo.py
python scripts/10_build_materials.py
```

网页“关系预测”支持全图扫描和单实体预测，可筛选六类缺失关系，查看路径、原文及PDF页码；预测仅提供待核验建议，不直接入图。原有组件关系评测保留在“高级评测与课程说明”中。

每个脚本支持 `--help`。网页与脚本使用相同模块；**不要在网页任务运行时通过终端同时修改同一数据目录**。

## 5. 不用API学习

```bash
python examples/build_teaching.py
# 可选：导入独立教学命名空间，仍不替换正式图谱
python examples/build_teaching.py --neo4j
```

教学目录：`examples/workspace/`。预存响应：`examples/responses/`。网页侧栏“打开独立教学图谱”只展示虚构关系，正式概览仍保持真实数量。Neo4j 教学查询将 `$project` 设为 `kg3dr-teaching`。

## 6. 成果

- `outputs/demo/index.html`：可双击静态版，不依赖 CDN。
- `outputs/graph/`：JSON、CSV、GraphML。
- `outputs/project_report.md`、`project_report.pdf`。
- `outputs/project_slides.pptx`、`project_slides.pdf`：18页，同源内容；PDF独立排版。
- `outputs/speaker_notes.md`：配套讲稿。

无正式论文和实验时，报告/PPT属于**待完善版本**。收到真实材料后重新运行，不能把教学分数填入正式结论。

测试：`python -m pytest -q`。进一步阅读 [代码阅读指南](docs/reading_guide.md)、[逐阶段指南](docs/stages.md)、[课程概念](docs/concepts.md)、[Cypher教程](docs/cypher.md)、[评价规范](docs/evaluation.md)。

## 7. 已验证内容

- 38项测试通过，包含真实Neo4j幂等导入、参数化检索、证据引用与按钮调度。
- 浏览器检查通过六个页面、31节点/60边的独立教学图、三论文局部案例、手机布局与断网静态HTML。
- 实际DeepSeek调用尚未验证：当前未提供密钥；HTTP请求与缓存通过模拟响应测试。
- `outputs/browser_check.json`保存浏览器检查结果，`outputs/screenshots/`保存截图。

可选重新执行网页验收：`python setup/check_browser.py`。脚本可复用服务器现有Chromium；在其他服务器上可通过`--executable`指定浏览器路径。


## 8. 删除论文

“论文管理”每行新增“删除”。确认后清理PDF、清单、解析、抽取审核、缓存与图谱证据，保留其他论文的共享事实。旧实验与导出成果移入本地备份并失效，请重新评测或导出。备份目录：`data/deleted/`。已导入图谱时要求Neo4j在线；有后台任务时拒绝删除。

终端：`python scripts/12_delete_paper.py --paper-id P001 --yes`。不加`--yes`只显示说明。测试使用隔离教学数据，未删除用户真实论文。详细范围与恢复备份说明见`docs/stages.md`。

## AI 检测同义实体与人工合并

在“知识抽取与图谱”完成三元组审核后，点击“实体合并审核 → AI 检测同义实体”。系统跨论文比较已纳入论文中已通过审核的方法、组件、任务、表示、数据集和指标；论文标题仍由论文管理维护。同义检测只提出建议，需人工核对来源证据。

每组可取消误选实体，搜索添加同类型的已通过实体，自由修改推荐标准名称，并保存草稿。填写审核者后逐组确认或拒绝。确认会保存别名并立即刷新审核区归组；之后仍需点击“校验事实”和“导入 Neo4j”更新正式图谱。原始三元组、原文证据、证据 ID 及其人工审核历史保留。标准名称若属于组外实体，必须先把该实体加入候选组。

检测复用现有 DeepSeek 配置与请求缓存，通过后台队列执行；单实体、重复 ID、未知实体等无效建议会逐组忽略，合法建议仍会保留，页面显示忽略数量；网络或整体响应格式失败时，可重新点击检测，继续未完成批次。此前因单实体建议失败的缓存结果也可直接重试处理，无需重新请求模型。“重新请求模型”可绕过模型请求缓存。实体或证据变化会使相关建议过期，可筛选“已过期”查看并重新检测；相同成员及上下文的已拒绝建议不重复推荐。草稿、合并与拒绝记录在刷新后保留，静态导出仅供浏览。

记录存储于 `data/entity_resolution.json`，确认的映射沿用 `data/aliases.json`；审核写入前备份至 `data/entity_resolution_backups/`，写入失败自动回滚。本期不提供一键拆分已合并实体。

验证：`.conda/kg3dr/bin/python -m pytest -q`；浏览器验收：`.conda/kg3dr/bin/python setup/check_entity_resolution.py`。使用隔离教学数据和模拟模型，不调用付费 API 或正式数据库。

## 按论文分开查看与审核

在“知识抽取与图谱”中：审核区用论文下拉框及“待审核/已通过/已拒绝”标签查看三元组；图谱区勾选论文即可即时筛选来源。共享关系保留所选来源的证据，勾选不会改变数据库或已有审核记录。可复制所选论文的Cypher到Neo4j Browser运行。

筛选回归：`python setup/check_paper_filters.py`。脚本使用虚构请求夹具，验证批量审核仅影响当前可见记录、共享证据隔离、刷新后保留选择及离线筛选，不需要启动服务或调用API。

## 连续编号

论文从P001依次编号，删除后后续编号自动前移，新论文追加到末尾。现有解析、三元组审核、来源证据和API缓存同步迁移，不需要重新抽取。旧实验结果归入本地备份，需重新评测。旧编号不是永久身份，操作时以最新页面和论文标题为准。

历史空号可运行`python scripts/13_renumber_papers.py --yes`修复（已导入图谱时Neo4j需在线）。

## 运行记录

右上角“清除已结束记录”可清理完成、失败和中断的历史，运行/排队任务及正式业务产物保留。“查看此阶段输出”在自动或手动刷新后保持展开和滚动位置。浏览器回归：`python setup/check_job_history.py`。

## 图谱自动分类（无需人工标注）

进入实时 Demo 的“论文分类”，点击“分类全部论文”或勾选后点击“分类所选论文”。系统先根据当前正式图谱整理研究主题、方法类型与任务类别，再结合明确关系及 DeepSeek 语义归纳生成多标签结果。无需填写正负例或审核者。

- 蓝色标签来自明确的任务关系，可能经过类别名称归并；紫色标签为基于图谱的推断；绿色为用户可选修订。
- 点击“查看依据”可查看分类解释、图谱路径、原文和PDF页码。引用归属已检查，不代表语义正确性已经人工确认。
- 左侧按类别筛选：同维度多选为并集，跨维度为交集；搜索与状态筛选可叠加。默认选择全部可分类论文，筛选不会自动改变选择，表头勾选框只影响当前可见论文。
- 结果逐篇保存、刷新不丢失；失败重试默认复用API缓存。缺少密钥或调用失败仍保留明确任务关系，未完成维度显示信息不足。无支持事实时不会强行归类。
- 类别体系保存后复用。图谱变化会提示版本过期；需要吸收新方向时点击“更新类别体系”，再重新分类。更新失败保留原体系。
- “可选：修订分类”单独保存个人选择，可恢复自动结果；不会修改图谱或旧实验标签。删除、重新编号会把相关实验及修订移入既有备份，避免编号复用导致错配。
- 旧的标签审核、逻辑回归训练和F1评测位于“高级实验”，其人工标签要求不影响自动分类。自动结果没有金标准时不输出F1或准确率。
- 导出静态Demo可离线查看、筛选及检查分类依据，不能运行模型或保存修改。

```bash
python scripts/14_classify_graph.py                         # 全部论文
python scripts/14_classify_graph.py --paper-id P001         # 指定论文，可重复参数
python scripts/14_classify_graph.py --update-taxonomy      # 显式更新类别
```

自动分类接口：`GET /api/classification/automatic`、`GET /api/classification/taxonomy`；通过`POST /api/run`的`automatic_classification`（可选`paper_ids`、`force`）或`classification_taxonomy`阶段运行。个人修订使用`PUT /api/classification/automatic/{paper_id}`，传入`category_ids`、`note`及当前`graph_version`、`taxonomy_version`、`paper_sha256`；同路径`DELETE`以版本参数恢复自动结果。

产物独立存放在`experiments/automatic_classification.json`、`classification_taxonomy.json`、`classification_corrections.json`，不会覆盖旧`classification.json`和模型。

回归：`.conda/kg3dr/bin/python -m pytest -q`；浏览器验收：`.conda/kg3dr/bin/python setup/check_automatic_classification.py`，使用隔离教学数据和模拟模型，不调用付费API。高级标签审核验收：`python setup/check_label_review.py`。

页面空闲时不重传完整图谱、不重绘页面；概览图复用布局，候选事实按需加载并使用系统字体。

## 类别体系历史、差异与恢复

在“论文分类 → 类别历史与恢复”中查看生成时间、模型、类别数量及当前版本。选择“对比基准”和“查看版本”可比较新增、删除、定义/父类别/关联实体的变化，并查看所选版本的完整类别。疑似合并、拆分和改名依据关联实体重叠提示，不能自动证明语义等价。

每次生成或更新类别均保存不可变快照；相同类别内容也可有不同操作记录。恢复会创建一条新记录，保留恢复前版本及来源，因此可以继续恢复到其他版本。恢复前显示仍匹配的论文、需要分类或重新分类的论文、可能过期的个人修订。恢复不请求模型、不回退图谱，也不覆盖分类或个人修订；兼容的旧结果会重新生效，其余提示重新分类。图谱与当前类别发生变化或后台任务运行时，拒绝过期恢复操作。

升级时将现有类别保存为基线，无法补回升级前已经被覆盖的版本。历史保存在`experiments/classification_taxonomy_history/`，删除论文及重新编号后仍保留；当前实验结果继续按既有机制归档。静态导出支持查看历史和差异，恢复需在实时Demo操作。

接口：`GET /api/classification/taxonomy/history` 列表；`GET /api/classification/taxonomy/history/{snapshot_id}` 详情及影响；`GET /api/classification/taxonomy/history/compare?before=...&after=...` 比较；`POST /api/classification/taxonomy/history/{snapshot_id}/restore` 传入`expected_current_snapshot_id`和`expected_graph_version`，防止覆盖晚到的新版本。类别内容版本`version`与操作记录`snapshot_id`分别使用内容哈希和独立记录ID。

验收：`python -m pytest -q tests/test_taxonomy_history.py`；`python setup/check_taxonomy_history.py`使用隔离数据与模拟模型检查浏览器恢复流程。

## 证据问答：问答、主题总结与研究方向综述

问题回答支持“选择问题模板 → 选择对应实体 → 自动组合问题”。方法比较须选择两个不同的方法；其他模板按类型选择方法、任务或组件。更换模板或实体会自动更新问题，完整问题仍可修改；“自行提问”保留自由输入。

页面三个任务分别说明输入、输出、图谱使用方式与评价标准。问题回答检索两跳事实，支持标准名及已确认别名，未选论文时默认全部正式入图论文。主题总结和研究方向综述无需问题或实体输入，至少勾选一篇论文后直接生成；后台汇集所选论文支持的全部核验事实，按技术维度组织。共享事实仅保留所选论文的来源证据。

三类任务分别保存最近一次交互结果，切换标签只展示当前任务的输出，刷新后仍可恢复；批量评测不会覆盖交互结果。每条结论可展开三元组、事实 ID、论文标题、PDF 页码和原文，也可查看本次检索子图。最多向模型提供 300 条事实，按关联方法轮流选取；超出时显示部分检索提示。引用结构合法仍需核对语义。综述中的未来建议单独标记为推断，附依据、推理及待验证问题；未收录不代表尚未研究。

命令行沿用 `--question`，新增 `--task-type qa|summary|review`、`--entity-ids` 与 `--paper-ids`（均可多值）。例如将下列占位值替换为真实 ID 后运行：

```bash
python scripts/08_run_generation.py --task-type review --paper-ids P001 P002
```

高级评测模板包含 18 题（三类各 6 题）。问答题填写问题与所需实体；总结和综述题选择论文即可。替换占位描述与 ID，并填写人工确认的参考事实和参考要点后，再运行评测。A/B 输出使用相同量表；未审核指标保持为空，按任务汇总正确率、引用准确率、证据支持率、要点覆盖率与质量评分。正式质量结论需要真实论文与人工评价，模拟测试结果不充当研究质量分数。

验证：`.conda/kg3dr/bin/python -m pytest -q`；独立浏览器验收：`.conda/kg3dr/bin/python setup/check_generation.py`（临时教学语料与模拟模型，不调用付费 API 或正式数据库）。
