import os


def get_directory_tree(
    directory,
    ignore_spec=None,
    max_depth=2,
    depth=0,
    project_root=None,
    prefix="",
    only_dirs=False,
):
    """
    Return the directory structure in tree command format, applying .gitignore rules.

    :param directory: The directory to scan
    :param ignore_spec: PathSpec object for matching .gitignore rules
    :param max_depth: Maximum scan depth
    :param depth: Current recursion depth (used for internal recursion)
    :param project_root: Project root directory (only set on first call)
    :param prefix: Prefix symbol for the current level
    :param only_dirs: Whether to return only directory structure, defaults to returning all (directories + files)
    :return: Directory structure string
    """
    if max_depth is not None and depth >= max_depth:
        return ""  # Max depth exceeded

    if project_root is None:
        project_root = os.path.abspath(directory)

    entries = sorted(os.listdir(directory))  # Sort for deterministic order
    entries = [e for e in entries if not e.startswith(".")]  # Skip hidden files

    tree_lines = []  # Store tree lines

    for index, entry in enumerate(entries):
        path = os.path.join(directory, entry)
        relative_path = os.path.relpath(path, start=project_root)

        # Skip non-directories in dir-only mode
        if only_dirs and not os.path.isdir(path):
            continue

        # Append slash for directories
        if os.path.isdir(path):
            relative_path += "/"

        # Apply .gitignore rules
        if ignore_spec and ignore_spec.match_file(relative_path):
            continue  # Skip ignored paths

        # Check if last entry in current directory
        is_last = index == len(entries) - 1
        connector = "└── " if is_last else "├── "
        tree_lines.append(prefix + connector + entry)

        # Recurse into subdirectories in dir-only mode
        if os.path.isdir(path):
            new_prefix = prefix + ("    " if is_last else "│   ")
            sub_tree = get_directory_tree(
                path,
                ignore_spec,
                max_depth,
                depth + 1,
                project_root,
                new_prefix,
                only_dirs=only_dirs,
            )
            if sub_tree:  # Append non-empty subtree
                tree_lines.extend(sub_tree.split("\n"))

    return "\n".join(tree_lines)
