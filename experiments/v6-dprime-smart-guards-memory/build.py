"""Build private Kaggle notebook for V6 D-Prime + Pre-Execution State Guards + Scoped Memory."""
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

nb["cells"][0]["source"] = """# ARC3 V6 D-Prime + Pre-Execution State Guards + Scoped Sandbox Memory

Team iteration on Daniel Franzen's public ARC-AGI-3 Milestone 2 solution, built on V5 (Public LB **31.18**):
- **D-Prime Slot Priority + Admission Gate (`install_d`)**: Replaces fresh-first admission with D-prime expected utility and keeps `EXPOSE_RESET` strictly off (`EXPOSE_UNDO='on'` only).
- **Pre-Execution State-Hash Guards (`level >= 2`, Overridable on Immediate Repeat)**:
  - `ARC3_DEATH_REPEAT_GUARD='1'` (with `_fatal_prefix_match` lookahead): refuses known-fatal actions or batch suffixes from an identical whole-frame board state before execution (0 actions spent, attempt preserved intact).
  - `ARC3_NOOP_REPEAT_GUARD='1'` (with 4-point animation-safety across `python_tool_sandbox.py`, `solver.py`, `tool_agent.py`, `animation.py`): refuses repeated no-op actions from an identical board state without falsely flagging actions with `transient_pixels > 0`.
  - `ARC3_REPEAT_STATE_GUARD='1'`: per-snippet cycle breaker that stops buggy Python loops from oscillating across revisited `(state_hash, action_sig)` pairs.
- **Persistent Scoped Sandbox Data Memory (`scoped_memory.py` / `ARC3_SCOPED_MEMORY='1'`)**:
  - Provides `scratch = {'game': {}, 'level': {}, 'step': {}}` (up to 128 KiB JSON) inside every Python call so parsed layouts, hazard coordinates, and BFS graphs persist across turns with **0 LLM prompt bloat** (100% SGLang prefix KV-cache preservation).
  - Transactional 30s timeout protection preserves both `_kept_functions` and `_scratch_memory`.
- **Spatial Grounding & Truncation Recovery**:
  - `ARC3_GAMEOVER_DIFF='1'` (exact `last_alive -> death_frame` object diff on `GAME_OVER`), `ARC3_LEVEL_INVENTORY='1'` (`START-vs-START` new-object inventory on `level >= 2` entry), `ARC3_DEATH_LEDGER='1'` (+ post-drain fallback), `step_budget.py` late alert, and `ARC3_STUB_DEAD_REASONING='1'`.

Credits: Daniel Franzen, Tufa Labs, Affectify, Yukai Liu, Ouyangruize, and Leo Provorov.
"""

source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

# 1. Inject V6 source tree patching into Cell 4 right after git apply harness-changes.patch,
#    BEFORE any inference.* modules are imported in later cells.
cell4_src = nb["cells"][4]["source"]
patch_anchor = "print('harness patch applied successfully')"
assert cell4_src.count(patch_anchor) == 1, "Could not find harness patch anchor in Cell 4"

v6_cell4_hook = (
    "print('harness patch applied successfully')\n"
    "import types as _v6_types\n"
    f"_V6_SCHEDULER_SOURCE = {source!r}\n"
    "_v6_mod = _v6_types.ModuleType('arc3_v6_dprime_smart_guards_memory')\n"
    "sys.modules[_v6_mod.__name__] = _v6_mod\n"
    "exec(compile(_V6_SCHEDULER_SOURCE, 'arc3_v6_dprime_smart_guards_memory.py', 'exec'), _v6_mod.__dict__)\n"
    "_v6_patched = _v6_mod.apply_v6_harness_patches(BUNDLE_DIR / 'src/ARC3-Inference')\n"
    "print('V6 harness patches applied:', sorted(_v6_patched.keys()), flush=True)"
)
cell4_src = cell4_src.replace(patch_anchor, v6_cell4_hook, 1)

# Configure V6 environment flags in setup_env while keeping EXPOSE_RESET OFF (only EXPOSE_UNDO='on')
guards_anchor = "    ########## guards ##########\n    'ARC3_GUARDS_FROM_LEVEL': 2,\n    'ARC3_BATCH_NOOP_BLOCK': '1',\n    'ARC3_STALE_STATE_BLOCK': '1',"
assert cell4_src.count(guards_anchor) == 1, "Could not find guards anchor in Cell 4"
cell4_src = cell4_src.replace(
    guards_anchor,
    guards_anchor
    + "\n    'ARC3_DEATH_LEDGER': '1',"
    + "\n    'ARC3_DEATH_REPEAT_GUARD': '1',"
    + "\n    'ARC3_NOOP_REPEAT_GUARD': '1',"
    + "\n    'ARC3_REPEAT_STATE_GUARD': '1',"
    + "\n    'ARC3_SCOPED_MEMORY': '1',"
    + "\n    'ARC3_GAMEOVER_DIFF': '1',"
    + "\n    'ARC3_LEVEL_INVENTORY': '1',"
    + "\n    'ARC3_STUB_DEAD_REASONING': '1',",
    1,
)
assert "EXPOSE_RESET" not in cell4_src.split("_V6_SCHEDULER_SOURCE")[0], "EXPOSE_RESET must not be enabled"
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

# 4. Inject V6 D-prime runtime installer cell at index 17
patch_cell = """import sys
import inference.agent.tool_agent as _team_tool_agent
import inference.framework.solver as _team_solver
sys.modules['arc3_v6_dprime_smart_guards_memory'].install_d(_team_tool_agent, _team_solver)
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
notebook = OUT / "arc3-v6-dprime-smart-guards-memory.ipynb"
notebook.write_text(json.dumps(nb, ensure_ascii=False, indent=1))

# Write Kaggle kernel metadata
meta = json.loads(REFERENCE_META.read_text())
meta.pop("id_no", None)
meta.update({
    "id": "jessewudao/arc3-v6-dprime-smart-guards-memory",
    "title": "ARC3 V6 DPrime Smart Guards Memory",
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
        "Built on V5 (Public LB 31.18): D-prime priority + install_d fresh-game admission + EXPOSE_RESET off (EXPOSE_UNDO='on')",
        "Pre-Execution State-Hash Guards on Level >= 2 (overridable): ARC3_DEATH_REPEAT_GUARD='1' (with _fatal_prefix_match lookahead), animation-safe ARC3_NOOP_REPEAT_GUARD='1', and ARC3_REPEAT_STATE_GUARD='1' per-snippet cycle breaker",
        "Complete 4-Point Animation-Aware Guard across python_tool_sandbox.py, solver.py (including gameplay_changed_per_action), tool_agent.py (including _record_guard_observations), and animation.py",
        "Scoped Sandbox Data Memory (scoped_memory.py / ARC3_SCOPED_MEMORY='1'): persistent JSON `scratch = {'game': {}, 'level': {}, 'step': {}}` up to 128 KiB with 0 LLM prompt bloat",
        "Transactional 30s Timeout Retention for both _kept_functions and _scratch_memory",
        "Spatial Grounding & Truncation Recovery: ARC3_GAMEOVER_DIFF='1', ARC3_LEVEL_INVENTORY='1', ARC3_DEATH_LEDGER='1' (+ post-drain fallback), step_budget.py late alert, and ARC3_STUB_DEAD_REASONING='1'",
    ],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Generated notebook: {notebook}")
