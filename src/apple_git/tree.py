from __future__ import annotations

import os
from pathlib import Path


def generate_tree(root: Path, max_depth: int = 2, max_files: int = 60) -> str:
    """Generate a string representation of the file tree."""
    output = []
    file_count = 0
    
    # Standard ignore patterns
    ignore_dirs = {
        ".git", "__pycache__", ".pytest_cache", ".ruff_cache", 
        "node_modules", "venv", "env", "build", "dist", ".idea", ".vscode",
        ".claude", ".github"
    }
    ignore_exts = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".DS_Store"}

    def _walk(path: Path, depth: int, prefix: str):
        nonlocal file_count
        if depth > max_depth or file_count >= max_files:
            return

        try:
            # Sort: directories first, then files
            entries = sorted(
                list(path.iterdir()),
                key=lambda e: (not e.is_dir(), e.name.lower())
            )
        except PermissionError:
            return

        filtered = [
            e for e in entries
            if e.name not in ignore_dirs and e.suffix not in ignore_exts
        ]

        for i, entry in enumerate(filtered):
            if file_count >= max_files:
                output.append(f"{prefix}...")
                return

            is_last = i == len(filtered) - 1
            connector = "└── " if is_last else "├── "
            
            output.append(f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}")
            
            if entry.is_dir() and (depth + 1 <= max_depth):
                _walk(entry, depth + 1, prefix + ("    " if is_last else "│   "))
            else:
                file_count += 1

    output.append(root.name + "/")
    _walk(root, 0, "")
    return "\n".join(output)
