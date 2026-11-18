import os
import random


def create_backup_test_dataset(base_dir="backup_test_dataset"):
    # Define file categories, extensions, size ranges, and quantities
    categories = {
        "1_small_text_logs": {
            "ext": [".txt", ".log", ".json", ".xml", ".cfg"],
            "size_range": (1, 6400),
            "unit": "KB",
            "count": 100,
        },
        "2_executables_scripts": {
            "ext": [".exe", ".dll", ".sh", ".py", ".bin"],
            "size_range": (100, 5000),
            "unit": "KB",
            "count": 100,
        },
        "3_documents_pictures": {
            "ext": [".pdf", ".docx", ".xlsx", ".jpg", ".png"],
            "size_range": (500, 10000),
            "unit": "KB",
            "count": 100,
        },
        "4_media_videos": {
            "ext": [".mp4", ".mov", ".mkv"],
            "size_range": (20, 5000),
            "unit": "MB",
            "count": 5,
        },
        "5_large_archives": {
            "ext": [".tar.gz", ".zip", ".iso"],
            "size_range": (50, 3000),
            "unit": "MB",
            "count": 5,
        },
    }

    print(
        f"[*] Initializing backup test dataset generation in directory: '{base_dir}'..."
    )
    total_files = 0
    total_bytes = 0

    for cat_name, props in categories.items():
        cat_dir = os.path.join(base_dir, cat_name)
        os.makedirs(cat_dir, exist_ok=True)

        print(f" -> Generating category: {cat_name} ({props['count']} files)...")

        for i in range(props["count"]):
            ext = random.choice(props["ext"])
            filename = f"sample_{i + 1:04d}{ext}"
            filepath = os.path.join(cat_dir, filename)

            # Calculate target size in bytes
            min_s, max_s = props["size_range"]
            size_val = random.randint(min_s, max_s)
            size_bytes = (
                size_val * 1024 if props["unit"] == "KB" else size_val * 1024 * 1024
            )

            # Write data simulation (Text = highly compressible, Media/Binaries = random/incompressible)
            with open(filepath, "wb") as f:
                if (
                    "text" in cat_name
                    or "documents" in cat_name
                    and ext in [".txt", ".log", ".json", ".xml", ".cfg"]
                ):
                    pattern = b"Backup performance benchmark repeating log entry string text payload... \n"
                    f.write(pattern * (size_bytes // len(pattern) + 1))
                else:
                    # Write pseudo-random blocks to simulate realistic compression/deduplication metrics
                    remaining = size_bytes
                    while remaining > 0:
                        chunk_size = min(remaining, 1024 * 1024)
                        f.write(os.urandom(chunk_size))
                        remaining -= chunk_size

            total_files += 1
            total_bytes += size_bytes

    print("\n[✔] Dataset generation complete!")
    print(f"    - Total Files: {total_files:,}")
    print(
        f"    - Total Size:  {total_bytes / (1024**2):.2f} MB (~{total_bytes / (1024**3):.2f} GB)"
    )


if __name__ == "__main__":
    create_backup_test_dataset("/home/sandeep/mixed_dataset")
