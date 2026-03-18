from __future__ import annotations


from src.apple_git.tree import generate_tree


def test_generate_tree_basic(tmp_path):
    """Test basic tree generation with files and directories."""
    (tmp_path / "file1.txt").write_text("content")
    (tmp_path / "dir1").mkdir()
    (tmp_path / "dir1" / "file2.py").write_text("content")
    (tmp_path / "dir2").mkdir()
    (tmp_path / "dir2" / "sub_dir").mkdir()
    (tmp_path / "dir2" / "sub_dir" / "file3.md").write_text("content")

    expected_tree = f"""{tmp_path.name}/
├── dir1/
│   └── file2.py
├── dir2/
│   └── sub_dir/
└── file1.txt"""
    assert generate_tree(tmp_path) == expected_tree


def test_generate_tree_max_depth(tmp_path):
    """Test tree generation with max_depth limit."""
    (tmp_path / "dir1").mkdir()
    (tmp_path / "dir1" / "dir2").mkdir()
    (tmp_path / "dir1" / "dir2" / "dir3").mkdir()
    (tmp_path / "dir1" / "dir2" / "dir3" / "file.txt").write_text("content")

    expected_tree_depth_1 = f"""{tmp_path.name}/
└── dir1/"""
    assert generate_tree(tmp_path, max_depth=1) == expected_tree_depth_1

    expected_tree_depth_2 = f"""{tmp_path.name}/
└── dir1/
    └── dir2/"""
    assert generate_tree(tmp_path, max_depth=2) == expected_tree_depth_2


def test_generate_tree_ignore_patterns(tmp_path):
    """Test tree generation respects ignore patterns."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("content")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "foo.pyc").write_text("content")
    (tmp_path / "important.py").write_text("content")
    (tmp_path / "temp.pyc").write_text("content")

    expected_tree = f"""{tmp_path.name}/
└── important.py"""
    assert generate_tree(tmp_path) == expected_tree


def test_generate_tree_max_files(tmp_path):
    """Test tree generation with max_files limit."""
    for i in range(10):
        (tmp_path / f"file{i}.txt").write_text("content")

    _expected_tree = f"""{tmp_path.name}/
├── file0.txt
├── file1.txt
├── file2.txt
├── file3.txt
├── file4.txt
├── file5.txt
├── file6.txt
├── file7.txt
├── file8.txt
├── file9.txt"""
    # max_files is 60 by default in tree.py, let's test with a smaller limit
    assert generate_tree(tmp_path, max_files=5) == f"""{tmp_path.name}/
├── file0.txt
├── file1.txt
├── file2.txt
├── file3.txt
├── file4.txt
..."""


def test_generate_tree_empty_dir(tmp_path):
    """Test tree generation for an empty directory."""
    expected_tree = f"{tmp_path.name}/"
    assert generate_tree(tmp_path) == expected_tree


def test_generate_tree_single_file(tmp_path):
    """Test tree generation for a single file in the root."""
    (tmp_path / "single_file.txt").write_text("content")
    expected_tree = f"""{tmp_path.name}/
└── single_file.txt"""
    assert generate_tree(tmp_path) == expected_tree
