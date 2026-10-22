import os
import secrets
import random
import itertools
import shutil


WORDS = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliett",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
    "data",
    "testing",
    "random",
    "stream",
    "buffer",
    "system",
]


def generate_random_sentence():
    length = random.randint(5, 12)
    words = [random.choice(WORDS) for _ in range(length)]
    return " ".join(words).capitalize() + ". "


def generate_files(
    num_files=10000,
    output_dir="generated_files_old",
    min_file_size=0,
    max_file_size=100,
):
    target_bytes = max_file_size * 1024
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(
            f"Generating {num_files:,} files between {min_file_size} KB and {max_file_size} KB..."
        )

        # written_bytes = 0
        # with open(
        #     os.path.join(output_dir, "text_file.log"), "w", encoding="utf-8"
        # ) as f:
        #     while written_bytes < target_bytes:
        #         line = generate_random_sentence() + f"ID:{random.randint(1000, 9999)}\n"
        #         line_bytes = len(line.encode("utf-8"))
        #         if written_bytes + line_bytes > target_bytes:
        #             needed_bytes = target_bytes - written_bytes
        #             line = line.encode("utf-8")[:needed_bytes].decode(
        #                 "utf-8", errors="ignore"
        #             )
        #             f.write(line)
        #             break
        #         f.write(line)
        #         written_bytes += line_bytes

        for i in range(1, num_files + 1):
            file_path = os.path.join(output_dir, f"file_{i:05d}.bin")
            file_size = random.randint(1024 * min_file_size, target_bytes)
            with open(file_path, "wb") as f:
                buffer = secrets.token_bytes(target_bytes)
                f.write(buffer[:file_size])
            if i % 1000 == 0:
                print(f"Created {i:,} / {num_files:,} files")
        print(f"\nDone! All files generated in './{output_dir}'")

    except Exception as e:
        print("\n [Error]: ", e)


def generate_files_new(
    num_files=10000,
    output_dir="generated_files_old",
    min_file_size=0,
    max_file_size=100,
    num_subfolders=3,
    levels=1,
):
    target_bytes = max_file_size * 1024
    try:
        # Collect all directory paths including intermediate levels
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)

        target_dirs = [output_dir]

        if levels > 0 and num_subfolders > 0:
            for lvl in range(1, levels + 1):
                # Generate combinations up to the current level depth
                combinations = list(
                    itertools.product(range(1, num_subfolders + 1), repeat=lvl)
                )
                for combo in combinations:
                    path_parts = [output_dir] + [f"folder_{i:02d}" for i in combo]
                    target_dirs.append(os.path.join(*path_parts))

        # Create all directories
        for d in target_dirs:
            os.makedirs(d, exist_ok=True)

        print(
            f"Generating {num_files:,} files across {len(target_dirs):,} directories (including intermediate levels) "
            f"between {min_file_size} KB and {max_file_size} KB..."
        )

        # Calculate even distribution of files across ALL directories
        num_dirs = len(target_dirs)
        files_per_dir = num_files // num_dirs
        remainder = num_files % num_dirs

        file_count = 0
        for dir_idx, d in enumerate(target_dirs):
            # Distribute any leftover remainder files across the first few directories
            current_dir_files = files_per_dir + (1 if dir_idx < remainder else 0)

            for i in range(1, current_dir_files + 1):
                file_count += 1
                file_path = os.path.join(d, f"file_{file_count:05d}.bin")
                file_size = random.randint(1024 * min_file_size, target_bytes)
                with open(file_path, "wb") as f:
                    buffer = secrets.token_bytes(target_bytes)
                    f.write(buffer[:file_size])

                if file_count % 1000 == 0:
                    print(f"Created {file_count:,} / {num_files:,} files")

        print(
            f"\nDone! All files generated across intermediate and leaf folders in './{output_dir}'"
        )

    except Exception as e:
        print("\n [Error]: ", e)

def generate_files_safe(
    num_files=10000,
    output_dir="generated_files_safe",
    min_file_size=0,
    max_file_size=100,
    num_subfolders=3,
    levels=1,
):
    max_bytes = max_file_size * 1024
    min_bytes = min_file_size * 1024

    try:
        if os.path.exists(output_dir):
            print(f"Removing existing directory: {output_dir}")
            shutil.rmtree(output_dir)

        target_dirs = [output_dir]

        if levels > 0 and num_subfolders > 0:
            for lvl in range(1, levels + 1):
                combinations = itertools.product(range(1, num_subfolders + 1), repeat=lvl)
                for combo in combinations:
                    path_parts = [output_dir] + [f"folder_{i:02d}" for i in combo]
                    target_dirs.append(os.path.join(*path_parts))

        # Create all directories
        for d in target_dirs:
            os.makedirs(d, exist_ok=True)

        print(
            f"Generating {num_files:,} files across {len(target_dirs):,} directories "
            f"({min_file_size} KB to {max_file_size} KB)..."
        )

        num_dirs = len(target_dirs)
        files_per_dir = num_files // num_dirs
        remainder = num_files % num_dirs

        # Pre-generate a single large random token buffer to avoid overhead
        # (Size equal to max requested file size)
        master_buffer = secrets.token_bytes(max_bytes)

        file_count = 0
        for dir_idx, d in enumerate(target_dirs):
            current_dir_files = files_per_dir + (1 if dir_idx < remainder else 0)

            for _ in range(current_dir_files):
                file_count += 1
                file_path = os.path.join(d, f"file_{file_count:05d}.bin")
                
                # Random size between min and max
                file_size = random.randint(min_bytes, max_bytes)
                
                # Slice from the pre-generated buffer instead of calling token_bytes repeatedly
                with open(file_path, "wb") as f:
                    f.write(master_buffer[:file_size])

                if file_count % 1000 == 0:
                    print(f"Created {file_count:,} / {num_files:,} files")

        print(f"\nDone! All files generated in './{output_dir}'")

    except Exception as e:
        print("\n[Error]:", e)

if __name__ == "__main__":
    random.seed(12345)
    try:
        creation_path = input("Creation Path : ").strip()
        total_files = int(input("No of files to create: ").strip())
        min_file_size = int(input("Min File Size in KB: ").strip())
        max_file_size = int(input("Max File Size in KB: ").strip())
        max_levels = int(input("Folder Levels: [default 0] : ").strip()) or 0
        max_folders = int(input("Number of folders: [default 0] : ").strip()) or 0
        generate_files_safe(
            total_files,
            creation_path,
            min_file_size,
            max_file_size,
            max_folders,
            max_levels,
        )
    except ValueError:
        print("\n [Error]: Number of files, min size and max size should be integer")
