"""Build private Kaggle notebook for V4 Stagnation + Animation-Aware + D-Prime."""
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

nb["cells"][0]["source"] = """# ARC3 V4 Stagnation + Animation-Aware + D-Prime

Team iteration on Daniel Franzen's public ARC-AGI-3 Milestone 2 solution:
- Clean D-prime slot priority + `install_d` fresh-game admission replacement (from V2, LB 28.04).
- 96k-Token Stagnation Context Restart (`stagnation_restart.py`): clears poisoned reasoning context and retained functions once per level after 98,304 generated tokens while preserving the live game board and Python empirical observations (`history`, `transitions`, `death_ledger`).
- Animation-Aware No-Op & Stale-State Fix: actions with intermediate animation (`transient_pixels > 0`) are not misclassified as NO-OP or stale-state, plus empty animation schema fix (`patch_animation_empty`).
- Fatal Edge-Strip Meter (`edge_meter.py`): reports objective pixel measurements of monotone shrinking edge strips on post-death diagnostic turns.
- Segmentation Bounding-Box Geometry (`bbox_rc`, `bbox_center2_rc`) and spatial helpers in `segmentation.py`.
- Preserves unguarded Level-1 exploration (`ARC3_GUARDS_FROM_LEVEL=2`) and enables `EXPOSE_RESET='on'`.

Credits: Daniel Franzen, Tufa Labs, Affectify, Yukai Liu, Heliosli, and Ouyangruize.
"""

source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

# 1. Inject V4 source tree patching into Cell 4 right after git apply harness-changes.patch,
#    BEFORE any inference.* modules are imported in later cells.
cell4_src = nb["cells"][4]["source"]
patch_anchor = "print('harness patch applied successfully')"
assert cell4_src.count(patch_anchor) == 1, "Could not find harness patch anchor in Cell 4"

v4_cell4_hook = (
    "print('harness patch applied successfully')\n"
    "import types as _v4_types\n"
    f"_V4_SCHEDULER_SOURCE = {source!r}\n"
    "_v4_mod = _v4_types.ModuleType('arc3_v4_stagnation_anima')\n"
    "sys.modules[_v4_mod.__name__] = _v4_mod\n"
    "exec(compile(_V4_SCHEDULER_SOURCE, 'arc3_v4_stagnation_anima.py', 'exec'), _v4_mod.__dict__)\n"
    "_v4_patched = _v4_mod.apply_v4_harness_patches(BUNDLE_DIR / 'src/ARC3-Inference')\n"
    "print('V4 harness patches applied:', sorted(_v4_patched.keys()), flush=True)"
)
cell4_src = cell4_src.replace(patch_anchor, v4_cell4_hook, 1)

# Enable EXPOSE_RESET alongside EXPOSE_UNDO while keeping ARC3_GUARDS_FROM_LEVEL=2 untouched
ctrl_anchor = "    ########## controls ##########\n    'EXPOSE_UNDO': 'on',"
assert cell4_src.count(ctrl_anchor) == 1, "Could not find controls anchor in Cell 4"
cell4_src = cell4_src.replace(
    ctrl_anchor,
    "    ########## controls ##########\n    'EXPOSE_UNDO': 'on',\n    'EXPOSE_RESET': 'on',",
    1,
)
nb["cells"][4]["source"] = cell4_src

# 2. Modify Cell 16 for fast smoke test when run interactively / Save & Run
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

# 3. Limit offline games to 4 for smoke test
run = nb["cells"][20]["source"]
old = "bm.games = _offline_games(competition_env_files)"
assert old in run
run = run.replace(old, old + "[:4]", 1)
nb["cells"][20]["source"] = run

# 4. Inject V4 D-prime runtime installer cell at index 17
patch_cell = """import sys
import inference.agent.tool_agent as _team_tool_agent
import inference.framework.solver as _team_solver
sys.modules['arc3_v4_stagnation_anima'].install_d(_team_tool_agent, _team_solver)
"""

nb["cells"].insert(17, {
    "cell_type": "code",
    "metadata": {},
    "execution_count": None,
    "outputs": [],
    "source": patch_cell,
})

# 5. Verify AST syntax for all python code cells
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
notebook = OUT / "arc3-v4-stagnation-anima.ipynb"
notebook.write_text(json.dumps(nb, ensure_ascii=False, indent=1))

# Write Kaggle kernel metadata
meta = json.loads(REFERENCE_META.read_text())
meta.pop("id_no", None)
meta.update({
    "id": "jessewudao/arc3-v4-stagnation-anima",
    "title": "ARC3 V4 Stagnation Anima",
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
        "Full D-prime priority alignment + install_d fresh-game admission replacement (from V2 LB 28.04)",
        "Restored ARC3_GUARDS_FROM_LEVEL=2 and removed 24-action Strategy-Audit text (fixing V3 regression)",
        "96k-Token Stagnation Context Restart (stagnation_restart.py, once per level >= 98,304 tokens)",
        "Animation-Aware No-Op & Stale-State fix (transient_pixels > 0 not treated as no-op)",
        "Empty animation dictionary schema fix (patch_animation_empty)",
        "Fatal Edge-Strip Meter (edge_meter.py) on post-death diagnostic turns",
        "Segmentation bbox_rc / bbox_center2_rc geometry and spatial grid helpers",
        "Enabled EXPOSE_RESET='on' alongside EXPOSE_UNDO='on'",
    ],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Generated notebook: {notebook}")
