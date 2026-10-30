"""PatchLoop v3 agent swarm: task-adaptive plan -> synthesized verifiers -> parallel tool-using workers ->
integration -> deterministic verification -> repair rounds. See docs/CONTRACT-V3-SWARM.md.

Heavy modules are imported lazily (`from app.swarm.engine import run_swarm`) so importing the agent API stays cheap.
"""
