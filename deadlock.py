"""Wait-for graph deadlock detection and recovery."""


def wait_for_graph(processes):
    owner = {r: p["id"] for p in processes for r in p.get("holds", [])}
    graph = {p["id"]: [] for p in processes}
    for p in processes:
        for r in p.get("waits", []):
            o = owner.get(r)
            if o and o != p["id"] and o not in graph[p["id"]]:
                graph[p["id"]].append(o)
    return graph


def edges(processes):
    """Wait-for edges with the resource that causes each wait: A -> B because B holds R."""
    owner = {r: p["id"] for p in processes for r in p.get("holds", [])}
    out = []
    for p in processes:
        for r in p.get("waits", []):
            o = owner.get(r)
            if o and o != p["id"]:
                out.append({"from": p["id"], "to": o, "resource": r})
    return out


def find_cycle(graph):
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack = []

    def dfs(n):
        color[n] = GREY
        stack.append(n)
        for m in graph[n]:
            if color[m] == GREY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                c = dfs(m)
                if c:
                    return c
        stack.pop()
        color[n] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            c = dfs(n)
            if c:
                return c
    return None


def detect(processes):
    g = wait_for_graph(processes)
    return {"graph": g, "edges": edges(processes), "cycle": find_cycle(g)}


def recover(processes):
    """Stop one job per loop (the one holding the fewest resources) until no loop is left."""
    procs = [dict(p) for p in processes]
    steps = []
    while True:
        cycle = find_cycle(wait_for_graph(procs))
        if not cycle:
            break
        members = [p for p in procs if p["id"] in set(cycle)]
        victim = min(members, key=lambda p: (len(p.get("holds", [])), p["id"]))
        steps.append({"cycle": cycle, "victim": victim["id"], "released": victim.get("holds", [])})
        procs = [p for p in procs if p["id"] != victim["id"]]
    return {"steps": steps, "remaining": procs, "graph": wait_for_graph(procs),
            "edges": edges(procs)}
