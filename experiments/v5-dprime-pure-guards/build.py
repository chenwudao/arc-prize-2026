"""Build private Kaggle notebook for V5 D-Prime + Pure Deterministic Guards."""
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

nb["cells"][0]["source"] = """# ARC3 V5 D-Prime + Pure Deterministic Guards

Team iteration on Daniel Franzen's public ARC-AGI-3 Milestone 2 solution:
- Clean D-prime slot priority + `install_d` fresh-game admission replacement (from V2, LB 28.04).
- Reverts `EXPOSE_RESET='on'` (restores default off; only `EXPOSE_UNDO='on'`) to eliminate voluntary mid-level resets that incur $4\\times$ quadratic RHAE penalties.
- Removes `96k` hard context wipe (`stagnation_restart.py`) so games never yield active GPU slots via `_note_history_evicted()` or lose cross-level retained helper functions (`_kept_functions`).
- Complete 3-Point Animation-Aware Execution Guard (`python_tool_sandbox.py`, `solver.py`, `tool_agent.py`, `animation.py`): actions with `transient_pixels > 0` do not trigger `_stale_state` blocks or batch `no_op_action` aborts.
- Transactional Helper Retention on Tool Timeout (`tool_agent.py`): preserves previously committed `_kept_functions` when a 30s Python call times out or aborts without a `keepable_functions` report.
- Static 1-line REPL persistence note in `PYTHON_ADDENDUM_TAIL` (`prompts.py`), maintaining 100% SGLang prefix KV-cache reuse.
- On-Demand Current-Level Death Ledger (`ARC3_DEATH_LEDGER='1'` + post-drain fallback) and Late Step-Budget Bar Alert (`step_budget.py`, $\\le 25\\%$ or $\\le 12$ steps remaining).

Credits: Daniel Franzen, Tufa Labs, Affectify, Yukai Liu, Ouyangruize, and Leo Provorov.
"""

source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

# 1. Inject V5 source tree patching into Cell 4 right after git apply harness-changes.patch,
#    BEFORE any inference.* modules are imported in later cells.
cell4_src = nb["cells"][4]["source"]
patch_anchor = "print('harness patch applied successfully')"
assert cell4_src.count(patch_anchor) == 1, "Could not find harness patch anchor in Cell 4"

v5_cell4_hook = (
    "print('harness patch applied successfully')\n"
    "import types as _v5_types\n"
    f"_V5_SCHEDULER_SOURCE = {source!r}\n"
    "_v5_mod = _v5_types.ModuleType('arc3_v5_dprime_pure_guards')\n"
    "sys.modules[_v5_mod.__name__] = _v5_mod\n"
    "exec(compile(_V5_SCHEDULER_SOURCE, 'arc3_v5_dprime_pure_guards.py', 'exec'), _v5_mod.__dict__)\n"
    "_v5_patched = _v5_mod.apply_v5_harness_patches(BUNDLE_DIR / 'src/ARC3-Inference')\n"
    "print('V5 harness patches applied:', sorted(_v5_patched.keys()), flush=True)"
)
cell4_src = cell4_src.replace(patch_anchor, v5_cell4_hook, 1)

# Enable ARC3_DEATH_LEDGER='1' while keeping EXPOSE_RESET OFF (only EXPOSE_UNDO='on')
guards_anchor = "    ########## guards ##########\n    'ARC3_GUARDS_FROM_LEVEL': 2,\n    'ARC3_BATCH_NOOP_BLOCK': '1',\n    'ARC3_STALE_STATE_BLOCK': '1',"
assert cell4_src.count(guards_anchor) == 1, "Could not find guards anchor in Cell 4"
cell4_src = cell4_src.replace(
    guards_anchor,
    guards_anchor + "\n    'ARC3_DEATH_LEDGER': '1',",
    1,
)
assert "EXPOSE_RESET" not in cell4_src.split("_V5_SCHEDULER_SOURCE")[0], "EXPOSE_RESET must not be enabled"
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

# 4. Inject V5 D-prime runtime installer cell at index 17
patch_cell = """import sys
import inference.agent.tool_agent as _team_tool_agent
import inference.framework.solver as _team_solver
sys.modules['arc3_v5_dprime_pure_guards'].install_d(_team_tool_agent, _team_solver)
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
notebook = OUT / "arc3-v5-dprime-pure-guards.ipynb"
notebook.write_text(json.dumps(nb, ensure_ascii=False, indent=1))

# Write Kaggle kernel metadata
meta = json.loads(REFERENCE_META.read_text())
meta.pop("id_no", None)
meta.update({
    "id": "jessewudao/arc3-v5-dprime-pure-guards",
    "title": "ARC3 V5 DPrime Pure Guards",
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
        "Reverted EXPOSE_RESET='on' (restores default off; only EXPOSE_UNDO='on') to avoid voluntary mid-level resets",
        "Removed 96k stagnation_restart.py hard wipe (preserves SGLang KV-cache, GPU slot, and cross-level _kept_functions)",
        "Removed unadvertised segmentation bbox_rc and sandbox bloat",
        "Complete 3-Point Animation-Aware Execution Guard (python_tool_sandbox.py, solver.py batch no_op_action stop, tool_agent.py, animation.py)",
        "Transactional Helper Retention on Tool Timeout (preserves _kept_functions when 30s Python call times out)",
        "Static 1-line PYTHON_ADDENDUM_TAIL REPL persistence reminder in prompts.py (100% KV-cache reuse)",
        "On-demand current-level Death Ledger (ARC3_DEATH_LEDGER='1' + post-drain fallback) and Late Step-Budget Bar Alert (<=25% or <=12 steps remaining)",
    ],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"Generated notebook: {notebook}")
