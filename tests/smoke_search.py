"""Scratch runner: search on the saved live banners, replay the best plan, print it."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
from helpers import fixture_problem
from bcplanner.search import search
from bcplanner.replay import replay
from bcplanner.actions import describe

def run(tickets, cat_food, plats, legends, owned=(), verbose=True):
    prob, names = fixture_problem(tickets=tickets, cat_food=cat_food, plats=plats, legends=legends, owned=owned)
    print(f'--- tickets={tickets} cf={cat_food} plats={plats} legends={legends} | units={len(prob.unit_ids)} targets={bin(prob.targets_mask).count("1")} tomorrow_adds={prob.tomorrow_adds_banners}', flush=True)
    res = search(prob)
    s = res.stats
    print(f'search {s.seconds:.2f}s labels={s.labels_created} dominated={s.labels_dominated} expanded={s.nodes_expanded} survivors={len(res.labels)} max/node={s.max_labels_at_a_node} truncated={s.truncated} max_k={s.max_offset}', flush=True)
    best = res.best_value()
    acts = res.plan_actions(best)
    rep = replay(prob, acts)
    ok = abs(rep.value - best.value) < 1e-6 and not rep.problems
    print(f'best value {best.value:.2f} (replay {rep.value:.2f}, agree={ok}) t={best.t} cfu={best.c} p={best.p} l={best.l} skips={best.skips} k={best.k} problems={rep.problems[:3]}', flush=True)
    if verbose:
        bn = {ev: b.name[:26] for ev, b in prob.banners.items()}
        for st in rep.steps:
            rolls = ', '.join(f"{'*' if r.new else ''}{names.get(r.cat_id, r.cat_id)}{'(R)' if r.rerolled else ''}{'(G)' if r.source=='guaranteed' else ''}" for r in st.rolls)
            print(f"{st.index:>2} day+{st.day_offset} k={st.offset_before:<3} {describe(st.action, bn):<44} {rolls}", flush=True)
    cov = res.cheapest_covering()
    print('cheapest full coverage:', None if cov is None else f'cost={res.cost(cov):.2f} t={cov.t} cfu={cov.c} p={cov.p} value={cov.value:.2f}', flush=True)
    for m, lab in res.near_misses(3):
        print(f'  missing {m}: cost={res.cost(lab):.2f} t={lab.t} cfu={lab.c} p={lab.p} value={lab.value:.2f}', flush=True)
    env = res.envelope()
    print('envelope:', [(round(res.cost(l), 2), round(l.value, 2)) for l in env][:15], flush=True)
    print('frontier size', len(res.frontier()), flush=True)
    return res, rep

if __name__ == '__main__':
    args = [int(a) for a in sys.argv[1:5]] or [15, 3000, 2, 1]
    run(*args)
