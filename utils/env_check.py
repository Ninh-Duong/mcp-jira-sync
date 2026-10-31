import importlib
import sys
from typing import List, Tuple

REQUIRED_PYTHON_VERSION: Tuple[int, int] = (3, 10)
REQUIRED_PACKAGES: List[Tuple[str, str]] = [
    ("mcp", "mcp"),
    ("httpx", "httpx"),
    ("dotenv", "python-dotenv"),
    ("cryptography", "cryptography"),
]


def check_python_version() -> Tuple[bool, str]:
    """Validates that running Python version satisfies requirements."""
    current = sys.version_info
    if (current.major, current.minor) < REQUIRED_PYTHON_VERSION:
        return (
            False,
            f"Python {REQUIRED_PYTHON_VERSION[0]}.{REQUIRED_PYTHON_VERSION[1]}+ is required. Current: {current.major}.{current.minor}.{current.micro}",
        )
    return True, f"Python {current.major}.{current.minor}.{current.micro} (OK)"


def check_dependencies() -> List[Tuple[str, bool, str]]:
    """Checks whether required packages can be imported."""
    results = []
    for module_name, package_name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(module_name)
            results.append((package_name, True, "Installed"))
        except ImportError:
            results.append((package_name, False, "Missing"))
    return results


def verify_environment(exit_on_error: bool = False) -> bool:
    """Performs full pre-flight environment checks.

    Returns True if environment is completely ready, False otherwise.
    """
    py_ok, py_msg = check_python_version()
    dep_results = check_dependencies()
    all_deps_ok = all(ok for _, ok, _ in dep_results)

    if not py_ok or not all_deps_ok:
        # stderr: stdout is reserved for JSON-RPC when this runs inside the MCP server
        err = sys.stderr
        print("\n[PRE-FLIGHT CHECK FAILED] Environment is not ready:", file=err)
        if not py_ok:
            print(f"  - {py_msg}", file=err)
        for pkg, ok, status in dep_results:
            if not ok:
                print(f"  - Missing package: {pkg} ({status})", file=err)
        print("\nResolution: Run the following command in terminal:", file=err)
        print("  pip install -r requirements.txt\n", file=err)

        if exit_on_error:
            sys.exit(1)
        return False

    return True


if __name__ == "__main__":
    py_ok, py_msg = check_python_version()
    print(f"[*] {py_msg}")
    for pkg, ok, status in check_dependencies():
        mark = "OK" if ok else "FAIL"
        print(f"[*] {pkg}: {status} [{mark}]")
    if verify_environment():
        print("\n[SUCCESS] Environment check passed. Ready to run!")
    else:
        sys.exit(1)
