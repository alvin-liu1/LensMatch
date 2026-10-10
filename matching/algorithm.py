"""Exact maximum cardinality, then minimum normalized cost (1e-6 precision)."""
from bisect import bisect_right
import networkx as nx
from .models import Config, Module


def differences(a: Module, b: Module):
    result = {key: abs(getattr(a, key) - getattr(b, key)) for key in ("aec", "rg", "bg")}
    result["score"] = abs(a.score - b.score) if a.score is not None and b.score is not None else None
    return result


def violations(a: Module, b: Module, config: Config):
    reasons = []
    if a.group != "pool" and a.group == b.group:
        reasons.append("同一 A/B 分组")
    if config.mode == "mixed-imu" and a.imu == b.imu:
        reasons.append("IMU 相同")
    for key, value in differences(a, b).items():
        if key == "score" and not config.use_score:
            continue
        if value is None:
            reasons.append(f"缺少 {key}")
        elif value > getattr(config, key + "_limit"):
            reasons.append(f"Δ{key} 超限")
    return reasons


def cost(a: Module, b: Module, config: Config):
    return sum(config.weights[k] * value / getattr(config, k + "_limit")
               for k, value in differences(a, b).items()
               if (k != "score" or config.use_score) and value is not None)


def solve(modules: list[Module], config: Config):
    # Sorting by exposure avoids checking pairs already outside the AEC limit.
    graph = nx.Graph()
    graph.add_nodes_from(range(len(modules)))
    ordered = sorted(range(len(modules)), key=lambda i: (modules[i].aec, modules[i].sn))
    values = [modules[i].aec for i in ordered]
    for pos, i in enumerate(ordered):
        end = bisect_right(values, modules[i].aec + config.aec_limit)
        for j in ordered[pos + 1:end]:
            if not violations(modules[i], modules[j], config):
                integer_cost = round(cost(modules[i], modules[j], config) * 1_000_000)
                graph.add_edge(i, j, weight=-integer_cost, cost=integer_cost)

    bipartite = config.mode == "mixed-imu" or any(m.group != "pool" for m in modules)
    pairs = []
    for nodes in sorted(nx.connected_components(graph), key=lambda ns: min(ns)):
        component = graph.subgraph(sorted(nodes))
        if component.number_of_edges() == 0:
            continue
        if not bipartite:
            pairs.extend(nx.max_weight_matching(component, maxcardinality=True))
            continue
        left = {i for i in nodes if (modules[i].group == "A" if modules[i].group != "pool" else modules[i].imu == 1)}
        matching = nx.bipartite.maximum_matching(component, top_nodes=left)
        count = len(matching) // 2
        flow_graph = nx.DiGraph()
        flow_graph.add_node("source", demand=-count)
        flow_graph.add_node("sink", demand=count)
        for i in sorted(nodes):
            flow_graph.add_node(i, demand=0)
            if i in left:
                flow_graph.add_edge("source", i, capacity=1, weight=0)
            else:
                flow_graph.add_edge(i, "sink", capacity=1, weight=0)
        for i, j, data in component.edges(data=True):
            if j in left:
                i, j = j, i
            flow_graph.add_edge(i, j, capacity=1, weight=data["cost"])
        flow = nx.min_cost_flow(flow_graph)
        pairs.extend((i, j) for i in sorted(left) for j, amount in flow[i].items() if amount and isinstance(j, int))

    normalized = []
    for i, j in pairs:
        a, b = modules[i], modules[j]
        if (b.group == "A" and a.group != "A") or (a.group == b.group == "pool" and
                ((config.mode == "mixed-imu" and b.imu == 1) or (config.mode == "no-imu" and b.sn < a.sn))):
            i, j = j, i
        normalized.append((i, j))
    normalized.sort(key=lambda pair: (modules[pair[0]].sn, modules[pair[1]].sn))
    used = {i for pair in normalized for i in pair}
    return normalized, [i for i in range(len(modules)) if i not in used], graph


def explain_unpaired(index, modules, graph, config):
    module = modules[index]
    if graph.degree(index):
        return {"原因": "存在合格候选，但受一对一全局匹配限制", "合格候选数": graph.degree(index)}
    candidates = [i for i in range(len(modules)) if i != index
                  and (module.group == "pool" or module.group != modules[i].group)
                  and (config.mode != "mixed-imu" or module.imu != modules[i].imu)]
    if not candidates:
        return {"原因": "没有符合分组/IMU要求的对侧模组", "合格候选数": 0}
    nearest = min(candidates, key=lambda i: (cost(module, modules[i], config), modules[i].sn))
    return {"原因": "; ".join(violations(module, modules[nearest], config)), "合格候选数": 0,
            "最近候选SN": modules[nearest].sn,
            **{f"候选Δ{k}": v for k, v in differences(module, modules[nearest]).items()}}
