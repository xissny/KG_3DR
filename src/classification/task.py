"""阶段 6：可读的留一交叉验证；没有足够金标准就返回缺口而非虚构分数。"""
from __future__ import annotations
import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from src.classification.features import build_features, feature_graph
from src.common.storage import DATA, EXP, digest, now, read_json, write_json
from src.graph.store import load_snapshot


def label_draft(snapshot: dict) -> dict:
    """根据已审核 SOLVES 关系生成草稿；缺少关系不等于负例，仍需人工确认完整性。"""
    result = {}
    for paper_id in snapshot.get('paper_ids', []):
        methods = {e['target'] for e in snapshot['edges'] if e['source'] == paper_id and e['relation'] == 'PROPOSES'}
        tasks = {e['target'] for e in snapshot['edges'] if e['relation'] == 'SOLVES' and e['source'] in methods | {paper_id}}
        result[paper_id] = {'task_ids': sorted(tasks), 'verified': False, 'reviewer': '', 'note': ''}
    return result


def evaluate_classification() -> dict:
    snapshot = load_snapshot()
    labels = read_json(DATA / 'labels.json', {})
    papers = [p for p in snapshot['paper_ids'] if labels.get(p, {}).get('verified') and labels[p].get('reviewer')]
    tasks = sorted({task for paper in papers for task in labels[paper]['task_ids']})
    eligible, gaps = [], []
    for task in tasks:
        positive = sum(task in labels[p]['task_ids'] for p in papers)
        negative = len(papers) - positive
        if min(positive, negative) >= 5:
            eligible.append(task)
        else:
            gaps.append({'task_id': task, 'positive': positive, 'negative': negative, 'required': '正负例均至少5篇'})
    if not eligible:
        result = {'status': 'insufficient_data', 'verified_papers': len(papers), 'gaps': gaps,
                  'message': '需要人工确认完整任务标签，且至少一个类别正负例均达5篇。',
                  'graph_version': snapshot['version'], 'time': now()}
        write_json(EXP / 'classification.json', result)
        return result
    graph = feature_graph(snapshot)
    y = np.array([[int(task in labels[p]['task_ids']) for task in eligible] for p in papers])
    modes = {}
    for mode in ['majority', 'one_hop', 'two_hop']:
        predictions = np.zeros_like(y)
        scores = np.zeros(y.shape, dtype=float)
        hops = 1 if mode == 'one_hop' else 2
        feature_rows = [build_features(graph, paper, hops) for paper in papers]
        # 显式循环展示训练/测试隔离，便于学习交叉验证。
        for test_index in range(len(papers)):
            train_indices = [i for i in range(len(papers)) if i != test_index]
            train_y = y[train_indices]
            if mode == 'majority':
                probability = train_y.mean(axis=0)
            else:
                vectorizer = DictVectorizer(sparse=True)
                train_x = vectorizer.fit_transform([feature_rows[i] for i in train_indices])
                test_x = vectorizer.transform([feature_rows[test_index]])
                probability = []
                for column in range(len(eligible)):
                    model = LogisticRegression(max_iter=1000, random_state=42)
                    model.fit(train_x, train_y[:, column])
                    probability.append(float(model.predict_proba(test_x)[0, 1]))
                probability = np.array(probability)
            scores[test_index] = probability
            predictions[test_index] = probability >= 0.5
        modes[mode] = {
            'micro_f1': float(f1_score(y, predictions, average='micro', zero_division=0)),
            'macro_f1': float(f1_score(y, predictions, average='macro', zero_division=0)),
            'per_class': [{'task_id': task, 'f1': float(f1_score(y[:, i], predictions[:, i], zero_division=0)),
                           'positive': int(y[:, i].sum()), 'negative': int((1-y[:, i]).sum())} for i, task in enumerate(eligible)],
            'cases': [{'paper_id': paper, 'gold': y[i].tolist(), 'prediction': predictions[i].tolist(),
                       'scores': scores[i].tolist(), 'correct': bool(np.array_equal(y[i], predictions[i]))} for i, paper in enumerate(papers)],
        }
    # 全量拟合供单篇演示；评测分数只来自上面的留一预测。
    vectorizer = DictVectorizer(sparse=True)
    x = vectorizer.fit_transform([build_features(graph, p, 2) for p in papers])
    models = []
    for index in range(len(eligible)):
        models.append(LogisticRegression(max_iter=1000, random_state=42).fit(x, y[:, index]))
    EXP.mkdir(parents=True, exist_ok=True)
    joblib.dump({'vectorizer': vectorizer, 'models': models, 'tasks': eligible, 'paper_ids': papers,
                 'graph_version': snapshot['version'], 'labels_version': digest(labels)}, EXP / 'classification.joblib')
    result = {'status': 'complete', 'graph_version': snapshot['version'], 'labels_version': digest(labels),
              'time': now(), 'tasks': eligible, 'papers': papers, 'gaps': gaps, 'modes': modes,
              'leakage_check': {'task_nodes_removed': True, 'all_solves_edges_removed': True,
                                'text_not_used': True, 'vectorizer_fit_within_fold': True},
              'limitations': '小样本留一评测方差较大；同源或方法系列论文可能高度相关，应结合逐例结果解释。'}
    write_json(EXP / 'classification.json', result)
    return result


def classify_paper(paper_id: str) -> dict:
    snapshot = load_snapshot()
    path = EXP / 'classification.joblib'
    if not path.exists():
        raise ValueError('请先运行分类评测，生成正式模型')
    fitted = joblib.load(path)
    if fitted['graph_version'] != snapshot['version'] or fitted['labels_version'] != digest(read_json(DATA / 'labels.json', {})):
        raise ValueError('图谱或标签已变化，请重新运行分类评测')
    if paper_id not in snapshot['paper_ids']:
        raise ValueError('论文不在当前图谱')
    features = build_features(feature_graph(snapshot), paper_id, 2)
    x = fitted['vectorizer'].transform([features])
    return {'paper_id': paper_id, 'graph_version': snapshot['version'],
            'in_training_set': paper_id in fitted['paper_ids'],
            'note': '全量模型演示不作为独立测试分数；正式结果请看留一评测。',
            'features': features, 'predictions': [{'task_id': task, 'score': float(model.predict_proba(x)[0, 1])}
                                               for task, model in zip(fitted['tasks'], fitted['models'])]}
