"""分类特征：先清理所有目标标签，再计算邻域，不从标签反推特征。"""
from __future__ import annotations
from collections import Counter
import networkx as nx


def feature_graph(snapshot: dict) -> nx.Graph:
    """全局删除 Task、SOLVES 及证据文本，仅保留允许的结构信息。"""
    graph = nx.Graph()
    allowed = {'Paper', 'Method', 'Component', 'Representation', 'Dataset', 'Metric'}
    for node in snapshot['nodes']:
        if node['type'] in allowed:
            graph.add_node(node['id'], type=node['type'])
    for edge in snapshot['edges']:
        if edge['relation'] in {'PROPOSES', 'USES_COMPONENT', 'OUTPUTS', 'TRAINED_ON', 'EVALUATED_ON', 'USES_METRIC'}:
            if edge['source'] in graph and edge['target'] in graph:
                graph.add_edge(edge['source'], edge['target'])
    assert all(data['type'] != 'Task' for _, data in graph.nodes(data=True))
    return graph


def build_features(graph: nx.Graph, paper_id: str, hops: int = 2) -> dict[str, float]:
    """把邻域转换成稀疏词典。词典键是类型/实体 ID，绝不读取原文或任务名。

    一跳特征通常描述论文连接了哪些方法/数据集；二跳增加方法的组件等。
    DictVectorizer 会在每个训练折单独拟合，不把测试特征词表提前放入训练。
    """
    if paper_id not in graph:
        return {'bias': 1.0}
    distances = nx.single_source_shortest_path_length(graph, paper_id, cutoff=hops)
    counts = Counter()
    for node, distance in distances.items():
        if distance == 0:
            continue
        kind = graph.nodes[node]['type']
        if kind == 'Paper':
            continue
        counts[f'h{distance}:count:{kind}'] += 1
        counts[f'h{distance}:entity:{node}'] += 1
    return {'bias': 1.0, **{key: float(value) for key, value in counts.items()}}
