"""Synthetic performance checks; run from repository root, no production data."""
import json
from pathlib import Path
import random
import sys
from time import perf_counter
import networkx as nx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matching.models import Module, Config
from matching.algorithm import solve, explain_unpaired, DiagnosticIndex


def measure(name, modules, config):
    start = perf_counter()
    pairs, unpaired, graph = solve(modules, config)
    solve_seconds = perf_counter() - start
    start = perf_counter()
    diagnostic_index = DiagnosticIndex(modules, config) if unpaired else None
    for index in unpaired:
        explain_unpaired(index, modules, graph, config, diagnostic_index)
    return {'case': name, 'modules': len(modules), 'pairs': len(pairs), 'candidate_edges': graph.number_of_edges(),
            'largest_component': max(map(len, nx.connected_components(graph)), default=0),
            'solve_seconds': round(solve_seconds, 4), 'diagnostic_seconds': round(perf_counter() - start, 4)}


def main():
    rng = random.Random(42)
    config = Config(use_score=False)
    cases = [
        ('sparse-1000', [Module(str(i), (i // 2) * 3, rng.random(), rng.random(), 0) for i in range(1000)], config),
        ('dense-200', [Module(str(i), 0, rng.random(), rng.random(), 0) for i in range(200)], config),
        ('mixed-500', [Module(str(i), (i // 2) * 3, rng.random(), rng.random(), i % 2) for i in range(500)], Config(mode='mixed-imu', use_score=False)),
        ('isolated-1000', [Module(str(i), i * 3, rng.random(), rng.random(), 0) for i in range(1000)], config),
    ]
    results = [measure(*case) for case in cases]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
