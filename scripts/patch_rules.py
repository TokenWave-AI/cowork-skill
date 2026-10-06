"""File-category and language rules retained from the previous paper analysis."""
import os
import re

TEST_RE = re.compile(
    r"(^|/)(tests?|testing|spec|specs|__tests__|e2e|integration[-_]tests?)(/|$)"
    r"|(^|/)test_[^/]*$|[^/]*_test\.[a-z]+$|[^/]*\.(test|spec)\.[a-z]+$"
    r"|[^/]*Test(s)?\.(java|kt|cs|scala)$|(^|/)conftest\.py$", re.I)
DOC_RE = re.compile(r"\.(md|rst|txt|adoc|mdx|po|pot)$|(^|/)(docs?|documentation|"
                    r"changelog|licenses?)(/|$)|CHANGELOG|README|LICENSE", re.I)
LOCK_RE = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|"
                     r"Cargo\.lock|poetry\.lock|go\.sum|composer\.lock|"
                     r"Gemfile\.lock|uv\.lock|flake\.lock)$", re.I)
VENDOR_RE = re.compile(r"(^|/)(vendor|third[-_]?party|node_modules|externals?|"
                       r"deps|submodules|\.yarn)(/|$)", re.I)
GEN_RE = re.compile(r"\.(pb\.go|pb\.cc|pb\.h|generated\.[a-z]+|snap|golden)$"
                    r"|(^|/)(generated|__generated__|gen)(/|$)"
                    r"|\.min\.(js|css)$|\.map$", re.I)
CI_RE = re.compile(r"(^|/)\.(github|gitlab|circleci|travis)(/|$)"
                   r"|(^|/)(Makefile|CMakeLists\.txt|Dockerfile[^/]*)$"
                   r"|\.(ya?ml|toml|ini|cfg|json|gradle|bazel|bzl|cmake)$", re.I)
FIXTURE_RE = re.compile(r"(^|/)(fixtures?|testdata|test[-_]data|samples?|"
                        r"examples?|data)(/|$)", re.I)


def categorise(path: str) -> str:
    if LOCK_RE.search(path):
        return "lockfile"
    if VENDOR_RE.search(path):
        return "vendored"
    if GEN_RE.search(path):
        return "generated"
    if TEST_RE.search(path):
        return "test"
    if FIXTURE_RE.search(path):
        return "fixture"
    if DOC_RE.search(path):
        return "doc"
    if CI_RE.search(path):
        return "config"
    return "production"


EXT_LANG = {
    ".py": "Python", ".pyi": "Python", ".pyx": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".vue": "JavaScript", ".svelte": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hxx": "C++",
    ".hh": "C++", ".inl": "C++", ".ipp": "C++", ".lxx": "C++", ".gxx": "C++",
    ".pxx": "C++", ".mm": "C++",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".rb": "Ruby", ".rake": "Ruby", ".gemspec": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".bats": "Shell",
    ".swift": "Swift", ".m": "Objective-C",
    ".scala": "Scala", ".lua": "Lua", ".pl": "Perl", ".pm": "Perl",
    ".r": "R", ".jl": "Julia", ".dart": "Dart", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".ml": "OCaml",
    ".zig": "Zig", ".nim": "Nim", ".v": "V", ".sql": "SQL",
    ".das": "Daslang", ".cmake": None, ".txt": None,
}

# ``.h`` is ambiguous; if a task's C++ evidence dominates, reassign it.
CPP_MARKERS = {".cc", ".cpp", ".cxx", ".hpp", ".hxx", ".hh"}


# Files that carry a language but no extension.
BASENAME_LANG = {
    "pkgbuild": "Shell", "makefile": "Make", "gnumakefile": "Make",
    "dockerfile": "Dockerfile", "rakefile": "Ruby", "gemfile": "Ruby",
    "vagrantfile": "Ruby", "brewfile": "Ruby", "podfile": "Ruby",
    "cmakelists.txt": "CMake", "build": "Bazel", "workspace": "Bazel",
    "configure": "Shell", "install": "Shell",
}


def lang_of(path):
    base = os.path.basename(path).lower()
    ext = os.path.splitext(path)[1].lower()
    if not ext or base in BASENAME_LANG:
        hit = BASENAME_LANG.get(base)
        if hit:
            return hit
        if base.startswith("dockerfile"):
            return "Dockerfile"
    return EXT_LANG.get(ext)
