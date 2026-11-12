from pathlib import Path


def get_all_files_from_list(
    list_file_path,
) -> list[Path]:  # Step 1: Read lines from the text file into an array
    with open(list_file_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Step 2: Convert lines into Path objects (Array 1)
    path_array = [Path(line.strip()) for line in raw_lines if line.strip()]

    # Step 3: Initialize a new array to hold all final file paths
    final_files_array = []

    # Step 4: Iterate through each path and handle files vs folders
    for path in path_array:
        if not path.exists():
            print(f"Warning: Path does not exist -> {path}")
            continue

        if path.is_file():
            # If it's a file, add it directly to the new array
            final_files_array.append(path)

        elif path.is_dir():
            for item in path.rglob("*"):
                if (
                    item.is_file()
                ):  # Ensure we only add actual files, not subdirectories
                    final_files_array.append(item)

    return final_files_array


paths = get_all_files_from_list("/home/sandeep/filelist.txt")
print(len(paths))
