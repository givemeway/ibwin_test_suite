import concurrent.futures
from pathlib import Path
import datetime
import subprocess
import time

NUM_INSTANCES = 1

run_dir = "/home/sandeep/QA/NO_TLS_PERF_TEST-16-11-2026-RUN-1"
script_path = "/home/sandeep/idevsutil_qa_package/main.py"
filelist_path = "/home/sandeep/filelist.txt"


def run_instance(instance_id):
    start_time = datetime.datetime.now()

    log_filename = f"{run_dir}/instance_{instance_id}_no_tls_run_1_16th_nov.log"

    cmd = [
        "python3.14",
        script_path,
        "--user",
        "test6",
        "--server",
        "evstlsserver.idrive.com",
        "--port",
        "443",
        "--tls",
        "0",
        "--dedup",
        "1",
        "--workspace",
        run_dir,
        "--password",
        "1234",
        "--auto-run",
        "1",
        "--fileListPath",
        filelist_path,
    ]

    print(f"[{start_time.strftime('%H:%M:%S')}] Starting instance {instance_id}")

    # Open a dedicated log file for each instance to capture stdout/stderr
    with open(log_filename, mode="w", buffering=1) as log_file:
        process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        process.wait()  # Blocks this thread until this specific process finishes

    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(
        f"[{end_time.strftime('%H:%M:%S')}] Completed instance {instance_id} in"
        f" {duration:.2f}s"
    )
    return instance_id, start_time, end_time, duration, process.returncode


def main():
    batch_start = datetime.datetime.now()
    print(f"=== Batch started at {batch_start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    results = []
    # ThreadPoolExecutor spawns 18 concurrent threads that manage the subprocesses
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_INSTANCES) as executor:
        futures = [
            executor.submit(run_instance, i) for i in range(1, NUM_INSTANCES + 1)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    batch_end = datetime.datetime.now()
    total_duration = (batch_end - batch_start).total_seconds()

    print("\n=== Batch Execution Summary ===")
    print(f"Total batch wall-clock time: {total_duration:.2f} seconds\n")
    print(
        f"{'ID':<4} | {'Start Time':<10} | {'End Time':<10} | {'Duration':<10} | {'Exit Code'}"
    )
    print("-" * 55)
    for res in sorted(results, key=lambda x: x[0]):
        print(
            f"{res[0]:<4} | {res[1].strftime('%H:%M:%S'):<10} |"
            f" {res[2].strftime('%H:%M:%S'):<10} | {res[3]:>6.2f}s    | {res[4]}"
        )


if __name__ == "__main__":
    try:
        if not Path(run_dir).exists():
            print("Creating Dir ->", run_dir)
            Path(run_dir).mkdir(exist_ok=True, parents=True)
    except Exception as e:
        print(e)
    main()
