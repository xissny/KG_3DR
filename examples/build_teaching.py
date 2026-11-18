#!/usr/bin/env python3
"""创建完全虚构的教学语料；所有产物位于examples/workspace，绝不写入正式data。"""
from pathlib import Path
import argparse
import os
import sys
import json
import hashlib
ROOT=Path(__file__).resolve().parents[1]
WORKSPACE=ROOT/'examples/workspace'
os.environ['KG3DR_DATA_DIR']=str(WORKSPACE/'data')
os.environ['KG3DR_EXPERIMENT_DIR']=str(WORKSPACE/'experiments')
os.environ['KG3DR_PROJECT']='kg3dr-teaching'
sys.path.insert(0,str(ROOT))
import pymupdf as fitz
from src.common.storage import DATA, EXP, digest, now, read_json, stable_id, write_json
from src.papers.pipeline import build_paper_list, parse_pdfs, save_papers
from src.common.models import Candidate, ExtractionResponse
from src.review.service import validate_facts
from src.classification.task import evaluate_classification
from src.prediction.task import evaluate_prediction


def build(run_evaluation=True, import_neo4j=False):
    pdf_dir=DATA/'pdfs';pdf_dir.mkdir(parents=True,exist_ok=True)
    sentences_by_paper={}
    responses=ROOT/'examples/responses';responses.mkdir(exist_ok=True)
    for i in range(1,13):
        title=f'TEACHING ONLY - Synthetic Paper {i:02}'
        method=f'Teaching Method {i:02}'
        component='Global attention' if i<=6 else 'Pairwise attention'
        task='Camera estimation' if i<=6 else 'Depth estimation'
        dataset='Teaching Dataset A' if i%2 else 'Teaching Dataset B'
        sentences=[
            ('Paper',title,'PROPOSES','Method',method,f'{title} proposes {method} for this fictional teaching example.'),
            ('Method',method,'USES_COMPONENT','Component',component,f'{method} uses {component} as its principal component.'),
            ('Method',method,'EVALUATED_ON','Dataset',dataset,f'{method} is evaluated on {dataset} in the synthetic setup.'),
            ('Method',method,'SOLVES','Task',task,f'{method} solves the task of {task} in this fictional example.'),
            ('Method',method,'OUTPUTS','Representation','Teaching geometry',f'{method} outputs Teaching geometry in this artificial example.'),
        ]
        facts=[{'subject':{'type':a,'name':b},'relation':r,'object':{'type':c,'name':d},'quote':q,'page':1} for a,b,r,c,d,q in sentences]
        sentences_by_paper[title]=facts
        path=pdf_dir/f'Teaching_{i:02}.pdf'
        if not path.exists():
            document=fitz.open();page=document.new_page();page.insert_textbox(fitz.Rect(45,45,550,780),
                title+'\n\nSYNTHETIC EDUCATIONAL DATA. NOT A REAL RESEARCH PAPER.\n\n'+'\n\n'.join(s[-1] for s in sentences),fontsize=11)
            document.set_metadata({'title':title,'author':'Synthetic teaching fixture'});document.save(path);document.close()
        write_json(responses/f'teaching_{i:02}.json',{'facts':facts})
    papers=build_paper_list(pdf_dir)
    for paper in papers:
        paper.update(inclusion_reason='仅供代码学习的虚构样例，不计入正式语料',status='teaching')
    save_papers(papers)
    parse_pdfs()
    labels={}
    for paper in papers:
        response=ExtractionResponse.model_validate({'facts':sentences_by_paper[paper['title']]})
        rows=[]
        for fact in response.facts:
            rows.append({'id':'F_'+digest([paper['sha256'],fact.model_dump()])[:20],
                         'paper_id':paper['paper_id'],'pdf_sha256':paper['sha256'],
                         'section':'Teaching','candidate':fact.model_dump(),'status':'approved',
                         'reviewer':'教学样例作者（非正式论文审核）','note':'虚构事实','history':[],
                         'reviewed_at':now(),'created_at':now(),'prompt_version':'fixture-v1'})
        write_json(DATA/'candidates'/f"{paper['paper_id']}.json",rows)
        task=response.facts[3].object
        labels[paper['paper_id']]={'task_ids':[task.id],'verified':True,'reviewer':'教学样例作者'}
    validate_facts()
    graph=read_json(DATA/'approved_graph.json');graph['teaching']=True
    # 教学快照明确标识，正式 load_snapshot 不会读取这个目录。
    write_json(DATA/'graph_snapshot.json',graph)
    write_json(ROOT/'examples/teaching_snapshot.json',graph)
    write_json(DATA/'labels.json',labels)
    if import_neo4j:
        from src.graph.store import import_graph
        import_graph()
    if run_evaluation:
        classification=evaluate_classification();prediction=evaluate_prediction()
        write_json(ROOT/'examples/teaching_results.json',{'teaching':True,'classification':classification,'prediction':prediction})
    return {'workspace':str(WORKSPACE),'papers':len(papers),'nodes':len(graph['nodes']),'edges':len(graph['edges']),
            'notice':'全部为虚构教学数据，不能用于正式课程实验结论'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-evaluation',action='store_true')
    parser.add_argument('--neo4j',action='store_true',help='导入独立教学命名空间，不替换正式图谱')
    args=parser.parse_args()
    print(json.dumps(build(not args.no_evaluation,args.neo4j),ensure_ascii=False,indent=2))
