"""Run in a prepared netlist workspace: python /path/to/hierX/examples/inspect_graph.py."""
from pathlib import Path

from hx.api import extract
from hx.diff import diff_graphs, render_markdown
from hx.export import export_file
from hx.model import Graph

# Extraction returns a Graph. Save it explicitly when you want a JSON artifact.
graph = extract("ota.sp:.", root=".", depth=2, dialect="ngspice")
output = Path(".hx")
graph.save(str(output / "before.json"))
loaded = Graph.load(str(output / "before.json"))
assert loaded.to_dict() == graph.to_dict()

print(f"Entry: {graph.entry}")
for node in graph.nodes.values():
    print(node.kind, node.name, node.precision)
for edge in graph.edges[:3]:
    # Python uses src/dst; the serialized JSON uses from/to.
    print(edge.src, "->", edge.dst, edge.kind)

# Work on the copied tutorial deck. Restore its source even if extraction fails.
deck = Path("ota.sp")
original = deck.read_text(encoding="utf-8")
try:
    assert "RL sense 0 10k" in original
    deck.write_text(original.replace("RL sense 0 10k", "RL sense 0 20k"), encoding="utf-8")
    changed = extract("ota.sp:.", root=".", depth=2, dialect="ngspice", use_cache=False)
finally:
    deck.write_text(original, encoding="utf-8")
changed.save(str(output / "after.json"))
difference = diff_graphs(graph.to_dict(), changed.to_dict())
assert difference["summary"]["any"]
print(render_markdown(difference, changed.to_dict()))
export_file(str(output / "after.json"), str(output / "review.html"))
print("Saved .hx/before.json, .hx/after.json, and .hx/review.html")
