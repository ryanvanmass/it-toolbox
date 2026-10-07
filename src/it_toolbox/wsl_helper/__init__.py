"""Headless helper process that runs inside the Linux tools WSL distro
and hosts long-lived services the Windows app talks to over
core/wsl/transport.py (see docs/wsl-interconnect-plan.md).

Must never import PySide6 (or anything that does): the distro runs it
with its own system python3, loading this package straight from the
Windows install via PYTHONPATH. tests/wsl_helper checks that.

Adding a service: write a module with `run(conn, params, stop)` and add
it to SERVICES in __main__.py.
"""
