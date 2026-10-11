"""Build a private Kaggle notebook from the unchanged team baseline."""
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

nb["cells"][0]["source"] = """# ARC3 V1 Dprime Coverage

Team iteration on Daniel Franzen's public ARC-AGI-3 Milestone 2 solution.
The model, inference stack, perception and tools are unchanged. The scheduling
score uses Affectify D-prime; the original fresh-game admission policy is retained
to give unseen games an exploration opportunity. This is an unscored candidate.

Credits: Daniel Franzen, Tufa Labs and Affectify.
Sources: https://github.com/da-fr/arc-agi-3-solution and
https://www.kaggle.com/code/shiiin9/affectify-arc-31-54-in-a-single-sub

Save & Run checks four public games for five minutes; it is a smoke test only.
The competition rerun discovers all gateway games and uses the full budget.
"""
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
run = nb["cells"][20]["source"]
old = "bm.games = _offline_games(competition_env_files)"
assert old in run
run = run.replace(old, old + "[:4]", 1)
nb["cells"][20]["source"] = run

source = (ROOT / "scheduler.py").read_text()
patch_cell = """import sys, types
_iteration_source = SOURCE_PLACEHOLDER
_iteration = types.ModuleType('arc3_v1_dprime_coverage')
sys.modules[_iteration.__name__] = _iteration
exec(compile(_iteration_source, 'arc3_v1_dprime_coverage.py', 'exec'), _iteration.__dict__)
import inference.agent.tool_agent as _team_tool_agent
_iteration.install(_team_tool_agent)
""".replace("SOURCE_PLACEHOLDER", repr(source))
nb["cells"].insert(17, {"cell_type": "code", "metadata": {}, "execution_count": None,
                        "outputs": [], "source": patch_cell})
nb["metadata"].pop("papermill", None)
notebook = OUT / "arc3-v1-dprime-coverage.ipynb"
notebook.write_text(json.dumps(nb, ensure_ascii=False, indent=1))

meta = json.loads(REFERENCE_META.read_text())
meta.pop("id_no", None)
meta.update({"id": "jessewudao/arc3-v1-dprime-coverage", "title": "ARC3 V1 Dprime Coverage",
             "code_file": notebook.name, "is_private": True, "enable_internet": False,
             "machine_shape": "NvidiaRtxPro6000"})
(OUT / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
manifest = {"baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
            "notebook_sha256": hashlib.sha256(notebook.read_bytes()).hexdigest(),
            "scheduler_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "formal_runtime_seconds": 32400, "formal_active_streams": 10,
            "formal_game_source": "live competition gateway; no public/private filtering",
            "smoke_game_count": 4, "smoke_seconds_per_game": 300,
            "changes": ["D-prime scoring", "observed per-game pace", "tail fade 0.4",
                        "fresh-first admission retained"]}
previous_path = ROOT / "manifest.json"
previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
if previous.get("notebook_sha256") == manifest["notebook_sha256"]:
    manifest = {**previous, **manifest}
previous_path.write_text(json.dumps(manifest, indent=2))
print(notebook)
