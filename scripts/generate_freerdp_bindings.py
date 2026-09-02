"""Regenerates the ctypes struct/type layer for embedded RDP from the real
FreeRDP3 headers, via clang2py (ctypeslib2) — auto-generation is used here
specifically because the core `freerdp` instance struct has 70+ fields
(many function pointers) and is actively evolving across versions;
hand-transcribing that into ctypes is exactly the kind of thing that
causes silent memory corruption from one misplaced field.

This is a DEV-ONLY tool. The app itself doesn't need a compiler or these
headers at runtime — only whoever regenerates the bindings does.

--- One-time setup (Linux) ---

Runtime library + dev headers:
    sudo dnf install freerdp-devel        # Fedora — installs libfreerdp3
                                           # itself too, already a runtime
                                           # dependency of session_launcher's
                                           # external xfreerdp path
    sudo apt install libfreerdp-dev       # Debian/Ubuntu

Generation tooling (project venv):
    pip install ctypeslib2 "clang==<match your libclang>"
    # `pip install libclang` gives you a libclang.so; the separate `clang`
    # PyPI package (the Python bindings) must be version-matched to it, or
    # you'll hit "undefined symbol" errors — check with:
    #   python -c "import ctypeslib; print(ctypeslib.clang_version())"

You'll also need whatever provides <stddef.h> etc. (a C compiler's
"resource directory") if libclang can't already find one — on Fedora
that's the `clang-libs` package (NOT just `clang-resource-filesystem`,
which is empty scaffolding pointing elsewhere).

--- Usage ---

    python scripts/generate_freerdp_bindings.py \
        --freerdp-include /usr/include/freerdp3 \
        --winpr-include /usr/include/winpr3 \
        --system-include /usr/include \
        --resource-include /usr/lib64/clang/<ver>/include \
        --output src/it_toolbox/core/rdp/_freerdp3_bindings.py

All four include paths are required — see the setup notes above for what
each one is for. Run `clang2py --help` (after installing ctypeslib2) if
you want to see what's actually happening under the hood; this script is
a thin, version-pinned wrapper around it with our specific workarounds
applied.
"""

import argparse
import sys


def _patch_duplicate_definition_bug() -> None:
    """ctypeslib2 2.4.0's Clang_Parser.register() only tolerates a
    forward-declared *struct* being redefined later — not an enum/typedef
    that gets visited twice via two different #include paths, which is
    what FreeRDP's CONNECTION_STATE (and possibly others) actually does.
    Keep the first definition seen instead of raising.
    """
    from ctypeslib.codegen import clangparser

    original_register = clangparser.Clang_Parser.register

    def patched_register(self, name, obj):
        try:
            return original_register(self, name, obj)
        except clangparser.DuplicateDefinitionException:
            return self.all[name]

    clangparser.Clang_Parser.register = patched_register


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freerdp-include", required=True)
    parser.add_argument("--winpr-include", required=True)
    parser.add_argument("--system-include", required=True)
    parser.add_argument("--resource-include", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--headers",
        nargs="+",
        default=["freerdp/freerdp.h", "freerdp/client.h"],
        help="Header paths, relative to --freerdp-include, to generate from.",
    )
    parser.add_argument(
        "--libclang",
        default=None,
        help=(
            "Explicit path to libclang.so/.dll, if auto-detection fails "
            "(seen on a Fedora venv where `pip install libclang` places it "
            "under .venv/lib/... while site-packages resolution looks in "
            ".venv/lib64/... — auto-detection then can't find it)."
        ),
    )
    args = parser.parse_args()

    if args.libclang:
        from clang.cindex import Config

        Config.set_library_file(args.libclang)

    _patch_duplicate_definition_bug()

    from ctypeslib.clang2py import main as clang2py_main

    clang_args = (
        f"-I{args.resource_include} -I{args.freerdp_include} "
        f"-I{args.winpr_include} -I{args.system_include}"
    )
    sys.argv = [
        "clang2py",
        "-o",
        args.output,
        f"--clang-args={clang_args}",
        *(f"{args.freerdp_include}/{h}" for h in args.headers),
    ]
    clang2py_main()
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
