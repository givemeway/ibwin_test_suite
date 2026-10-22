from __future__ import annotations

import argparse
import shutil
import json
import csv
import os
import shlex
import time
from pathlib import Path
from typing import List

from .config import load_builds, load_files, getFilePaths
from .core.idevsutil import IdevsUtil
from .models import Environment
from .suites.regression import Regression
from .suites.search import SearchSuite
from .utils import get_all_files_from_list, sha256_chunked, verify_chunk
from .db import FileTreeDatabase


def extract_files():
    file_list = "files_nt.json" if os.name == "nt" else "files.json"
    normal_files = []
    split_files = []
    cbt_files = []
    link_files = []
    for key, files in load_files(file_list):
        if key == "files":
            normal_files.extend(files)
        if key == "split_files":
            split_files.extend(files)
        if key == "cbt_files":
            cbt_files.extend(files)
        if key == "link_files":
            link_files.extend(files)
    return {
        "files": normal_files,
        "split_files": split_files,
        "cbt_files": cbt_files,
        "link_files": link_files,
    }


class Console:
    def __init__(self):
        self.env = Environment()
        self.env.workspace = self.env.workspace.resolve()
        self.env.workspace.mkdir(parents=True, exist_ok=True)
        # self.build = BUILDS["1"]
        self.builds = load_builds("builds.json")
        all_files = extract_files()
        # self.testFiles = [
        #     file
        #     for key, files in load_files(
        #         "files_nt.json" if os.name == "nt" else "files.json"
        #     )
        #     for file in files
        # ]
        self.testFiles = all_files["files"]
        self.splitFiles = all_files["split_files"]
        self.cbtFiles = all_files["cbt_files"]
        self.linkFiles = all_files["link_files"]
        self.testFiles.sort()
        self.build = self.builds["1"]
        self.history_path = self.env.workspace / "history.json"
        self.history = self.load_history()
        self.run_dir: Path = Path("/")
        self.conn = self.db()

    def db(self):
        return FileTreeDatabase()

    def delete_account(self):
        # self.env.username = "sanity03"
        acc_path = os.path.join(self.env.userRoot, self.env.username)
        db_path = Path(os.getcwd()).joinpath("filetree.db")
        db_path_shm = Path(os.getcwd()).joinpath("filetree.db-shm")
        db_path_wal = Path(os.getcwd()).joinpath("filetree.db-wal")

        try:
            print("Deleting User Root .. ", acc_path)
            if Path(acc_path).exists():
                shutil.rmtree(acc_path)
            if db_path.exists() or (db_path_shm.exists() or db_path_wal.exists()):
                if self.conn is not None:
                    self.conn.close()
                print("Deleting User DB ..", db_path)
                try:
                    os.remove(db_path)
                    os.remove(db_path_shm)
                    os.remove(db_path_wal)

                except Exception as e:
                    print(e)

        except Exception as e:
            print(f"Error deleting Account folder: {acc_path} | ", e)
            return

    def create_account(self, isSuiteRunning: bool = False):
        self.run_common("create_account", "create-account", isSuiteRunning)

    def run_sanity_suite(self):
        # 1. Delete old account
        self.delete_account()
        self.conn = self.db()
        # 2. create account & configure account
        self.create_account(isSuiteRunning=True)
        # 3. run the backup
        backup_set = input("Existing Backup Set : [ y / n] : ").strip()
        isBackupSet: bool = False
        if backup_set.lower() == "y":
            isBackupSet = True

        if isBackupSet:
            self.testFiles = []

        self.regression(
            filenames=self.testFiles,
            split_filenames=self.splitFiles,
            cbt_filenames=self.cbtFiles,
            link_filenames=self.linkFiles,
            isBackupSet=isBackupSet,
        )
        # build the file & folder list in the sqlite3 tables
        # files = getFilePaths(self.run_dir, self.testFiles)
        self.search_suite().run_full_suite()
        self.conn.close()
        # accumulate the results

    def search_suite(self, files: list[Path] = []) -> SearchSuite:
        run = (
            self.env.workspace
            / f"search_suite_{self.build.name.lower()}_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        self.run_dir = run
        if len(files) == 0:
            files = getFilePaths(
                run_dir=self.run_dir, source="source", filenames=self.testFiles
            )

        return SearchSuite(
            IdevsUtil(self.build, self.env, run), run, db=self.conn, files=files
        )

    def load_history(self):
        if self.history_path.exists():
            try:
                return json.loads(self.history_path.read_text(encoding="utf-8"))
            except:
                return
        return []

    def history_add(self, command, result=None):
        self.history.append(
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "build": self.build.name,
                "release": self.build.release,
                "command": command,
                "return_code": None if result is None else result["return_code"],
            }
        )
        self.history = self.history[-500:]
        self.history_path.write_text(
            json.dumps(self.history, indent=2), encoding="utf-8"
        )

    def configure(self, args=[], isReconfigure=False):
        if isReconfigure:
            print("\nEnvironment Re-Configuration")
            self.env.username = (
                input(f"Username [{self.env.username}]: ").strip() or self.env.username
            )
            self.env.server = (
                input(f"Server address [{self.env.server}]: ").strip()
                or self.env.server
            )
            self.env.device_id = (
                input(f"Device ID [{self.env.device_id}]: ").strip()
                or self.env.device_id
            )
            self.env.private_key = (
                input(f"Private key [{self.env.private_key}]: ").strip()
                or self.env.private_key
            )

            self.env.password = (
                input(f"Account password [{self.env.password}]: ").strip()
                or self.env.password
            )
            self.env.remote_root = (
                input(f"Remote root [{self.env.remote_root}]: ").strip()
                or self.env.remote_root
            )
            self.env.computer_name = (
                input(f"Computer name [{self.env.computer_name}]: ").strip()
                or self.env.computer_name
            )
            self.env.port = (
                int(input(f"Port [{self.env.port}]: ").strip()) or self.env.port
            )
            self.env.use_utf8_encryption = (
                int(input(f"UTF8-CMD [{self.env.use_utf8_encryption}]").strip())
                or self.env.use_utf8_encryption
            )
            self.env.dedup = (
                int(input(f"DeDup [{self.env.dedup}]").strip()) or self.env.dedup
            )
            self.env.fileListPath = (
                input(f"FileList Path: [{self.env.fileListPath}]").strip()
                or self.env.fileListPath
            )
            self.env.workspace = (
                Path(input(f"Workspace : [{self.env.workspace}]").strip())
                or self.env.workspace
            )
            self.env.syncDedup = (
                int(input(f"SyncDedup : [{self.env.syncDedup}]").strip())
                or self.env.syncDedup
            )
            self.env.server_root = (
                input(f"Server Root : [{self.env.server_root}]").strip()
                or self.env.server_root
            )

        else:
            if isinstance(args, argparse.Namespace):
                self.env.username = args.user
                self.env.server = args.server
                self.env.device_id = args.device_id
                self.env.private_key = args.pvt_key
                self.env.password = args.password
                self.env.port = args.port
                self.env.use_utf8_encryption = args.utf8_cmd
                self.env.dedup = args.dedup
                self.env.fileListPath = args.fileListPath
                self.env.workspace = args.workspace
                self.env.syncDedup = args.sync_dedup
                self.env.server_root = args.server_root
                print("\n" + "-" * 90)
                print("Environment Configured")
                print("-" * 90)
                print(f"\n Username         : [{self.env.username}]")
                print(f"\n Server           : [{self.env.server}]")
                print(f"\n Device ID        : [{self.env.device_id}]")
                print(f"\n Pvt Key          : [{self.env.private_key}]")
                print(f"\n Password         : [{self.env.password}]")
                print(f"\n PORT             : [{self.env.port}]")
                print(f"\n IS_TEST_MACHINE  : [{self.env.is_test_machine}]")
                print(f"\n USE UTF-8 ENC    : [{self.env.use_utf8_encryption}]")
                print(f"\n DEDUP            : [{self.env.dedup}]")
                print(f"\n FileListPath     : [{self.env.fileListPath}]")
                print(f"\n Workspace        : [{self.env.workspace}]")
                print(f"\n SyncDedup        : [{self.env.syncDedup}]")
                print(f"\n Server Root      : [{self.env.server_root}]")
                print("\n" + "-" * 90)

            else:
                self.env.username = (
                    input(f"Username [{self.env.username}]: ").strip()
                    or self.env.username
                )
                self.env.server = (
                    input(f"Server address [{self.env.server}]: ").strip()
                    or self.env.server
                )
                self.env.device_id = (
                    input(f"Device ID [{self.env.device_id}]: ").strip()
                    or self.env.device_id
                )
                self.env.private_key = (
                    input(f"Private key [{self.env.private_key}]: ").strip()
                    or self.env.private_key
                )

                self.env.password = (
                    input(f"Account password [{self.env.password}]: ").strip()
                    or self.env.password
                )
                self.env.remote_root = (
                    input(f"Remote root [{self.env.remote_root}]: ").strip()
                    or self.env.remote_root
                )
                self.env.computer_name = (
                    input(f"Computer name [{self.env.computer_name}]: ").strip()
                    or self.env.computer_name
                )
                self.env.use_utf8_encryption = (
                    int(input(f"UTF8-CMD [{self.env.use_utf8_encryption}]").strip())
                    or self.env.use_utf8_encryption
                )
                self.env.dedup = (
                    int(input(f"DeDup [{self.env.dedup}]").strip()) or self.env.dedup
                )
                self.env.fileListPath = (
                    input(f"FileList Path: [{self.env.fileListPath}]").strip()
                    or self.env.fileListPath
                )
                self.env.workspace = (
                    Path(input(f"Workspace : [{self.env.workspace}]").strip())
                    or self.env.workspace
                )
                self.env.syncDedup = (
                    int(input(f"SyncDedup : [{self.env.syncDedup}]").strip())
                    or self.env.syncDedup
                )
                self.env.server_root = (
                    input(f"Server Root : [{self.env.server_root}]").strip()
                    or self.env.server_root
                )
        if not isReconfigure:
            print("Environment Configuration")
            print("-" * 90)
        w = input(f"Workspace [{self.env.workspace}]: ").strip() or self.env.workspace
        if w:
            self.env.workspace = Path(w).resolve()
            self.env.workspace.mkdir(parents=True, exist_ok=True)
            self.history_path = self.env.workspace / "history.json"
            self.history = self.load_history()

    def select_build(self):
        print("\n")
        for build_id, build in self.builds.items():
            print(
                f"{build_id}. {build.name} - {build.release} - {build.release_date} - {build.working_dir} - {build.executable}"
            )
        c = input("Build : ").strip()
        if c in self.builds:
            self.build = self.builds[c]
            print(f"Selected: {self.build.name}")

    def tool(self, name="run"):
        self.run_dir = (
            self.env.workspace
            / f"{name if name != 'run' else 'run'}_{self.build.name.lower()}_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return IdevsUtil(self.build, self.env, self.run_dir)

    def regression(
        self,
        filenames: list[str] = [],
        split_filenames: list[str] = [],
        cbt_filenames: list[str] = [],
        link_filenames: list[str] = [],
        isBackupSet: bool = False,
    ):
        # mb: int
        # filename: str

        # try:
        # mb = int(input("Test file size in MB [20]: ").strip() or "20")
        # filename = input(" File name: ").strip() or "Sandeep.txt"
        # label = input("Set Label: ").strip() or ""
        # except ValueError:
        #    print("Invalid size.")
        #    return
        self.run_dir = (
            self.env.workspace
            / f"regression_{self.build.name.lower()}_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)

        files: list[Path] = []
        split_files: list[Path] = []
        cbt_files: list[Path] = []
        link_files: list[Path] = []

        if isBackupSet:
            files = get_all_files_from_list(Path(self.env.fileListPath))

        if not isBackupSet:
            files = getFilePaths(self.run_dir, filenames, source="source")
            split_files = getFilePaths(
                self.run_dir, split_filenames, source="split_source"
            )
            cbt_files = getFilePaths(self.run_dir, cbt_filenames, source="cbt_source")
            link_files = getFilePaths(
                self.run_dir, link_filenames, source="link_source"
            )
        Regression(
            IdevsUtil(
                self.build,
                self.env,
                self.run_dir,
                isRegression=True,
                filename="sandeep.txt",
            ),
            self.run_dir,
            size_mb=1,
            db=self.conn,
            filename="sandeep.txt",
            label="",
        ).run(
            files=files,
            split_files=split_files,
            cbt_files=cbt_files,
            link_files=link_files,
        )
        self.history_add("REGRESSION")

    def compare(self):
        mb: int
        filename: str
        label: str = ""
        try:
            mb = int(input("Test file size in MB [20]: ").strip() or "20")
            filename = input("Filename: ").strip()
            label = input("Backup Label: ").strip() or ""
        except ValueError:
            print("Invalid size.")
            return

        root = self.env.workspace / f"comparison_{time.strftime('%Y%m%d_%H%M%S')}"
        root.mkdir(parents=True, exist_ok=True)
        all_results = {}

        for build in self.builds.values():
            if build.osname == "nt":
                run = root / build.name.lower()
                run.mkdir(parents=True, exist_ok=True)
                suite = Regression(
                    IdevsUtil(
                        build, self.env, run, isRegression=True, filename=filename
                    ),
                    run,
                    mb,
                )
                suite.run()
                all_results[build.name] = {r.test_id: r for r in suite.results}
            if build.osname == "posix":
                run = root / build.name.lower()
                run.mkdir(parents=True, exist_ok=True)
                suite = Regression(
                    IdevsUtil(
                        build, self.env, run, isRegression=True, filename=filename
                    ),
                    run,
                    mb,
                )
                suite.run()
                all_results[build.name] = {r.test_id: r for r in suite.results}

        ids = sorted(set(all_results["Prod"]) | set(all_results["Test"]))
        csv_path = root / "production_vs_test.csv"

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Test ID", "Description", "Production", "Test", "Comparison"])
            for tid in ids:
                p, t = all_results["Prod"].get(tid), all_results["Test"].get(tid)
                ps = p.status if p else "NOT RUN"
                ts = t.status if t else "NOT RUN"
                w.writerow(
                    [
                        tid,
                        p.description if p else t.description,
                        ps,
                        ts,
                        "MATCH" if ps == ts else "DIFFERENT",
                    ]
                )

        print(f"\nBuild comparison report: {csv_path}")

    def run_common(self, method, history_name, isSuiteRunning: bool = False):
        r = getattr(self.tool(), method)(isSuiteRunning)
        if r:
            self.history_add(history_name, r)

    def show_history(self):
        if not self.history:
            print("No command history.")
            return
        print("\nTime                Build       Command")
        print("-" * 80)
        for x in self.history:
            print(f"{x['time']}  {x['build']:<10}  {x['command']}")

    def cbt_integrity_check(self):
        src_path = input(" Source File Path: ").strip()
        dst_path = input(" Path to the file to verify: ").strip()
        chunked_hashes: List[str] = sha256_chunked(Path(src_path), 1024 * 1024)
        for chunk_index, chunk_hash in enumerate(chunked_hashes):
            checked = verify_chunk(
                Path(dst_path), chunk_index, chunk_hash, chunk_size=1024 * 1024
            )
            result = "PASS" if checked else "FAIL"
            print(f" Verified Chunk Index: {chunk_index + 1} |  Result: {result}")

    def menu(self):
        print("\n" + "=" * 90)
        print("                 IDEVSUTIL QA AUTOMATION CONSOLE")
        print("=" * 90)
        print(
            f"Build: {self.build.name} | {self.build.release} | {self.build.release_date}"
        )
        print(f"Exe  : {self.build.executable}")
        print(f"User : {self.env.username or '<not configured>'}")
        print(f"Dev  : {self.env.device_id or '<not configured>'}")
        print("-" * 90)
        print(" 1  Select Build")
        print(" 2  Configure Environment")
        print(" 3  Regression Testing")
        print(" 4  Regression Testing - ALL Builds")
        print(" 5  Auth List")
        print(" 6  Device List")
        print(" 7  Version Information")
        print(" 8  Search")
        print(" 9  Properties")
        print("10  Get Quota")
        print("11  Server Version")
        print("12  Client Version")
        print("13  Get Size")
        print("14  Items Status")
        print("15  Verify Files")
        print("16  Create Checksum")
        print("17  Snapshot")
        print("18  Custom idevsutil Command")
        print("19  Command History")
        print("20  Clear Screen")
        print("21  Backup Files/Folders")
        print("22  Download Files/Folders")
        print("23  Create Dir")
        print("24  Get Empty Folders")
        print("25  Get ENC Password")
        print("26  Delete Files/Folders")
        print("27  List Trash")
        print("28  Empty Trash")
        print("29  File Status")
        print("30  Config Account")
        print("31  Create Account")
        print("32  Verify Account")
        print("33  CBT Integrity Check")
        print("34  Create Bucket")
        print("35  Extended List-->Yet to implement")
        print("36  Rename Item")
        print("37  Trash to Original")
        print("38  Set Label")
        print("39  Search Label")
        print("40  Set label along backup")
        print("41  Search Suite")
        print("42  Run Sanity Suite")
        print("43  Link Backup")
        print("44  Create Link")
        print("45  Dedup Search and Create Link")
        print(" 0  Exit")
        print("-" * 90)

    def run(self):
        while True:
            self.menu()
            c = input("QA > ").strip().lower()
            try:
                if c == "0":
                    print("Exiting.")
                    return
                if c == "1":
                    self.select_build()
                elif c == "2":
                    self.configure([], True)
                elif c == "3":
                    self.run_sanity_suite()
                elif c == "4":
                    self.compare()
                elif c == "5":
                    self.run_common("auth_list", "auth-list")
                elif c == "6":
                    self.run_common("device_list", "device-list")
                elif c == "7":
                    self.run_common("version_info", "version-info")
                elif c == "8":
                    self.search_suite().menu()
                    # self.run_common("search", "search")
                elif c == "9":
                    self.run_common("properties", "properties")
                elif c == "10":
                    self.run_common("quota", "get-quota")
                elif c == "11":
                    self.run_common("server_version", "server-version")
                elif c == "12":
                    self.run_common("client_version", "client-version")
                elif c == "13":
                    self.run_common("get_size", "get-size")
                elif c == "14":
                    self.run_common("items_status", "items-status3")
                elif c == "15":
                    self.run_common("verify_files", "verify-files2")
                elif c == "16":
                    self.run_common("create_checksum", "create-chk")
                elif c == "17":
                    self.run_common("snapshot", "snapshot")
                elif c == "18":
                    self.run_common("custom", "custom")
                elif c == "19":
                    self.show_history()
                elif c == "20":
                    self.run_common("clear_screen", "clear-screen")
                elif c == "21":
                    self.run_common("backup", "manual-backup")
                elif c == "22":
                    self.run_common("download", "manual-download")
                elif c == "23":
                    self.run_common("create_dir", "create-dir")
                elif c == "24":
                    self.run_common("get_empty_folders", "get-empty-folders")
                elif c == "25":
                    self.run_common("get_enc_psd", "get-enc-psd")
                elif c == "26":
                    self.run_common("delete_items", "delete-items")
                elif c == "27":
                    self.run_common("list_trash", "list-trash")
                elif c == "28":
                    self.run_common("empty_trash", "empty-trash")
                elif c == "29":
                    self.run_common("file_status", "file-status")
                elif c == "30":
                    self.run_common("config_account", "config-account")
                elif c == "31":
                    self.run_common("create_account", "create-account")
                elif c == "32":
                    self.run_common("verify_account", "verify-account")
                elif c == "33":
                    self.cbt_integrity_check()
                elif c == "34":
                    self.run_common("create_bucket", "create-bucket")
                elif c == "35":
                    self.run_common("extended_list_search", "extended-list-search")
                elif c == "36":
                    self.run_common("rename_item", "rename-item")
                elif c == "37":
                    self.run_common("move_to_original", "move-to-original")
                elif c == "38":
                    self.run_common("set_label", "set-label")
                elif c == "39":
                    self.run_common("search_label", "search-label")
                elif c == "40":
                    self.run_common("set_label_along_backup", "set-label-along-backup")
                elif c == "41":
                    self.run_common("search_suite", "search-suite")
                elif c == "42":
                    self.run_sanity_suite()
                elif c == "43":
                    self.run_common("link_backup", "link-backup")
                elif c == "44":
                    self.run_common("create_link", "create_link")
                elif c == "45":
                    self.run_common(
                        "dedup_search_and_create_link", "dedup_search_and_create_link"
                    )
                else:
                    print("Invalid option.")
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
            except Exception as e:
                print(f"\nERROR: {e}")
