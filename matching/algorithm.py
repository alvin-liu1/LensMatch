"""Exact maximum cardinality, then minimum normalized cost (1e-6 precision)."""
from bisect import bisect_left, bisect_right
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


def solve(modules: list[Module], config: Config, progress=None):
    # Sorting by exposure avoids checking pairs already outside the AEC limit.
    graph = nx.Graph()
    graph.add_nodes_from(range(len(modules)))
    ordered = sorted(range(len(modules)), key=lambda i: (modules[i].aec, modules[i].sn))
    values = [modules[i].aec for i in ordered]
    for pos, i in enumerate(ordered):
        if progress and pos % 100 == 0:
            progress(f"构建候选图：{pos}/{len(modules)}")
        end = bisect_right(values, modules[i].aec + config.aec_limit)
        for candidate_pos in range(pos + 1, end):
            j = ordered[candidate_pos]
            if not violations(modules[i], modules[j], config):
                integer_cost = round(cost(modules[i], modules[j], config) * 1_000_000)
                graph.add_edge(i, j, weight=-integer_cost, cost=integer_cost)

    bipartite = config.mode == "mixed-imu" or any(m.group != "pool" for m in modules)
    pairs = []
    components = sorted(nx.connected_components(graph), key=lambda ns: min(ns))
    for component_id, nodes in enumerate(components, 1):
        if progress and (component_id == 1 or component_id % 100 == 0 or component_id == len(components)):
            progress(f"求解连通分量：{component_id}/{len(components)}；候选边 {graph.number_of_edges()}")
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


class DiagnosticIndex:
    """Exact nearest candidate search with a nonnegative single-metric lower bound."""
    def __init__(self, modules, config):
        self.modules, self.config = modules, config
        keys = [key for key in ("aec", "rg", "bg", "score")
                if config.weights[key] > 0 and (key != "score" or config.use_score)
                and all(getattr(module, key) is not None for module in modules)]
        self.key = max(keys, key=lambda key: config.weights[key] *
                       (max(getattr(m, key) for m in modules) - min(getattr(m, key) for m in modules)) /
                       getattr(config, key + "_limit")) if modules and keys else None
        self.groups = {}
        for group, imu in {(m.group, m.imu) for m in modules}:
            indices = [i for i, m in enumerate(modules)
                       if (group == "pool" or group != m.group)
                       and (config.mode != "mixed-imu" or imu != m.imu)]
            if self.key:
                indices.sort(key=lambda i: (getattr(modules[i], self.key), modules[i].sn))
            self.groups[group, imu] = (indices, [getattr(modules[i], self.key) for i in indices] if self.key else [])

    def nearest(self, index):
        module = self.modules[index]
        indices, values = self.groups[module.group, module.imu]
        if not self.key:
            return min((i for i in indices if i != index), default=None,
                       key=lambda i: (cost(module, self.modules[i], self.config), self.modules[i].sn))
        value = getattr(module, self.key)
        right = bisect_left(values, value)
        left = right - 1
        best, best_rank = None, (float("inf"), "")
        while left >= 0 or right < len(indices):
            if left >= 0 and (right == len(indices) or value - values[left] <= values[right] - value):
                pos = left
                left -= 1
            else:
                pos = right
                right += 1
            bound = self.config.weights[self.key] * abs(value - values[pos]) / getattr(self.config, self.key + "_limit")
            if bound > best_rank[0]:
                break
            candidate = indices[pos]
            if candidate == index:
                continue
            rank = (cost(module, self.modules[candidate], self.config), self.modules[candidate].sn)
            if rank < best_rank:
                best, best_rank = candidate, rank
        return best


def explain_unpaired(index, modules, graph, config, diagnostic_index=None):
    module = modules[index]
    if graph.degree(index):
        return {"原因": "存在合格候选，但受一对一全局匹配限制", "合格候选数": graph.degree(index)}
    if diagnostic_index is not None:
        nearest = diagnostic_index.nearest(index)
    else:
        candidates = [i for i in range(len(modules)) if i != index
                      and (module.group == "pool" or module.group != modules[i].group)
                      and (config.mode != "mixed-imu" or module.imu != modules[i].imu)]
        nearest = min(candidates, default=None, key=lambda i: (cost(module, modules[i], config), modules[i].sn))
    if nearest is None:
        return {"原因": "没有符合分组/IMU要求的对侧模组", "合格候选数": 0}
    return {"原因": "; ".join(violations(module, modules[nearest], config)), "合格候选数": 0,
            "最近候选SN": modules[nearest].sn,
            **{f"候选Δ{k}": v for k, v in differences(module, modules[nearest]).items()}}
