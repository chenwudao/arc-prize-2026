"""Build private Kaggle notebook for V3 Cognitive Guard."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT.parents[1] / "notebooks/dfranzen/arc-agi-3-milestone-2-solution.ipynb"
REFERENCE_META = ROOT / "input-metadata.json"
OUT = ROOT / "upload"
OUT.mkdir(exist_ok=True)

nb = json.loads(BASELINE.read_text())
for cell in nb["cells"]:
    if isinstance(cell["source"], list):
        cell["source"] = "".join(cell["source"])
    if cell["cell_type"] == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    cell["metadata"] = {}

nb["cells"][0]["source"] = """# ARC3 V3 Cognitive Guard

Team iteration on Daniel Franzen's public ARC-AGI-3 Milestone 2 solution.
- Full Affectify / Yukai Liu D-prime priority alignment (proven 31.54 ~ 34.30 SOTA).
- Fresh-first gate replacement via install_d: Unstarted games enter queue via D-prime snapshot priority.
- Dynamic pace tracking (FormPace: mean generated tokens per completed level).
- Tail fade fraction 0.4 in endgame to harvest solvable levels.
- Non-intrusive Strategy-Audit intervention on stalled levels (action count >= 24).
- Level-1 cognitive guards enabled: ARC3_GUARDS_FROM_LEVEL=1, ARC3_NOOP_REPEAT_GUARD=1, ARC3_DEATH_REPEAT_GUARD=1, ARC3_DEATH_LEDGER=1.
- Model, inference stack, perception, and tools remain unchanged.

Credits: Daniel Franzen, Tufa Labs, Affectify, Yukai Liu, and lordhansolo.
"""

# Modify Cell 4 to enable Level-1 guards and anti-loop repeat protection
cell4_src = nb["cells"][4]["source"]
old_guards = """    ########## guards ##########
    'ARC3_GUARDS_FROM_LEVEL': 2,
    'ARC3_BATCH_NOOP_BLOCK': '1',
    'ARC3_STALE_STATE_BLOCK': '1',"""
new_guards = """    ########## guards ##########
    'ARC3_GUARDS_FROM_LEVEL': 1,
    'ARC3_NOOP_REPEAT_GUARD': '1',
    'ARC3_DEATH_REPEAT_GUARD': '1',
    'ARC3_DEATH_LEDGER': '1',
    'ARC3_BATCH_NOOP_BLOCK': '1',
    'ARC3_STALE_STATE_BLOCK': '1',"""
assert old_guards in cell4_src, "Could not find expected guards config in Cell 4"
nb["cells"][4]["source"] = cell4_src.replace(old_guards, new_guards, 1)

# Modify Cell 16 for fast smoke test when run interactively / Save & Run
cfg = nb["cells"][16]["source"]
start = cfg.index("else:\n    if USE_PRIORITY_SCHEDULING:")
end = cfg.index("\n# show config", start)
cfg = cfg[:start] + """else:
    # Fast GPU smoke test; formal competition settings above are unchanged.
    bm.n_passes = 1
    bm.solver.concurrency = 4
    bm.solver.max_runtime_s_per_game = 5 * 60
""" + cfg[end:]
nb["cells"][16]["source"] = cfg

# Limit offline games to 4 for smoke test
run = nb["cells"][20]["source"]
old = "bm.games = _offline_games(competition_env_files)"
assert old in run
run = run.replace(old, old + "[:4]", 1)
nb["cells"][20]["source"] = run

# Inject V3 Cognitive Guard patch cell
source = (ROOT / "scheduler.py").read_text()
patch_cell = """import sys, types
_iteration_source = SOURCE_PLACEHOLDER
_iteration = types.ModuleType('arc3_v3_cognitive_guard')
sys.modules[_iteration.__name__] = _iteration
exec(compile(_iteration_source, 'arc3_v3_cognitive_guard.py', 'exec'), _iteration.__dict__)
import inference.agent.tool_agent as _team_tool_agent
import inference.framework.solver as _team_solver
_iteration.install_d(_team_tool_agent, _team_solver)
""".replace("SOURCE_PLACEHOLDER", repr(source))

nb["cells"].insert(17, {
    "cell_type": "code",
    "metadata": {},
    "execution_count": None,
    "outputs": [],
    "source": patch_cell,
})

# Verify AST syntax for python code cells
for idx, c in enumerate(nb["cells"]):
    if c["cell_type"] == "code":
        src = c["source"]
        if src.strip().startswith("%%writefile"):
            continue
        lines = [line for line in src.splitlines() if not line.strip().startswith(("!", "%"))]
        clean_src = "\n".join(lines)
        try:
            ast.parse(clean_src)
        except Exception as e:
            raise RuntimeError(f"Cell {idx} failed AST parse: {e}")

nb["metadata"].pop("papermill", None)
notebook = OUT / "arc3-v3-cognitive-guard.ipynb"
notebook.write_text(json.dumps(nb, ensure_ascii=False, indent=1))

# Write Kaggle kernel metadata
meta = json.loads(REFERENCE_META.read_text())
meta.pop("id_no", None)
meta.update({
    "id": "jessewudao/arc3-v3-cognitive-guard",
    "title": "ARC3 V3 Cognitive Guard",
    "code_file": notebook.name,
    "is_private": True,
    "enable_gpu": True,
    "enable_internet": False,
    "machine_shape": "NvidiaRtxPro6000",
})
(OUT / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))

manifest = {
    "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
    "notebook_sha256": hashlib.sha256(notebook.read_bytes()).hexdigest(),
    "scheduler_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "formal_runtime_seconds": 32400,
    "formal_active_streams": 10,
    "formal_game_source": "live competition gateway; no public/private filtering",
    "smoke_game_count": 4,
    "smoke_seconds_per_game": 300,
    "changes": [
        "Full D-prime priority alignment",
        "install_d fresh-game admission replacement",
        "Dynamic per-game FormPace tracking",
        "Endgame tail fade 0.4",
        "Non-intrusive Strategy-Audit intervention on stalled levels (actions >= 24)",
        "Level-1 cognitive guards enabled (ARC3_GUARDS_FROM_LEVEL=1)",
        "Repeat no-op & death guards enabled (ARC3_NOOP_REPEAT_GUARD=1, ARC3_DEATH_REPEAT_GUARD=1)",
        "Death state ledger enabled (ARC3_DEATH_LEDGER=1)",
    ],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Generated notebook: {notebook}")
