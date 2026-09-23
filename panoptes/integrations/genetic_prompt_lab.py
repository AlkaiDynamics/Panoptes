"""Dependency-free prompt-evolution planning inspired by GeneticPromptLab.

The pinned upstream implementation selects the best half of a scored prompt
population, crosses parent pairs, injects 25 percent fresh prompts, and then
probabilistically mutates the next generation. Panoptes preserves that useful
algorithmic structure while emitting transformation requests instead of
calling a paid model or importing the upstream ML dependency stack.
"""

import math
import random


def plan_evolution_round(population, *, mutation_rate=0.1, seed=0):
    """Return a deterministic, provider-neutral evolution work queue."""
    if not isinstance(population, list) or len(population) < 4:
        raise ValueError("population must contain at least four scored prompts")
    if not isinstance(mutation_rate, (int, float)) or isinstance(mutation_rate, bool):
        raise ValueError("mutation_rate must be numeric")
    if not 0 <= mutation_rate <= 1:
        raise ValueError("mutation_rate must be between 0 and 1")

    normalized = []
    seen = set()
    for index, item in enumerate(population):
        if not isinstance(item, dict):
            raise ValueError("each population item must be an object")
        ident = item.get("id")
        prompt = item.get("prompt")
        fitness = item.get("fitness")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            raise ValueError("prompt ids must be unique nonempty strings")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompts must be nonempty strings")
        if (not isinstance(fitness, (int, float)) or isinstance(fitness, bool)
                or not math.isfinite(fitness)):
            raise ValueError("fitness must be a finite number")
        seen.add(ident)
        normalized.append({"id": ident, "prompt": prompt, "fitness": float(fitness),
                           "input_order": index})

    ranked = sorted(normalized, key=lambda item: (-item["fitness"], item["input_order"]))
    elites = ranked[: int(len(ranked) * 0.5)]
    requests = []
    for index in range(0, len(elites) - 1, 2):
        requests.append({
            "id": f"crossover-{index // 2 + 1:03d}",
            "kind": "crossover",
            "parents": [elites[index]["id"], elites[index + 1]["id"]],
            "instruction": "Combine useful parent segments while preserving the task and evidence constraints.",
            "requires_inference": True,
        })
    for index in range(int(len(ranked) * 0.25)):
        requests.append({
            "id": f"immigrant-{index + 1:03d}",
            "kind": "fresh_candidate",
            "instruction": "Generate a distinct prompt from a fresh representative example.",
            "requires_inference": True,
        })

    next_ids = [item["id"] for item in elites] + [item["id"] for item in requests]
    rng = random.Random(seed)
    mutation_queue = [
        {"candidate": ident, "mutate": rng.random() < mutation_rate,
         "instruction": "Rephrase without weakening the core task or evidence constraints."}
        for ident in next_ids
    ]
    return {
        "algorithm": "elite-selection_pairwise-crossover_random-immigrants_mutation",
        "source_behavior": {"elite_fraction": 0.5, "immigrant_fraction": 0.25,
                            "mutation_rate": mutation_rate},
        "input_population": len(ranked),
        "elites": [{k: item[k] for k in ("id", "prompt", "fitness")} for item in elites],
        "transformation_queue": requests,
        "mutation_queue": mutation_queue,
        "planned_population": len(next_ids),
        "inference_executed": False,
    }
