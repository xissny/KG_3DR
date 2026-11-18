"""交付物生成：报告/PPT/讲稿来自同一数据版本，不用教学分数填充正式结果。"""
from __future__ import annotations
from html import escape
import json
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfgen import canvas
from src.common.storage import DATA, EXP, ROOT, now, read_json

BLUE = '315DF4'
INK = '17243A'
FONT = 'STSong-Light'


def data_context():
    graph = read_json(DATA / 'graph_snapshot.json', {'nodes': [], 'edges': [], 'evidence': [], 'version': None})
    papers = read_json(DATA / 'papers.json', [])
    results = {name: read_json(EXP / f'{name}.json') for name in ['classification','prediction','generation_evaluation']}
    # 不将旧图谱评测误当成当前实验结果。
    stale = []
    for name, result in list(results.items()):
        if result and result.get('graph_version') != graph.get('version'):
            stale.append(name)
            results[name] = None
    return graph, papers, results, stale


def slides_content(graph, papers, results):
    n_papers = len([p for p in papers if p.get('included', True)])
    status = '当前无正式图谱；等待论文、密钥、抽取与人工审核。' if not graph['edges'] else f"图谱版本：{graph['version'][:16]}"
    classification = results['classification']
    prediction = results['prediction']
    generation = results['generation_evaluation']
    class_text = '尚无有效分类评测结果；需完整人工标签及足够正负样本。'
    if classification and classification.get('status') == 'complete':
        score = classification['modes']['two_hop']
        class_text = f"二跳特征 Micro-F1={score['micro_f1']:.3f}；Macro-F1={score['macro_f1']:.3f}。"
    pred_text = '尚无正式关系预测结果。'
    if prediction and prediction.get('path_model', {}).get('mrr') is not None:
        m = prediction['path_model']
        pred_text = f"MRR={m['mrr']:.3f}；Hits@3={m['hits_at_3']:.3f}；覆盖率={m['coverage']:.3f}。"
    gen_text = '尚无人工审核后的生成结果。'
    if generation and generation.get('metrics'):
        gen_text = '人工评测指标：' + json.dumps(generation['metrics'], ensure_ascii=False)
    return [
        ('前馈式三维重建论文知识图谱', ['从论文到事实，从联系到洞察', 'DeepSeek · Neo4j · 分类 / 预测 / 生成', status]),
        ('研究问题与技术范围', ['以 VGGT 等前馈式三维重建方法为核心。','排除 NeRF、3DGS 等路线；不训练三维重建模型。','目标：有证据地连接论文、方法、任务和技术组件。']),
        ('论文语料与筛选依据', [f'当前正式纳入论文：{n_papers} 篇；课程要求不少于20篇。','检查主题相关性、全文可得性和可追溯性。','合并预印本与正式版本，人工核对元数据与筛选依据。']),
        ('系统与分阶段流程', ['PDF → 论文清单 → 分页正文 → DeepSeek 候选事实','人工审核 → Neo4j → 三类应用 → 评测与展示','每个阶段独立脚本；网页与终端调用相同代码。']),
        ('本体与关系建模', ['实体：论文、方法、组件、任务、表示、数据集、指标。','关系：提出、采用、解决、输出、训练于、评测于、使用指标、引用。','类型约束保证结构合法，人工核验保证事实有依据。']),
        ('DeepSeek 抽取与人工审核', ['先用3篇试抽取，固定提示与术语规范。','每条候选必须带原文、页码和来源；校验证据存在。','缓存、重试、断点续跑；审核记录与修改历史留存。']),
        ('图谱规模与质量', [f"实体 {len(graph['nodes'])}；关系 {len(graph['edges'])}；证据 {len(graph['evidence'])}。",'正式关系均需审核者与来源；区分训练/评测数据。','另选不少于5篇全文复核，记录错误及遗漏；尚未执行时不能声称通过。']),
        ('Neo4j 图谱可视化', ['按实体类型着色，按关系类型解释联系。','搜索与邻域展开避免全图拥挤。','点击关系查看论文原文和页码；Neo4j Browser 提供可复现查询。']),
        ('局部关联案例', ['从正式图谱选择至少3篇论文，展示共享组件或研究任务。','共享特征不能直接解释为方法继承。','当前无正式数据时，仅可演示独立教学样例，不能当作论文结论。']),
        ('分类方法与防泄漏', ['多标签逻辑回归；多数类、一跳、二跳特征对比。','全局移除任务节点与标签关系，不使用标题、摘要或证据文本。','按论文留一；每折仅在训练数据拟合特征词表。']),
        ('分类结果与错误分析', [class_text,'每类至少5篇正例、5篇负例；不足则报告缺口。','分析正确/错误案例和小样本方差；全量模型演示不算独立测试。']),
        ('关系预测方法与防泄漏', ['隐藏“方法使用组件”关系，按论文和方法分组移除等价目标。','路径分数：二跳路径数 + 0.5 × 三跳路径数。','候选来自训练图谱；频率为基线；并列采用平均秩。']),
        ('预测结果与局限', [pred_text,'报告 filtered MRR、Hits@1/3 与候选覆盖率。','未知关系不等于负事实；新组件无法预测；建议需再次核验。']),
        ('基于图谱的生成流程', ['问答选择模板与实体；主题总结和研究综述只需选择论文。','从正式 Neo4j 检索事实；总结与综述汇集所选论文的核验事实，逐结论引用来源。','建议标记为推断并提供依据；最多300条事实，截断时说明范围。']),
        ('生成评价与对照', [gen_text,'18道题：问答、主题总结、方向综述各6题，包含证据不足案例。','相同量表人工评价A/B输出；按任务报告正确率、引用、要点覆盖与综合质量。']),
        ('HTML Demo 演示路径', ['上传PDF并生成清单 → 点击抽取 → 审核并导入Neo4j。','分别切换分类、预测、生成页面，运行并查看分析。','静态快照可离线浏览；实时任务在当前服务器运行。']),
        ('局限与改进', ['小语料和标注缺失限制评测的稳定性。','抽取结构合法不代表语义正确，模型输出需要人工审核。','后续可扩大语料、增加独立标注与跨方法系列评价。']),
        ('成果与复现', ['代码、论文清单、图谱、HTML Demo、报告与可编辑PPT。','Conda、Java21、Neo4j 在项目内隔离部署。','保留模型、提示、数据与实验版本；所有分数来自实际运行。']),
    ]


