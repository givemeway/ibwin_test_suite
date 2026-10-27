from __future__ import annotations
import concurrent.futures
import threading

import os
import uuid
import re
import csv, json
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Dict
from dataclasses import asdict

from ..config import load_builds
from ..models import Build, Environment, Result
from ..utils import (
    command_line,
    compare_dicts_and_format,
    create_arg_file,
    create_checksum_dict,
    create_cred_file,
    create_enc_file,
    create_file_dict,
    create_utf8_file,
    create_test_file,
    get_all_files_from_list,
    sha256,
    extract_repo_info,
)


class IdevsUtil:
    def __init__(
        self,
        build: Build,
        env: Environment,
        run_dir: Path,
        isRegression: bool = False,
        filename="sandeep.txt",
    ):
        self.build = build
        self.builds = load_builds("builds.json")
        self.isRegression = isRegression
        self.filename = filename
        self.isBuildToggled = False
        self.source = run_dir / "source" / self.filename
        self.env = env
        self.run_dir = run_dir
        self.label = Path(run_dir).name
        self.logs = run_dir / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.chunk_size = 1000
        self.cooldown_seconds = 2
        self.workers = 4
        self.results = []
        self.lock = threading.Lock()

    def add(self, tid, desc, status, expected, actual, build, details=""):
        self.results.append(Result(tid, desc, status, expected, actual, build, details))
        print(f"[{status}] {tid} - {desc}")

    def resetRegression(self):
        self.isRegression = False

    def toogleBuild(self, value: bool):
        self.isBuildToggled = value

    def resetBuildToOriginal(self):
        opposite_build = self.build.oppositeBuild
        self.build = self.builds[opposite_build]

    def remote(self, path=""):
        root = self.env.remote_root.strip("/")
        base = f"{self.env.username}@{self.env.server}::{root}/"
        return base + path.lstrip("/") if path else base

    def convert_to_utf8_enc_cmd(
        self, args: List[str], executable: str
    ) -> List[str] | None:
        if self.build.isTestBed == 1 and self.env.port:
            args.append(f"--port={self.env.port}")

        if self.env.device_id and int(self.env.dedup) == 1:
            args.append(f"--device-id={self.env.device_id}")

        argFilePath = Path(self.build.working_dir).joinpath("args.txt")
        utf8FilePath = Path(self.build.working_dir).joinpath("args_1.txt")
        create_arg_file(args, argFilePath)
        utf_arg = []
        enc_exe = Path(self.build.working_dir).joinpath(self.build.executable + "_enc")

        utf_arg.append(str(enc_exe))
        utf_arg.append(str(argFilePath))
        utf_arg.append("1")
        enc_psd: str = ""
        enc_pk: str = ""
        enc_cmd: str = ""

        cred_args = []
        cred_args.append(executable)
        if self.env.private_key:
            cred_args.append(f"--string-encode={self.env.private_key}")
        else:
            cred_args.append(f"--string-encode={self.env.password}")
        try:
            p = subprocess.run(
                cred_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.env.timeout,
            )
            rc, out, err = p.returncode, p.stdout, p.stderr
            enc_pk = out.split("Encoded string=")[1].strip("\n")
            if err:
                print("\n--- STDERR ---")
                print(err)
                return

        except subprocess.TimeoutExpired as e:
            rc, out, err = -1, e.stdout or "", f"TIMEOUT after {self.env.timeout}s"
            return
        except Exception as e:
            rc, out, err = -1, "", str(e)
            return

        cred_args = []
        cred_args.append(executable)
        cred_args.append(f"--string-encode={self.env.password}")

        try:
            p = subprocess.run(
                cred_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.env.timeout,
            )
            rc, out, err = p.returncode, p.stdout, p.stderr
            enc_psd = out.split("Encoded string=")[1].strip("\n")
            if err:
                print("\n--- STDERR ---")
                print(err)
                return

        except subprocess.TimeoutExpired as e:
            rc, out, err = -1, e.stdout or "", f"TIMEOUT after {self.env.timeout}s"
            return
        except Exception as e:
            rc, out, err = -1, "", str(e)
            return

        credFilePath = Path(self.build.working_dir).joinpath("args.txt" + "_.c9fd7dd")
        create_cred_file(credFilePath, enc_psd, enc_pk)

        try:
            p = subprocess.run(
                utf_arg,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.env.timeout,
            )
            rc, out, err = p.returncode, p.stdout, p.stderr
            enc_str = out.split("Encrypted Output:")[1].strip("\n")
            if err:
                print("\n--- STDERR ---")
                print(err)
                return
            create_enc_file(enc_str, argFilePath)
            create_utf8_file(utf8FilePath, str(argFilePath))

        except subprocess.TimeoutExpired as e:
            rc, out, err = -1, e.stdout or "", f"TIMEOUT after {self.env.timeout}s"
            return
        except Exception as e:
            rc, out, err = -1, "", str(e)
            return

        utf_arg = []
        utf_arg.append(str(enc_exe))
        utf_arg.append(str(utf8FilePath))
        utf_arg.append("1")
        try:
            p = subprocess.run(
                utf_arg,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.env.timeout,
            )
            rc, out, err = p.returncode, p.stdout, p.stderr
            enc_cmd = out.split("Encrypted Output:")[1].strip("\n")
            if err:
                print("\n--- STDERR ---")
                print(err)
                return
            cmd = [executable, f"--cmd={enc_cmd}"]
            print(f"--cmd={enc_cmd}")
            return cmd
        except subprocess.TimeoutExpired as e:
            rc, out, err = -1, e.stdout or "", f"TIMEOUT after {self.env.timeout}s"
            return
        except Exception as e:
            rc, out, err = -1, "", str(e)
            return

    def run(
        self,
        args,
        name="command",
        isBuildSame: bool = True,
    ) -> dict[str, str] | None:
        cmd: List[str] | None = []

        if name != "sys_cmds":
            executable = self.build.working_dir + self.build.executable
            # cmd = [self.build.executable] + args
            # cmd = [executable] + args

            if not isBuildSame and not self.isBuildToggled:
                opposite_build = self.build.oppositeBuild
                self.build = self.builds[opposite_build]
                self.isBuildToggled = True
                executable = self.build.working_dir + self.build.executable
                # cmd = [executable] + args
            cmd.append(executable)
            cmd.extend(args)
            if self.build.isTestBed == 1 and self.env.port:
                cmd.append(f"--port={self.env.port}")

            if (
                self.env.private_key
                and not self.env.use_utf8_encryption
                and not any(re.match(r"--pvt-key", arg) for arg in args)
            ):
                cmd.append(f"--pvt-key={self.env.private_key}")

            if not self.env.use_utf8_encryption and not any(
                re.match(r"--password-file", arg) for arg in args
            ):
                cmd.append(f"--password-file={self.env.password}")

            if (
                self.env.device_id
                and int(self.env.dedup) == 1
                and name != "create_bucket"
                and not bool(self.env.syncDedup)
            ):
                cmd.append(f"--device-id={self.env.device_id}")

            cmd.append("--tls")

            print("\n" + "=" * 90)
            print(f"BUILD   : {self.build.name} / {self.build.release}")
            print(f"COMMAND : {command_line(cmd)}")
            print("=" * 90)

            if self.env.use_utf8_encryption:
                cmd = self.convert_to_utf8_enc_cmd(args, executable)

            start = time.perf_counter()
            if isinstance(cmd, List):
                try:
                    p = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.env.timeout,
                    )
                    rc, out, err = p.returncode, p.stdout, p.stderr
                except subprocess.TimeoutExpired as e:
                    rc, out, err = (
                        -1,
                        e.stdout or "",
                        f"TIMEOUT after {self.env.timeout}s",
                    )
                except Exception as e:
                    rc, out, err = -1, "", str(e)

                elapsed = time.perf_counter() - start
                (self.logs / f"{name}.stdout.txt").write_text(
                    out, encoding="utf-8", errors="replace"
                )
                (self.logs / f"{name}.stderr.txt").write_text(
                    err, encoding="utf-8", errors="replace"
                )

                if err:
                    print("\n--- STDERR ---")
                    print(err)
                print(f"\nReturn code: {rc} | Duration: {elapsed:.2f}s")

                # if not self.isRegression:
                # print(out)
                # input("Press ENTER to continue..")
                return {
                    "return_code": rc,
                    "stdout": out,
                    "stderr": err,
                    "duration": elapsed,
                }
        else:
            cmd.extend(args)

    def clear_screen(self):
        cmd = "cls" if os.name == "nt" else "clear"
        os.system(cmd)

    def auth_list(
        self,
        isSuiteRunning: bool = False,
        remotePath: str = "",
        isRegularFile: int = 1,
        name: str = "auth_list",
    ):
        path: str = "/"
        if not isSuiteRunning:
            path = input("Remote Path: ").strip()
        if isSuiteRunning and remotePath != "":
            path = remotePath
        a = ["--auth-list"]
        a.append("--xml-output")
        if not bool(isRegularFile):
            a.append("--split-backup")
        a.append(self.remote(path))
        return self.run(a, name)

    def device_list(self, isSuiteRunning: bool = False):
        return self.run(
            [
                "--list-device",
                "--xml-output",
                self.remote(),
            ],
            "device_list",
        )

    def list_trash(self, isSuiteRunning: bool = False):
        a = ["--auth-list", "--xml-output", "--trash"]
        trash_path = input("Trash Path: ").strip()
        if trash_path == "":
            trash_path = "/"
        a.append(self.remote(trash_path))
        return self.run(a, "list-trash")

    def empty_trash(self, isSuiteRunning: bool = False):
        file_list = (
            input(f"File List Path: [{self.env.fileListPath}]").strip()
            or self.env.fileListPath
        )
        a = ["--empty-trash", "--xml-output"]
        a.append(f"--files-from={file_list}")
        a.append(self.remote())
        return self.run(a, "empty-trash")

    def delete_items(
        self,
        fl: str = "",
        isSuiteRunning: bool = False,
        itemsToDelete: List[str] = [],
        v: str = "",
    ):
        file_list = fl
        if not isSuiteRunning:
            file_list = input(" File List Path: ").strip()
        # if isSuiteRunning:
        # fl: Path = self.env.workspace / "filelist.txt"
        # with fl.open("w", encoding="utf-8") as f:
        #    for item in itemsToDelete:
        #        f.writelines(item + "\n")
        # file_list = fl
        a = [
            "--delete-items",
            "--xml-output",
            f"--files-from={file_list}",
        ]
        a.append(self.remote())
        return self.run(a, f"delete-items-{v}")

    def client_version(self, isSuiteRunning: bool = False):
        return self.run(["--client-version"], "client_version")

    def server_version(self, isSuiteRunning: bool = False):
        return self.run(
            ["--server-version", self.remote()],
            "server_version",
        )

    def create_dir(self, isSuiteRunning: bool = False):
        dirPath = input("Enter Dir Path To Create: ").strip()
        a = [f"--create-dir={dirPath}"]
        a.append("--xml-output")
        a.append(self.remote())
        return self.run(a, "create-dir")

    def get_empty_folders(self, isSuiteRunning: bool = False):
        a = ["--get-empty-folders"]
        a.append("--xml-output")
        a.append(self.remote())
        return self.run(a, "get-empty-folders")

    def get_enc_psd(self, user="", psd=""):
        password: str
        username: str
        if psd == "":
            password = input("Enter the intended password: ")
        else:
            password = psd
        if user == "":
            username = input("Enter the username: ")
        else:
            username = user
        a = [f"--psd-enc={password}"]
        a.append(f"--user={username}")
        return self.run(a, "get-enc-psd")

    def quota(self, isSuiteRunning: bool = False):
        a = ["--get-quota", "--xml-output"]
        a.append(self.remote())
        return self.run(a, "quota")

    def version_info(
        self,
        isRegression=False,
        isSuiteRunning: bool = False,
        rp: Path = Path("/"),
        isRegularFile: int = 1,
    ):
        remotePath: str
        if isRegression:
            if os.name == "nt":
                remotePath = str(rp.as_posix())
                parts = remotePath.split(":")
                remotePath = "/" + "".join(parts)
            else:
                if self.source == "":
                    remotePath = input("Remote File Path (posix path): ").strip()
                else:
                    remotePath = str(rp)
        else:
            remotePath = input("Remote File Path (posix path): ").strip()
        a = ["--version-info"]
        if not bool(isRegularFile):
            a.append("--split-backup")
        a.append("--xml-output")
        a.append(self.remote(remotePath))
        name = "version_info"
        if not bool(isRegularFile):
            name = "version_info_split_backup"
        return self.run(a, name)

    def search(
        self,
        isSuiteRunning: bool = False,
        remotePath: str = "/",
        filesOnly: bool = False,
    ):
        keyword = ""

        if not isSuiteRunning:
            keyword = input("Search keyword: ").strip()

        a = ["--search", "--xml-output"]
        if filesOnly:
            a.append("--file")

        if keyword != "":
            a.append(f"--search-key={keyword}")

        a.append(self.remote(remotePath))

        return self.run(a, "search")

    def properties(self, isSuiteRunning: bool = False):
        path = input("Remote file/folder path: ").strip()
        a = ["--properties", "--xml-output"]
        a.append(self.remote(path))
        return self.run(a, "properties")

    def get_size(self, isSuiteRunning: bool = False):
        path = input("Remote folder path: ").strip()
        a = ["--get-size", "--xml-output"]
        a.append(self.remote(path))
        return self.run(a, "get_size")

    def items_status(self, isSuiteRunning: bool = False):
        fl = (
            input(f"FileList Path [{self.env.fileListPath}] : ").strip()
            or self.env.fileListPath
        )
        a = ["--items-status", "--xml-output", f"--files-from={fl}"]
        a.append(self.remote())
        return self.run(a, "items_status3")

    def file_status(self, isSuiteRunning: bool = False):
        fl = input("Remote File Path: ").strip()
        a = ["--file-status", "--xml-output"]
        a.append(self.remote(fl))
        return self.run(a, "file_status")

    def create_bucket(self, isSuiteRunning: bool = False):
        a = ["--create-bucket"]
        bucket_type: str = "D"
        nick_name: str = "TEST-BACKUP"
        location: str = "OFFICE"
        uid = str(uuid.uuid4()).split("-")
        uid = "".join(uid)
        os: str = "Test OS"
        if not isSuiteRunning:
            bucket_type = input("Bucket type[D=Desktop| R=Mobile]: ").strip()
            nick_name = input("Computer Name: ").strip()
            os = input("OS: ").strip()
            location = input("Location: ").strip()
            uid = input(f"Uid : [ {uid} ]").strip() or uid
        a.append(f"--bucket-type={bucket_type}")
        a.append(f"--nick-name={nick_name}")
        a.append(f"--uid={uid}")
        a.append(f"--os={os}")
        a.append(f"--location={location}")
        a.append(self.remote())
        return self.run(a, "create_bucket")

    def rename_item(self, isSuiteRunning: bool = False):
        a = ["--rename"]
        op = input("Old Path: ").strip()
        np = input("New Path: ").strip()
        a.append(f"--old-path={op}")
        a.append(f"--new-path={np}")
        a.append("--xml-output")
        a.append(self.remote())
        return self.run(a, "rename_item")

    def move_to_original(
        self,
        isSuiteRunning: bool = False,
        name: str = "move_to_original",
        filelist: str = "",
    ):
        fl = filelist
        if not isSuiteRunning:
            fl = (
                input(f"File List Path: [{self.env.fileListPath}]").strip()
                or self.env.fileListPath
            )
        a = ["--moveto-original", "--xml-output"]
        a.append(f"--files-from={fl}")
        a.append(self.remote())
        return self.run(a, name)

    def set_label(self, isSuiteRunning: bool = False):
        a = ["--xml-output"]
        fl = (
            input(
                f"File List path [add --f=/f.txt and --a=LABEL in src] [{self.env.fileListPath}]: "
            ).strip()
            or self.env.fileListPath
        )
        a.append(f"--files-from={fl}")
        a.append("--set-label")
        a.append(self.remote())
        return self.run(a, "set-label")

    def set_label_along_backup(self, isSuiteRunning: bool = False):
        a = ["--xml-output", f"--password-file={self.env.password}", "--type"]
        label = input("Label: ").strip()
        fl = (
            input(f"File List path [{self.env.fileListPath}] : ").strip()
            or self.env.fileListPath
        )
        a.append(f"--files-from={fl}")
        a.append("--add-progress")
        a.append(self.remote())
        a.append(f"--label-val={label}")
        return self.run(a, "set-label-along-backup")

    def search_label(self, isSuiteRunning: bool = False):
        a = ["--xml-output", "--search"]
        label = input("Label: ").strip()
        a.append(f"--label={label}")
        a.append(self.remote())
        return self.run(a, "search-label")

    def extended_list_search(self, isSuiteRunning: bool = False):
        a = ["--search", "--file-index64=0", "--xml-output"]

    def verify_account(
        self,
        user="",
        psd="",
        pk="",
        enc="",
        isSuiteRunning: bool = False,
    ):
        username: str = user
        password: str = psd
        pvt_key: str = pk
        enc_type: str = enc
        if not isSuiteRunning:
            if user == "":
                username = input(" Username: ").strip()
            if enc == "":
                print(" ENC Type: ")
                print(" 1. DEFAULT")
                print(" 2. PRIVATE")
                enc_type = input().strip()
                if enc_type == "1":
                    enc_type = "DEFAULT"
                elif enc_type == "2":
                    enc_type = "PRIVATE"
                else:
                    print("Invalid Input")
                    return
                if enc_type == "PRIVATE":
                    if pk == "":
                        pvt_key = input(" Pvt-key : ").strip()
                    else:
                        pvt_key = pk
            if psd == "":
                password = input(" Password: ").strip()
        a = [f"--default-key={enc_type}", f"--password-file={password}"]
        if enc_type == "PRIVATE" and pvt_key != "":
            a.append(f"--pvt-key={pvt_key}")
        a.append(f"{username}@{self.env.server}::home/")
        print("Verifying Account....")
        self.run(a, "verify-account")

    def create_account(self, isSuiteRunning: bool = False):
        try:
            a = []
            user: str = self.env.username
            password: str = self.env.password
            enc: str = "PRIVATE"
            enc_key: str = self.env.private_key
            enc_psd: str = ""

            if not isSuiteRunning:
                user = input("  Username: ").strip()
                password = input("  Password: ").strip()
                print("Encryption Type: ")
                print("1. Default")
                print("2. Private")
                enc_type: str = ""
                enc_type = input().strip()
                enc: str
                enc_key: str = ""
                if enc_type == "1":
                    enc = "DEFAULT"
                elif enc_type == "2":
                    enc = "PRIVATE"
                else:
                    print("Invalid Option. Select 1 or 2")
                    return
                if enc == "PRIVATE":
                    enc_key = input(" Enter Private Key: ").strip()
            a = self.get_enc_psd(user, password)
            enc_psd = a["stdout"].strip("\n").split("\n")[-1]
            print("enc_psd: ", enc_psd)
            directory = os.path.join(self.env.userRoot, user)
            print("Creating account..", directory)
            os.makedirs(directory, exist_ok=True)
            fl = os.path.join(directory, f"{user}.psecrets")
            fl_conf = os.path.join(directory, f"{user}.verconf")
            with open(fl_conf, "w", encoding="utf-8") as f:
                f.write("max versions=15")
            with open(fl, "w", encoding="utf-8") as f:
                f.write(f"{user}:{enc_psd}:Y:0")
            self.verify_account(
                user, password, enc_key, enc, isSuiteRunning=isSuiteRunning
            )

        except Exception as e:
            print("ERROR: ", e)
            return

    def config_account(self, isSuiteRunning: bool = False):
        user = input("Username: ").strip()
        print("Selection Encryption Type:")
        print("1. DEFAULT ")
        print("2. PRIVATE ")
        enc_key = input().strip()
        if enc_key == "1":
            enc_key = "DEFAULT"
        elif enc_key == "2":
            enc_key = "PRIVATE"
        else:
            return
        a = ["--config-account", f"--user={user}", f"--enc-type={enc_key}"]
        if enc_key == "PRIVATE":
            pvt_key = input("Private Key: ").strip()
            a.append(f"--pvt-key={pvt_key}")
        password = input("Password: ").strip()
        a.append(f"--password-file={password}")
        return self.run(a, "config-account")

    def verify_files(self, isSuiteRunning: bool = False):
        fl = (
            input(f"FileListPath : [{self.env.fileListPath}]").strip()
            or self.env.fileListPath
        )
        a = ["--Verify-files2", f"--files-from={fl}"]
        a.append("--xml-output")
        a.append(self.remote())
        return self.run(a, "verify_files2")

    def create_checksum(
        self,
        isSuiteRunning: bool = False,
        file_list: str = "",
        server_root: str = "",
        name: str = "create_checksum",
    ):
        fl = file_list
        root = server_root
        if not isSuiteRunning:
            fl = (
                input(f"Source file-list path [{self.env.fileListPath}]: ").strip()
                or self.env.fileListPath
            )
            if not bool(self.env.syncDedup):
                root = input("Server root / Disk ID: ").strip()

        a: list[str] = []
        a.append("--xml-output")
        a.append(f"--files-from={fl}")
        a.append("--create-chk")
        if not bool(self.env.syncDedup):
            a.append(f"--server-root={root}")
        a.append(self.remote())
        return self.run(a, name)

    def snapshot(self, isSuiteRunning: bool = False):
        path = input("Remote path (blank for root): ").strip()
        s = input("Snapshot start timestamp [0]: ").strip() or "0"
        e = input("Snapshot end timestamp: ").strip()
        a: list[str] = []
        a.append("--xml-output")
        a.append("--snap-shot")
        a.append(f"--snapshot-sdate={s}")
        a.append(f"--snapshot-edate={e}")
        a.append(self.remote(path))
        return self.run(a, "snapshot")

    def upload(
        self,
        file_list: Path,
        name,
        label="",
        temp_path="EVS_TEMP",
        backup_loc: str = "/",
        isSuiteRunning: bool = False,
        addl_args: list[str] = [],
    ):
        a: List[str] = []
        a.append("--type")
        backup_label = label
        if name == "manual_backup":
            temp = input("Temp Path: ").strip() or temp_path
            l = input("Set Label Val? [Y/N] : ").strip()
            if l.lower() == "y":
                backup_label = input(" Label: ").strip() or label
            if temp != "":
                a.append(f"--temp={temp_path}")
        a.append("--xml-output")
        if backup_label != "":
            a.append(f"--label-val={backup_label}")
        a.append("--add-progress")
        # a.append("--web-res")
        if len(addl_args) > 0:
            a.extend(addl_args)
        a.append(f"--files-from={file_list}")
        a.append("/")
        a.append(self.remote(backup_loc))
        return self.run(
            a,
            name,
        )

    def finish(self, isSuiteRunning: bool = False):
        passed = sum(r.status == "PASS" for r in self.results)
        failed = sum(r.status == "FAIL" for r in self.results)

        json_path = self.run_dir / "regression_results.json"
        csv_path = self.run_dir / "regression_results.csv"
        json_path.write_text(
            json.dumps([asdict(r) for r in self.results], indent=2), encoding="utf-8"
        )

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=list(asdict(self.results[0]).keys())
                if self.results
                else [
                    "test_id",
                    "description",
                    "status",
                    "expected",
                    "actual",
                    "build",
                    "details",
                ],
            )
            w.writeheader()
            for r in self.results:
                w.writerow(asdict(r))

        print("\n" + "=" * 90)
        print(f"REGRESSION COMPLETE: PASS={passed} FAIL={failed}")
        print(f"CSV: {csv_path}")
        print(f"JSON: {json_path}")
        print("=" * 90)
        return failed == 0

    def _create_bucket(self, isSuiteRunning) -> str:
        print("#" * 90)
        print("Creating Bucket")
        print("#" * 90)
        out = self.create_bucket(isSuiteRunning)
        print("Bucket Created : ", out["stdout"])
        print("-" * 90)
        pattern = r'device_id="([^"]*)"'
        uid = re.findall(pattern, out["stdout"])
        deviceID = ""
        if uid:
            deviceID = "5c0b" + uid[0].strip() + "4b5z"
            print("DeviceID: ", deviceID)
            return deviceID
        else:
            print("Unable to retrieve device ID ", out)
            return ""

    def _create_test_files(self, tst_fl: list[str]):
        try:
            fileListArr: list[Path] = []
            fileListPath = self.run_dir.joinpath("testBackup", "filelist.txt")
            for filename in tst_fl:
                file: Path = self.run_dir.joinpath("testBackup", filename)
                print("-" * 90)
                print(f"Creating Test File : {file}")
                print("-" * 90)
                create_test_file(file, 1)
                print("File Created: ", filename)
                print("-" * 90)
                fileListArr.append(file)
            print("-" * 90)
            print("Creating File List file: ", str(fileListPath))
            print("-" * 90)
            with fileListPath.open("w", encoding="utf-8") as f:
                for file_path in fileListArr:
                    f.write(str(file_path) + "\n")
            print("FileList File Created: ", str(fileListPath), ": Content Below ")
            for f in fileListArr:
                print(f)
            print("-" * 90)
            return True
        except:
            return False

    def _backup(
        self,
        fileListPath: Path,
        deviceID: str,
        testFilesPath: str,
        testFiles: list[str],
    ):
        print("#" * 90)
        print("TEST BACKUP INITIATED")
        print("#" * 90)
        self.env.device_id = deviceID
        return self.upload(fileListPath, "suite_backup")

    def _validate_test_backup(
        self,
        testFilesPath: str,
        testFiles: List[str],
    ):
        print("TEST Backup Complete. Validating Output :", testFilesPath)
        r = self.auth_list(True, remotePath=testFilesPath)
        pattern = r'fname="([^"]*)"'
        itemsFound = re.findall(pattern, r["stdout"])

        if r["return_code"] != 0:
            self.add(
                "SANITY-BACKUP",
                f"Full Backup - {len(testFiles)} files",
                "FAIL",
                "Return code 0",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.build.name}",
            )
            return False
        else:
            bk_files = set()
            for item in testFiles:
                p = self.run_dir.joinpath("testbackup", item.strip())
                bk_files.add(str(p).strip())

            for i, item in enumerate(itemsFound):
                data = str(item)
                # `!@#$%^&    *()_+=-|;:\'         "?,<   .>
                # `!@#$%^&amp;*()_+=-|;:&apos;&quot;?,&lt;.&gt;
                # `!@#$%^&    *()_+=-|;:'\     "         ?,<.>,
                data = data.replace("&amp;", "&")
                data = data.replace("&apos;", "'")
                data = data.replace("&quot;", '"')
                data = data.replace("&lt;", "<")
                data = data.replace("&gt;", ">")
                p = self.run_dir.joinpath("testbackup", data.strip())
                try:
                    bk_files.remove(str(p))
                except:
                    print("Key not found: ", p)
            self.add(
                "SANITY-BACKUP",
                f"Full Backup - {len(testFiles)} files",
                f"{'PASS' if len(bk_files) == 0 else 'FAIL'}",
                "Return code 0",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.build.name}",
            )
        # self.finish()

    def backup(self, isSuiteRunning: bool = False, filesToCreate: list[str] = []):
        if isSuiteRunning and len(filesToCreate) > 0:
            deviceID = self._create_bucket(isSuiteRunning)
            testFilesPath = str(self.run_dir.joinpath("testBackup"))
            fileListPath = self.run_dir.joinpath("testBackup", "filelist.txt")
            if not self._create_test_files(filesToCreate):
                return
            self._backup(fileListPath, deviceID, testFilesPath, filesToCreate)
            self._validate_test_backup(testFilesPath, filesToCreate)

        if not isSuiteRunning:
            path_list: str = (
                input(f"File List Path [{self.env.fileListPath}]").strip()
                or self.env.fileListPath
            )
            bl: str = input("Backup Location: ").strip()
            path: Path = Path(path_list)
            r = self.upload(path, "manual_backup", backup_loc=bl, label=self.label)

            if r["return_code"] != 0:
                self.add(
                    "Backup",
                    "Full Backup",
                    "FAIL",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )
                return False
            else:
                self.add(
                    "1LAC-BKP",
                    "FULL Backup",
                    "PASS",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )
            self.finish()

    def _validate_restore(self, dest: Path, uploadedFiles: List[Path]):
        restored: List[Path] = []
        for root, _, files in os.walk(str(dest)):
            for filename in files:
                file_path = Path(root).joinpath(filename)
                restored.append(file_path)
        if len(uploadedFiles) != len(restored):
            return False

        count = 0
        files_dict = {}

        for uf in uploadedFiles:
            if uf.name in files_dict:
                files_dict[uf.name].append(uf)
            else:
                files_dict[uf.name] = []
                files_dict[uf.name].append(uf)

        for rf in restored:
            if rf.name in files_dict:
                files_dict[rf.name].append(rf)
            else:
                files_dict[rf.name] = []
                files_dict[rf.name].append(rf)

        for v in files_dict.values():
            expected = v[0]
            actual = v[1]
            eh, ah = sha256(expected), sha256(actual)
            es, ass = expected.stat().st_size, actual.stat().st_size
            ok = eh == ah and es == ass
            if ok:
                count = count + 1

        self.add(
            "SANITY-RESTORE",
            "Verify restored",
            "PASS" if count == len(uploadedFiles) else "FAIL",
            "size={}, sha256={}",
            "size={}, sha256={}",
            f"Build: {self.build.name}",
        )
        self.finish()

    def restore(
        self,
        file_list: Path,
        destination: Path,
        name,
        isBuildSame: bool = True,
        isSuiteRunning: bool = False,
        filesToDownload: List[str] = [],
    ):
        a: List[str] = []
        poisx_path: str
        a.append("--xml-output")
        if os.name == "nt":
            poisx_path = Path(destination).as_posix()
            parts = poisx_path.split(":")
            poisx_path = "/" + "".join(parts) + "/"
            a.append("--add-progress")

        else:
            poisx_path = str(destination)

        a.append(f"--files-from={file_list}")
        a.append(self.remote())
        a.append(poisx_path)
        if isSuiteRunning and len(filesToDownload) > 0:
            self.run(a, name, isBuildSame)
            filesUploaded = []
            for filename in filesToDownload:
                p = self.run_dir.joinpath("testBackup", filename)
                filesUploaded.append(p)
            return self._validate_restore(destination, filesUploaded)
        return self.run(a, name, isBuildSame)

    def download(self, isSuiteRunning: bool = False):
        input_file_list = (
            input(f"File List Path [{self.env.fileListPath}]").strip()
            or self.env.fileListPath
        )
        input_restore_path = input("Restore Path: ").strip()
        restorePath = Path(input_restore_path)
        inputFilePath = Path(input_file_list)
        self.restore(inputFilePath, restorePath, "manual_restore")

    def link_backup(
        self,
        isSuiteRunning: bool = False,
        link_file_path: str = "/home/sandeep/filelist_link.txt",
        server_root: str = "",
    ):
        all_files = get_all_files_from_list(self.env.fileListPath)
        all_files_to_link = get_all_files_from_list(link_file_path)

        fl_with_all_file_paths = self.env.fileListPath + "_filePaths"
        fl_with_all_file_link_paths = link_file_path + "_fileLinkPaths"

        fl_with_file_chks = self.env.fileListPath + "_chk"
        fl_with_file_chks_link = link_file_path + "_fileLinkPaths_chk"

        with Path(fl_with_all_file_paths).open("w", encoding="utf-8") as f:
            for file in all_files:
                f.writelines(str(file) + "\n")

        with Path(fl_with_all_file_link_paths).open("w", encoding="utf-8") as f:
            for file in all_files_to_link:
                f.writelines(str(file) + "\n")

        if server_root == "":
            server_root = input("Server Root: ").strip()

        out = self.create_checksum(
            isSuiteRunning=True,
            file_list=fl_with_all_file_paths,
            server_root=server_root,
            name="create_chk_source",
        )

        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        with Path(fl_with_file_chks).open("w", encoding="utf-8") as f:
            chk_files = [line.strip() for line in details.splitlines() if line.strip()]
            for chk_file in chk_files:
                if chk_file != "DES keylen=8 ivlen=8 EVP_BytesToKey result=8":
                    f.writelines(chk_file + "\n")

        r = self.upload(
            isSuiteRunning=True,
            file_list=Path(fl_with_file_chks),
            name="backup_seekid",
            label="backup_seekid",
            addl_args=["--seekid"],
        )

        if r["return_code"] != 0:
            self.add(
                "BACKUP-SEEKID",
                "Full Backup",
                "FAIL",
                "Return code 0",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.build.name}",
            )
            return False
        else:
            self.add(
                "BACKUP-SEEKID",
                "FULL Backup",
                "PASS",
                "Return code 0",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.build.name}",
            )

        out2 = self.create_checksum(
            isSuiteRunning=True,
            file_list=fl_with_all_file_link_paths,
            server_root=server_root,
            name="create_chk_link_files",
        )

        # details2 = out2.get("stderr", "").strip()
        details2 = out2.get("stdout", "").strip()  # if details2 == "" else details2

        with Path(fl_with_file_chks_link).open("w", encoding="utf-8") as f:
            chk_files = [line.strip() for line in details2.splitlines() if line.strip()]
            for chk_file in chk_files:
                if chk_file != "DES keylen=8 ivlen=8 EVP_BytesToKey result=8":
                    f.writelines(chk_file + "\n")

        source_dict = create_checksum_dict(
            fromFile=False, output=details, file_list_path=Path(fl_with_all_file_paths)
        )

        link_dict = create_file_dict(
            fromFile=False,
            output=details2,
            file_list_path=Path(fl_with_all_file_link_paths),
        )

        print("Comparing LINK and SOURCE DICTS...")

        _dict = compare_dicts_and_format(
            link_dict, source_dict, repo_link_flag=0, version=3
        )
        formatted = _dict["link"]
        unlink = _dict["nolink"]
        print("linked: ", len(formatted))
        print("Unlinked files: ", len(unlink))
        print("Comparing LINK and SOURCE DICTS DONE...")
        print("Writing formatted link files...")

        link_backup_list = link_file_path + "_dedup_linked"

        with Path(link_backup_list).open("w", encoding="utf-8") as f:
            for path in formatted:
                f.writelines(path + "\n")

        print("Writing formatted link files DONE...")
        print("Kill the updater and press ENTER to create links")
        input("")
        self.create_link(link_file_path=Path(link_backup_list), isSuiteRunning=True)

        self.finish()

    def process_batch(self, idx: int, chunk: list[str], link_folder_path: Path):
        link_backup_list = str(link_folder_path.joinpath(f"chunk_{idx}"))

        with Path(link_backup_list).open("w", encoding="utf-8") as f:
            for file in chunk:
                f.writelines(file.strip() + "\n")

        args = [
            "--xml-output",
            "--create-link",
            f"--files-from={link_backup_list}",
            self.remote(),
        ]
        time.sleep(1)
        r = self.run(args=args, name=f"create_link_{idx}")

        with self.lock:
            if r["return_code"] != 0:
                self.add(
                    f"CREATE-LINK-{idx}",
                    "Create Link - Dedup Backup",
                    "FAIL",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )
                return False
            else:
                self.add(
                    f"CREATE-LINK-{idx}",
                    "Create Link - Dedup Backup",
                    "PASS",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )

    def create_link(
        self,
        link_file_path: Path = Path("/"),
        isSuiteRunning: bool = False,
        create_report: bool = False,
    ):
        link_file_paths: list[str] = []
        link_folder_path: Path
        fl = link_file_path

        if not isSuiteRunning:
            file = input("Link File Path: ").strip()
            fl = Path(file)

        with fl.open("r", encoding="utf-8") as f:
            link_file_paths = [line.strip("\n") for line in f if line.strip()]

        formatted_list = list(link_file_paths)

        try:
            link_folder_path = fl.parent.joinpath("link_file_list")
            if not link_folder_path.exists():
                link_folder_path.mkdir(exist_ok=True, parents=True)
        except Exception as e:
            print("Error: ", e)
            return

        chunks = [
            formatted_list[i : i + self.chunk_size]
            for i in range(0, len(formatted_list), self.chunk_size)
        ]

        self.workers = min(4, len(chunks))

        for wave_start in range(0, len(chunks), self.workers):
            wave_chunks = chunks[wave_start : wave_start + self.workers]
            print(
                f"\n--- Starting Wave: Batches {wave_start + 1} to {wave_start + len(wave_chunks)} ---"
            )
            success = True
            # run up to 4 concurrently
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(wave_chunks)
            ) as executor:
                future_to_idx = {}
                for offset, chunk in enumerate(wave_chunks):
                    idx = wave_start + offset + 1
                    future = executor.submit(
                        self.process_batch, idx, chunk, link_folder_path
                    )
                    future_to_idx[future] = idx

                # Wait for all 4 concurrent chunks to finish before moving on to next batch of 4 chunks
                for future in concurrent.futures.as_completed(future_to_idx):
                    res = future.result()
                    if res is False:
                        success = False

            if not success:
                print("A batch failed in this batch. Stopping process.")
                return False

            # sleep for few seconds before sending next set of chunk batches
            if wave_start + self.workers < len(chunks):
                print(
                    f"Wave complete. Cooling down for {self.cooldown_seconds} seconds before the next concurrent chunk batch..."
                )
                time.sleep(self.cooldown_seconds)

        if create_report or not isSuiteRunning:
            self.finish()

    def dedup_search_and_create_link(self, isSuiteRunning=False):
        args = ["--xml-output", "--search", "--dedup-search2", self.remote()]

        out = self.run(args, name="dedup_search2")
        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        dedup_checksum_dict = extract_repo_info(details)
        repo_link_flag = 1

        if not dedup_checksum_dict:
            print("Repo Links not found Trying with dedup-Search3 ")
            repo_link_flag = 0
            args = ["--xml-output", "--search", "--dedup-search3", self.remote()]
            out = self.run(args, name="dedup_search3")
            # details = out.get("stderr", "").strip()
            details = out.get("stdout", "").strip()  # if details == "" else details
            dedup_checksum_dict = extract_repo_info(details)

        all_files = get_all_files_from_list(self.env.fileListPath)

        fl_with_all_file_paths = self.env.fileListPath + "_filePaths"

        fl_with_file_chks = self.env.fileListPath + "_chk"

        with Path(fl_with_all_file_paths).open("w", encoding="utf-8") as f:
            for file in all_files:
                f.writelines(str(file) + "\n")

        server_root = ""
        if not bool(self.env.syncDedup):
            server_root = input("Server Root: ").strip()

        out = self.create_checksum(
            isSuiteRunning=True,
            file_list=fl_with_all_file_paths,
            server_root=server_root,
            name="create_chk_source",
        )

        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        with Path(fl_with_file_chks).open("w", encoding="utf-8") as f:
            chk_files = [
                line.strip()
                for line in details.splitlines()
                if line.strip() != "DES keylen=8 ivlen=8 EVP_BytesToKey result=8"
            ]
            for chk_file in chk_files:
                f.writelines(chk_file + "\n")

        source_checksum_dict = create_file_dict(
            fromFile=False, output=details, file_list_path=Path(fl_with_all_file_paths)
        )

        _dict = compare_dicts_and_format(
            source_checksum_dict, dedup_checksum_dict, repo_link_flag=repo_link_flag
        )

        formatted_paths = _dict["link"]
        no_link_files = _dict["nolink"]

        print("no_link_files: ", len(no_link_files))
        print("formmatted_paths: ", len(formatted_paths))

        fl_prepared_link_files = Path(
            str(self.env.fileListPath) + "prepared_link_files"
        )
        if len(formatted_paths) > 0:
            with fl_prepared_link_files.open("w", encoding="utf-8") as f:
                for file in formatted_paths:
                    f.writelines(file + "\n")

            self.create_link(
                link_file_path=fl_prepared_link_files,
                isSuiteRunning=True,
                create_report=True,
            )

        if len(no_link_files) > 0:
            fl_with_file_chks = self.env.fileListPath + "_remaining_chk_files_to_upload"
            with Path(fl_with_file_chks).open("w", encoding="utf-8") as f:
                for no_link_file in no_link_files:
                    f.writelines(no_link_file + "\n")

            r = self.upload(
                isSuiteRunning=True,
                file_list=Path(fl_with_file_chks),
                name="backup_seekid",
                label="backup_seekid",
                addl_args=["--seekid"],
            )

            if r["return_code"] != 0:
                self.add(
                    "BACKUP-SEEKID",
                    "Full Backup",
                    "FAIL",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )
                return False
            else:
                self.add(
                    "BACKUP-SEEKID",
                    "FULL Backup",
                    "PASS",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.build.name}",
                )

    def custom(self, isSuiteRunning: bool = False):
        print("Enter idevsutil arguments. Example: --get-quota")
        text = input("idevsutil > ").strip()
        if not text:
            return
        try:
            args = shlex.split(text, posix=False)
        except ValueError as e:
            print(f"Invalid command: {e}")
            return
        return self.run(args, f"custom_{time.strftime('%Y%m%d_%H%M%S')}")