def add_ppt_text(slide, x, y, w, h, text, size=20, color=INK, bold=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    for index, line in enumerate(text.split('\n')):
        p = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        p.text = line
        p.font.name = 'Noto Sans CJK SC'
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = RGBColor.from_string(color)
    return box


def make_ppt(slides, output):
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for index, (title, points) in enumerate(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string('F5F6F8')
        add_ppt_text(slide,.65,.35,11,.4,'3DR / KNOWLEDGE LAB',12,BLUE,True)
        add_ppt_text(slide,.65,1.05,12,1.1,title,30,INK,True)
        for j, point in enumerate(points):
            add_ppt_text(slide,.7,2.5+j*1.12,.45,.5,f'{j+1:02}',15,BLUE,True)
            add_ppt_text(slide,1.35,2.43+j*1.12,11.1,1.05,point,20)
        add_ppt_text(slide,.7,7,11,.3,'前馈式三维重建 · 课程项目 / 实验数据不足时明确保留状态',10,'788298')
        add_ppt_text(slide,12,7,.7,.3,f'{index+1:02}',10,BLUE)
        slide.notes_slide.notes_text_frame.text = '讲解建议：' + '；'.join(points)
    deck.save(output)


def make_slides_pdf(slides, output):
    pdf = canvas.Canvas(str(output), pagesize=(960,540))
    for index,(title,points) in enumerate(slides):
        pdf.setFillColor(colors.HexColor('#F5F6F8'));pdf.rect(0,0,960,540,fill=1,stroke=0)
        pdf.setFillColor(colors.HexColor('#315DF4'));pdf.setFont(FONT,11);pdf.drawString(48,503,'3DR / KNOWLEDGE LAB')
        style = ParagraphStyle('slide_title',fontName=FONT,fontSize=25,leading=34,textColor=colors.HexColor('#17243A'))
        para=Paragraph(escape(title),style);para.wrap(860,100);para.drawOn(pdf,48,421)
        for j,point in enumerate(points):
            y=334-j*81
            pdf.setFont(FONT,12);pdf.setFillColor(colors.HexColor('#315DF4'));pdf.drawString(50,y,f'{j+1:02}')
            p=Paragraph(escape(point),ParagraphStyle('point',fontName=FONT,fontSize=16,leading=25,textColor=colors.HexColor('#17243A')))
            _,height=p.wrap(790,80);p.drawOn(pdf,96,y+13-height)
        pdf.setFont(FONT,9);pdf.setFillColor(colors.HexColor('#788298'));pdf.drawString(48,23,'课程项目 · 与PPT共用内容；PDF采用独立排版');pdf.drawRightString(910,23,f'{index+1:02}')
        pdf.showPage()
    pdf.save()


def build_materials() -> dict:
    graph,papers,results,stale=data_context()
    output=ROOT/'outputs';output.mkdir(exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    slides=slides_content(graph,papers,results)
    make_ppt(slides,output/'project_slides.pptx')
    make_slides_pdf(slides,output/'project_slides.pdf')
    notes=['# 项目答辩讲稿','',f'生成时间：{now()}','数据不足时请先补充真实论文和评测，再生成提交版。','']
    for i,(title,points) in enumerate(slides,1):
        notes += [f'## 第{i}页：{title}','', '；'.join(points),'']
    (output/'speaker_notes.md').write_text('\n'.join(notes),encoding='utf-8')
    report=['# 前馈式三维重建论文知识图谱项目报告','',f'生成时间：{now()}',
            f"图谱版本：{graph.get('version') or '尚未建立'}",'',
            '> 当前报告由实际产物生成。无正式论文或实验结果的部分保持待完成状态，不能直接作为已完成实验提交。','']
    for title,points in slides[1:]:
        report += ['## '+title,'']+[f'- {point}' for point in points]+['']
    report += ['## 论文清单','']
    for p in papers:
        report += [f"- {p['paper_id']}：{p['title']}，{p.get('year','')}，{p.get('venue','')}。筛选依据：{p.get('inclusion_reason') or '待填写'}"]
    if not papers: report+=['尚未载入正式PDF。']
    report += ['','## 关系与证据样例','']
    names={n['id']:n['name'] for n in graph['nodes']}
    evidence={e['id']:e for e in graph['evidence']}
    for edge in graph['edges'][:20]:
        report += [f"- {edge['id']}：{names[edge['source']]} — {edge['relation']} → {names[edge['target']]}"]
        for eid in edge['evidence_ids']:
            e=evidence[eid]
            report += [f"  来源：{e['paper_id']}，PDF第{e['page']}页。原文：{e['quote']}"]
    report += ['','## 实验复现与状态','',f'过期实验（未用于当前结论）：{stale or "无"}',
               '各阶段输入输出、命令与防泄漏检查见 docs/stages.md 和 docs/concepts.md。',
               '抽取错误与遗漏的复核记录见 data/quality_audit.json；未填写时不宣称已完成质量复核。',
               '', '## 实验产物摘要','']
    for name,result in results.items():
        summary={k:v for k,v in (result or {}).items() if k not in ['cases','modes']}
        report += [f'### {name}','',json.dumps(summary or {'status':'尚未运行'},ensure_ascii=False,indent=2),'']
    report += ['## 参考资料','','- 用户提供论文及图谱中的证据记录。',
               '- DeepSeek API：https://api-docs.deepseek.com/','- Neo4j 官方文档：https://neo4j.com/docs/']
    markdown='\n'.join(report)
    (output/'project_report.md').write_text(markdown,encoding='utf-8')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle('CN',fontName=FONT,fontSize=10,leading=17,wordWrap='CJK',spaceAfter=7))
    styles.add(ParagraphStyle('CNH',fontName=FONT,fontSize=15,leading=23,spaceBefore=14,spaceAfter=10))
    story=[]
    for line in report:
        if not line.strip():continue
        heading=line.startswith('#')
        text=line.lstrip('# ').removeprefix('> ')
        story.append(Paragraph(escape(text),styles['CNH'] if heading else styles['CN']))
    SimpleDocTemplate(str(output/'project_report.pdf'),rightMargin=45,leftMargin=45,topMargin=45,bottomMargin=45).build(story)
    return {'files':['project_report.md','project_report.pdf','project_slides.pptx','project_slides.pdf','speaker_notes.md'],
            'graph_version':graph.get('version'),'slides':len(slides),'status':'正式结果未齐时为待完善版本'}
