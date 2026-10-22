from __future__ import annotations

import csv
import json
import os
import re
import shutil
import time
import random

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..core.idevsutil import IdevsUtil
from ..db import FileTreeDatabase
from ..models import ChunkInfo, Result
from ..utils import (
    add_split_files_metadata,
    add_split_files_with_session,
    cbt_split_file,
    copy_tmp_dump,
    create_test_file,
    extract_split_received_metadata,
    get_all_files_from_list,
    get_splits_and_blocks_to_modify,
    info,
    insert_data,
    mutate_cbt_files,
    mutate_files,
    print_cbt_info_considered,
    remove_data,
    replace_data,
    replace_data_for_cbt,
    sha256,
    split_file,
    split_restore_create_config_xml_file,
    split_restore_create_split_restore_file,
    toPosix,
    toWin,
    PathMetadata,
    update_version_info,
)

SPLIT_SIZE = 1024 * 1024 * 512
BLOCK_SIZE = 1024 * 32
BLOCKS_IN_SPLIT = SPLIT_SIZE // BLOCK_SIZE
TOTAL_VERSIONS = 5


class Regression:
    def __init__(
        self,
        tool: IdevsUtil,
        root: Path,
        size_mb: int,
        db: FileTreeDatabase | None = None,
        filename="sandeep.txt",
        label="",
    ):
        self.tool = tool
        self.root = root
        self.size_mb = size_mb
        self.filename = filename
        self.label = label if label != "" else root.name

        self.source = root / "source"
        self.split_source = root / "split_source"
        self.cbt_source = root / "cbt_source"

        self.lists = root / "filelists"
        self.split_lists = root / "split_lists"
        self.cbt_lists = root / "cbt_lists"

        self.snapshots = root / "snapshots"
        self.split_snapshots = root / "split_snapshots"
        self.cbt_snapshots = root / "cbt_snapshots"

        self.restored = root / "restored"
        self.split_restored = root / "split_restored"
        self.cbt_restored = root / "cbt_restored"

        for d in (
            self.source.parent,
            self.lists,
            self.snapshots,
            self.restored,
            self.split_source.parent,
            self.split_lists,
            self.split_snapshots,
            self.split_restored,
            self.cbt_source,
            self.cbt_lists,
            self.cbt_restored,
            self.cbt_snapshots,
        ):
            d.mkdir(parents=True, exist_ok=True)

        self.results = []
        self.filesInfo = []
        self.files: list[Path] = []
        self.db = db
        self.updater_binary = Path(self.tool.build.working_dir).parent.joinpath(
            "UPDATER", "src", "idevsupdate"
        )
        self.split_bkp_path = "/home/sandeep/split_backup_files/"
        self.split_bkp_syntax_path = "/home/sandeep/split_filelist.txt"
        self.split_rs_path = "/home/sandeep/split_restore"

    def add(self, tid, desc, status, expected, actual, build, details=""):
        self.results.append(Result(tid, desc, status, expected, actual, build, details))
        print(f"[{status}] {tid} - {desc}")

    def add_file(self, name, checksum, size, mdt):
        self.filesInfo.append(
            ChunkInfo(name=name, checksum=checksum, mdt=mdt, size=size)
        )

    def _create_bucket(self, isSuiteRunning) -> dict[str, str] | str:
        print("#" * 90)
        print("Creating Bucket")
        print("#" * 90)
        out = self.tool.create_bucket(isSuiteRunning)
        print("Bucket Created : ", out["stdout"])
        print("-" * 90)
        pattern = r'device_id="([^"]*)"'
        pattern2 = r'server_root="([^"]*)"'
        uid = re.findall(pattern, out["stdout"])
        server_root = re.findall(pattern2, out["stdout"])
        deviceID = ""
        compID = ""
        if uid and server_root:
            deviceID = "5c0b" + uid[0].strip() + "4b5z"
            compID = server_root[0].strip()
            print("DeviceID: ", deviceID)
            print("COMPID: ", compID)
            return {"device_id": deviceID, "server_root": compID}
        else:
            print("Unable to retrieve device ID ", out)
            return ""

    def _validate_test_backup(
        self,
        testFilesPath: str,
        testFiles: list[str],
    ):
        print("TEST Backup Complete. Validating Output :", testFilesPath)
        r = self.tool.auth_list(True, remotePath=testFilesPath)
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

    def _backup(self, isSuiteRunning, filesToCreate: list[str] = []):
        if len(filesToCreate) > 0:
            deviceID = self._create_bucket(isSuiteRunning)
            if deviceID != "":
                self.tool.env.device_id = deviceID
            self._validate_test_backup(self.source, filesToCreate)
        else:
            return

    def _copy_snapshot(
        self, v: int, files: list[Path], files_source: Path, files_snapshot: Path
    ):
        try:
            for file in files:
                absPath = str(file.parent)
                # source = str(self.source)
                source = str(files_source)
                if os.name == "nt":
                    absPath = toPosix(file.parent)
                    # source = toPosix(self.source)
                    source = toPosix(files_source)

                rel = absPath.split(source)[1].lstrip("/")
                filePath: Path
                snapshot: Path
                if rel == "":
                    # snapshot = self.snapshots
                    snapshot = files_snapshot
                    versioned = file.name + f"_V{v:03d}"
                    # filePath = self.snapshots / versioned
                    filePath = files_snapshot / versioned

                else:
                    # snapshot = self.snapshots / rel
                    snapshot = files_snapshot / rel

                    versioned = file.name + f"_V{v:03d}"
                    filePath = snapshot / versioned

                if not Path.exists(snapshot):
                    snapshot.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, filePath)

        except Exception as e:
            print("_copy_snapshot: ", e)

    def backup(self, v, files: list[Path] = []):
        fl = self.lists / f"backup_V{v:03d}.txt"
        with open(str(fl), "w", encoding="utf-8") as f:
            for file in files:
                f.writelines(str(file) + "\n")

        r = self.tool.upload(
            fl,
            f"backup_V{v:03d}",
            label=self.label,
        )
        if r is None:
            return False
        if r["return_code"] != 0:
            self.add(
                f"{'INC' if v > 1 else 'FULL'}-BKP-{v:03d}",
                f"{'Incremental' if v > 1 else 'FULL'} - backup V{v}",
                "FAIL",
                "Return code 0",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.tool.build.name}",
            )
            return False

        self._copy_snapshot(
            v=v, files=files, files_source=self.source, files_snapshot=self.snapshots
        )

        self.add(
            f"{'INC' if v > 1 else 'FULL'}-BKP-{v:03d}",
            f"{'Incremental' if v > 1 else 'FULL'} - backup V{v}",
            "PASS",
            "Backup succeeded",
            f"Return code 0; {r['duration']:.2f}s",
            f"Build: {self.tool.build.name}",
        )
        return r

    def validate_restore(
        self,
        dest: Path,
        uploadedFiles: list[Path],
        v,
        isRegularFile: int = 1,
        original_files_dict: dict[str, Any] = {},
        isCBT: bool = False,
    ):
        restored: list[Path] = []

        for root, _, files in os.walk(str(dest)):
            for filename in files:
                file_path = Path(root).joinpath(filename)
                if os.name == "nt":
                    file_path = toPosix(file_path)
                if isinstance(file_path, str):
                    file_path = Path(file_path)
                if not bool(isRegularFile):
                    file = Path(file_path)
                    ext = file.suffix
                    if (
                        file.is_file()
                        and not str(file).endswith("_config.xml")
                        and ext != ""
                        and len(ext.split("_")) < 2
                    ):
                        file_path = Path(file)
                        restored.append(file_path)
                else:
                    restored.append(file_path)

        count = 0
        files_dict = {}
        stats = {}
        meta = PathMetadata()
        for uf in uploadedFiles:
            p = str(uf).split(f"_V{v:03d}")[0]
            parent = uf.parent

            if os.name == "nt":
                parent = Path(meta.fix_windows_path(path=str(parent)))

            relPath = str(parent.relative_to(self.root))
            parts = relPath.split("/")[1:]
            if os.name == "nt":
                parts = relPath.split("\\")[1:]
            temp_path = ""

            if bool(isRegularFile):
                temp_path = "source" + "/" + "/".join(parts)
                if os.name == "nt":
                    temp_path = "source" + "\\" + "\\".join(parts)
            elif isCBT:
                temp_path = "cbt_source" + "/" + "/".join(parts)
                if os.name == "nt":
                    temp_path = "cbt_source" + "\\" + "\\".join(parts)
            else:
                temp_path = "split_source" + "/" + "/".join(parts)
                if os.name == "nt":
                    temp_path = "split_source" + "\\" + "\\".join(parts)

            path = Path(str(self.root)).joinpath(temp_path, uf.name)
            file = uf
            if os.name == "nt":
                file = toWin(str(file))
                p = toPosix(Path(p))
                parts = Path(p).as_posix().split("/")
                p = "/".join(parts[1:])

            stat = {
                "mdt": file.stat().st_mtime,
                "size": file.stat().st_size,
                "ver": v,
            }
            stats[p] = stat
            if str(path) in files_dict:
                files_dict[str(path)].append(uf)
            else:
                files_dict[str(path)] = []
                files_dict[str(path)].append(uf)

        for rf in restored:
            parent = rf.parent
            if os.name == "nt":
                parent = Path(meta.fix_windows_path(path=str(parent)))

            relPath = parent.relative_to(dest)
            path = "/" + str(relPath) + "/" + rf.name + f"_V{v:03d}"
            if os.name == "nt":
                relPath = Path(meta.fix_windows_path("\\" + str(relPath)))
                path = relPath.joinpath(rf.name + f"_V{v:03d}")
                # path = "\\" + str(relPath) + "\\" + rf.name + f"_V{v:03d}"

            # path = rf.parent / (rf.name + f"_V{v:03d}")

            key = str(path)
            if key in files_dict:
                files_dict[key].append(rf)
            else:
                files_dict[key] = []
                files_dict[key].append(rf)

        for val in files_dict.values():
            expected = val[0]
            actual = val[1]

            if os.name == "nt":
                expected = toWin(str(expected))
                actual = toWin(str(actual))

            eh, ah = sha256(expected), sha256(actual)
            es, ass = expected.stat().st_size, actual.stat().st_size

            ok = eh == ah and es == ass

            if ok:
                count = count + 1

        text = "INC" if int(v) > 1 else "FULL"

        if not bool(isRegularFile):
            text = "INC-SPLIT" if int(v) > 1 else "FULL-SPLIT"
        if isCBT:
            text = "INC-CBT" if int(v) > 1 else "FULL-CBT"

        self.add(
            f"{text}-Restore-{v:03d}",
            "Restore Integrity Verification",
            "PASS" if count == len(uploadedFiles) else "FAIL",
            "Uploaded File Matched Actual",
            "Downloaded File Version Matched Actual",
            f"Build: {self.tool.build.name}",
        )

        return stats

    def restore_version(self, v, files: list[Path], isBuildSame=True):
        # <source path>_IBVER001, <source path>_IBVER002, ...
        fl = self.lists / f"restore_V{v:03d}.txt"
        with open(str(fl), "w", encoding="utf-8") as f:
            for file in files:
                versioned = f"{str(file)}_IBVER{v:03d}"
                f.write(versioned + "\n")

        dest = self.restored / f"V{v:03d}"
        dest.mkdir(parents=True, exist_ok=True)
        self.tool.restore(fl, dest, f"restore_V{v:03d}", isBuildSame)
        snapFiles: list[Path] = []

        for file in files:
            source: str = ""
            absPath: str = ""
            relPath: str = ""
            if os.name == "nt":
                source = toPosix(self.source)
                absPath = toPosix(file.parent)
            else:
                source = str(self.source)
                absPath = str(file.parent)
            relPath = absPath.split(source)[1].lstrip("/")
            versioned = ""
            if relPath == "":
                versioned = file.name + f"_V{v:03d}"
            else:
                versioned = relPath + "/" + file.name + f"_V{v:03d}"
            snap = self.snapshots / versioned
            if os.name == "nt":
                snap = toPosix(Path(snap))
            if isinstance(snap, str):
                snap = Path(snap)
            snapFiles.append(snap)

        return self.validate_restore(dest, snapFiles, v)

    def validate_versions(
        self,
        out: str,
        remotepath: str,
        uploadedStats,
        isRegularFile: int = 1,
        isCBT: bool = False,
    ):
        # <item mod_time="2026/09/11 13:02:55" mdt_long="1789111975"  size="1048576" ver="1"/>
        mdt_pattern = r'mdt_long="([^"]*)"'
        size_pattern = r'size="([^"]*)"'
        ver_pattern = r'ver="([^"]*)"'
        stats = {}

        mdts = re.findall(mdt_pattern, out)
        sizes = re.findall(size_pattern, out)
        vers = re.findall(ver_pattern, out)
        if len(sizes) == len(mdts) and len(vers) == len(sizes):
            for m, s, v in zip(mdts, sizes, vers):
                stats[v] = {"mdt": m, "size": s, "ver": v}

        count = 0

        for key, value in stats.items():
            rp = str(Path(remotepath).parent)
            _src = self.source

            if isCBT:
                _src = self.cbt_source

            if not bool(isRegularFile) and not isCBT:
                _src = self.split_source

            src = str(_src)

            if os.name == "nt":
                rp = toPosix(Path(rp))
                src = toPosix(Path(src))

            rel = rp.split(src)[1].lstrip("/")
            actual_source = ""

            if rel == "":
                relFilePath = Path(remotepath).name
                replace = "snapshots"

                if not bool(isRegularFile) and not isCBT:
                    replace = "split_snapshots"
                if isCBT:
                    replace = "cbt_snapshots"

                actual_source = self.root.joinpath(replace, relFilePath)
                if os.name == "nt":
                    actual_source = toPosix(actual_source)
            else:
                name = Path(remotepath).name
                replace = "snapshots"

                if not bool(isRegularFile) and not isCBT:
                    replace = "split_snapshots"

                if isCBT:
                    replace = "cbt_snapshots"

                actual_source = self.root.joinpath(replace, rel, name)
                if os.name == "nt":
                    actual_source = toPosix(actual_source)

            if str(actual_source).strip() in uploadedStats:
                u_item_s = uploadedStats[str(actual_source)][int(key) - 1]
                d_item_s = value
                if (
                    int(u_item_s["size"]) == int(d_item_s["size"])
                    and int(u_item_s["mdt"]) == int(d_item_s["mdt"])
                    and int(u_item_s["ver"]) == int(d_item_s["ver"])
                ):
                    count = count + 1

        return count == TOTAL_VERSIONS - 1

    def _extract_fname(self, pattern, stdout: str) -> list[str]:
        # pattern = r'fname="([^"]*)"'
        itemsFound = re.findall(pattern, stdout)
        paths = []
        paths_set = set()
        for item in itemsFound:
            data = str(item)
            # `!@#$%^&    *()_+=-|;:\'         "?,<   .>
            # `!@#$%^&amp;*()_+=-|;:&apos;&quot;?,&lt;.&gt;
            # `!@#$%^&    *()_+=-|;:'\     "         ?,<.>,
            data = data.replace("&amp;", "&")
            data = data.replace("&apos;", "'")
            data = data.replace("&quot;", '"')
            data = data.replace("&lt;", "<")
            data = data.replace("&gt;", ">")
            if data.strip() not in paths_set:
                paths_set.add(data.strip())
                paths.append(data.strip())
        return paths

    def upload_get_ordered_file_paths(self, v, files) -> list[Path]:
        out = self.backup(v, files)

        if out is None:
            return self.finish()

        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        pattern = r'fname="([^"]*)"'
        uploadedFilePaths = self._extract_fname(pattern=pattern, stdout=details)
        return [Path("/").joinpath(path) for path in uploadedFilePaths]

    def get_ordered_split_file_paths(self, output: str, v: int) -> list[Path]:
        pattern = r'fname="([^"]*)"'
        uploadedFilePaths = self._extract_fname(pattern=pattern, stdout=output)
        paths = set()
        ordered_path_lists = []
        for path in uploadedFilePaths:
            p = Path("/").joinpath(path[:-5])
            if str(p) not in paths:
                paths.add(str(p))
                ordered_path_lists.append(p)

        return ordered_path_lists

    def log_to_file(self, message: str):
        with open("execution_debug.log", "a") as f:
            f.write(message + "\n")

    def update_versioned_files_in_db(
        self, v, meta: PathMetadata, file, deviceID, compID, is_Regular_file: int = 1
    ):
        file_path = meta._to_pure_posix(file)

        if os.name == "nt":
            file = meta.fix_windows_path(file)

        metadata = meta.fetch_hierarchy_properties(str(file))
        try:
            self.log_to_file(f"file_path: {file_path}")
            self.log_to_file(f"file     : {file}")
            self.log_to_file("=" * 90)
            self.log_to_file(f"metadata : {metadata}")
            self.log_to_file("=" * 90)

        except Exception as e:
            print("e -->< ", e)

        if v == 1:
            metadata[file_path]["checksum"] = sha256(Path(file))
            metadata[file_path]["vernum"] = 1
            self.db.insert_path(
                file_path,
                pathProperties=metadata,
                device_id=deviceID,
                computer_id=compID,
                isRegularFile=is_Regular_file,
            )
        else:
            # record = self.db.get_by_path(file_path)
            record = self.db.get_by_path_new(
                file_path,
                isRegularFile=is_Regular_file,
                computer_id=compID,
                device_id=deviceID,
            )
            if record is not None:
                data = update_version_info(
                    file=Path(file),
                    record=record,
                    file_path=file_path,
                    metadata=metadata,
                    v=v,
                    isRegularFile=is_Regular_file,
                )
                if self.db is not None:
                    self.db.update(data["uid"], data["record"])
                    self.db.insert_version_record(data["version"])

    def cbt_backup(self, v: int, files: list[Path], cbt_info):
        all_files: list[Path] = files

        if len(all_files) == 0:
            all_files = get_all_files_from_list(self.tool.env.fileListPath)

        origin_files_to_split: dict[str, Any] = {}

        fl = self.cbt_lists / f"cbt_{v:03d}_sync_check.txt"
        split_count = 0

        for i, file in enumerate(all_files):
            mode = "a" if i > 0 else "w"
            stats = cbt_split_file(
                file_path=Path(file), fl_path=str(fl), mode=mode, split_size=SPLIT_SIZE
            )
            if stats is not None:
                path = stats["path"]
                origin_files_to_split[path] = stats
                split_count = len(stats["splits_info"])
                for f in stats["splits_info"]:
                    name = f["name"]
                    size = f["size"]
                    checksum = f["checksum"]
                    mdt = f["mdt"]
                    self.add_file(name=name, checksum=checksum, size=size, mdt=mdt)

        file_csv = self.cbt_source / f"cbt_split_info_{v:03d}.json"

        self.write_file_info(file_csv)

        session = self.sync_check(str(fl), v=v, isCBT=True)

        fl = self.cbt_lists / f"cbt_{v:03d}_split_backup.txt"

        ordered_file_paths: list[Path] = []

        if session is not None:
            ordered_file_paths = self._split_backup(
                session=session,
                origin_files_to_split=origin_files_to_split,
                fl=fl,
                v=v,
                isCBT=True,
                cbt_info=cbt_info,
            )

            fl = self.cbt_lists / f"cbt_{v:03d}_send_meta.txt"

            self._send_split_metadata(
                original_files_to_split=origin_files_to_split,
                sessionID=session,
                split_count=split_count,
                fl=fl,
                v=v,
                isCBT=True,
            )
            self._copy_snapshot(
                v=v,
                files=files,
                files_source=self.cbt_source,
                files_snapshot=self.cbt_snapshots,
            )
        return {
            "origin_files_to_split": origin_files_to_split,
            "ordered_file_paths": ordered_file_paths,
        }

    def run(
        self,
        files: list[Path],
        split_files: list[Path],
        cbt_files: list[Path],
        link_files: list[Path],
    ):
        print("\n" + "#" * 90)
        print("BACKUP AND RESTORE REGRESSION")
        print("#" * 90)

        self.files = files
        compID = self.tool.env.server_root
        deviceID = self.tool.env.device_id
        print("compID: ", compID)
        print("deviceID: ", deviceID)

        if int(self.tool.env.dedup) == 1 and not self.tool.env.device_id:
            data = self._create_bucket(True)
            deviceID = data.get("device_id", "")
            compID = data.get("server_root", "")
            if deviceID != "":
                self.tool.env.device_id = deviceID

        meta = PathMetadata()

        # 1. CBT Backup
        # origin_files_to_split = {}
        #
        # for v in range(1, TOTAL_VERSIONS + 1):
        #     cbt_info = mutate_cbt_files(v=v, files=cbt_files, size=1024 * 1024 * 1)
        #     out = self.cbt_backup(v, files=cbt_files, cbt_info=cbt_info)
        #
        #     origin_files_to_split = out["origin_files_to_split"]
        #
        #     ordered_file_paths = out["ordered_file_paths"]
        #
        #     for file in ordered_file_paths:
        #         self.update_versioned_files_in_db(
        #             v, meta, file, deviceID, compID, is_Regular_file=0
        #         )
        #
        # # 2. CBT - Restore and validate restores
        # stats = {}
        #
        # for v in range(1, TOTAL_VERSIONS + 1):
        #     batch_stat = self.split_restore(
        #         original_files=origin_files_to_split, v=v, split_count=2, isCBT=True
        #     )
        #     for k, v in batch_stat.items():
        #         if k in stats:
        #             stats[k].append(v)
        #         else:
        #             stats[k] = [v]
        #
        # # 2 a) verify cbt file versions
        #
        # for path in origin_files_to_split.keys():
        #     file = Path(path)
        #     r = self.tool.version_info(True, rp=file, isRegularFile=0)
        #     if r is None:
        #         return
        #     isVerified = self.validate_versions(
        #         out=r["stdout"],
        #         remotepath=str(file),
        #         uploadedStats=stats,
        #         isRegularFile=0,
        #         isCBT=True,
        #     )
        #     self.add(
        #         "CBT-VERSIONS",
        #         "Retrieve & Verify version history of CBT files",
        #         "PASS" if isVerified else "FAIL",
        #         f"Version-info of {file.name} succeeds",
        #         str(r["return_code"]),
        #         r["stderr"],
        #         f"Build: {self.tool.build.name}",
        #     )

        # 3. Split Backup
        origin_files_to_split = {}

        for v in range(1, TOTAL_VERSIONS + 1):
            mutate_files(v=v, files=split_files, size=1234)
            out = self.split_backup(v=v, files=split_files, split_count=7)
            origin_files_to_split = out["origin_files_to_split"]
            ordered_file_paths = out["ordered_file_paths"]
            for file in ordered_file_paths:
                self.update_versioned_files_in_db(
                    v, meta, file, deviceID, compID, is_Regular_file=0
                )
            time.sleep(2)

        # 4. Validate Split & CBT backups
        self.validate_backup(isRegularFile=0, module="AUTH-SPLIT/CBT-FILES")

        # 5. Split Restore and validate restores
        stats = {}

        for v in range(1, TOTAL_VERSIONS + 1):
            batch_stat = self.split_restore(
                original_files=origin_files_to_split, v=v, split_count=7
            )
            for k, v in batch_stat.items():
                if k in stats:
                    stats[k].append(v)
                else:
                    stats[k] = [v]
            time.sleep(2)

        # 6. split version info validation
        for path in origin_files_to_split.keys():
            file = Path(path)
            r = self.tool.version_info(True, rp=file, isRegularFile=0)
            if r is None:
                return
            isVerified = self.validate_versions(
                out=r["stdout"],
                remotepath=str(file),
                uploadedStats=stats,
                isRegularFile=0,
            )
            self.add(
                "VERSIONS-SPLIT/CBT-BACKUP",
                "Retrieve & Verify version history",
                "PASS" if isVerified else "FAIL",
                f"Version-info of {file.name} succeeds",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.tool.build.name}",
            )

        # 7. Regular file backup
        for v in range(1, TOTAL_VERSIONS + 1):
            mutate_files(v=v, files=files, size=self.size_mb)

            # self.tool.run(["killall", "idevsupdate"], name="sys_cmds")

            uploadOrderedFiles = self.upload_get_ordered_file_paths(v, files)
            # copy_tmp_dump(
            #     self.root, Path(self.tool.env.userRoot), self.tool.env.username
            # )
            #
            for file in uploadOrderedFiles:
                self.update_versioned_files_in_db(v, meta, file, deviceID, compID)
            # self.tool.run([self.updater_binary, "--daemon"], name="sys_cmds")

            time.sleep(2)

        # 8. regular file backup validation
        self.validate_backup()

        print("-" * 90)
        print("\n Restore Build Selection")
        print("-" * 90)
        print("1. Same")
        print("2. Opposite")
        # selection = input(">").strip()
        isBuildSame: bool = True
        # if selection == "2":
        # isBuildSame = False
        # else:
        # isBuildSame = True

        # 9. Regular file restore & validation
        stats = {}

        for v in range(1, TOTAL_VERSIONS + 1):
            batch_stat = self.restore_version(v, self.files, isBuildSame)
            for k, v in batch_stat.items():
                if k in stats:
                    stats[k].append(v)
                else:
                    stats[k] = [v]

        # 10. regular file version info validation

        for file in files:
            r = self.tool.version_info(True, rp=file)
            if r is None:
                return
            isVerified = self.validate_versions(r["stdout"], str(file), stats)
            self.add(
                "SANITY-VERSIONS",
                "Retrieve & Verify version history",
                "PASS" if isVerified else "FAIL",
                f"Version-info of {file.name} succeeds",
                str(r["return_code"]),
                r["stderr"],
                f"Build: {self.tool.build.name}",
            )

        self.tool.toogleBuild(False)
        if not isBuildSame:
            self.tool.resetBuildToOriginal()

        self.tool.resetRegression()
        return self.finish()

    def sync_check(self, fl: str, v: int, isCBT: bool = False):
        # =======================
        # Command for sync-check:
        # =====================
        #  ./idevsutil --password-file=1234 --port=900 test3@localhost::home/
        #  --device-id=5c0bD015900616870005783114b5z --files-from=/opt/file.txt
        #  --sync-check --no-stat --pvt-key=1234
        #
        # File input:
        # Syntax: Filename:MDT$size$split_count
        # Example: /home/ARP/log.txt:1524789612$1073765830$3
        args = [
            # f"--files-from={self.split_bkp_syntax_path}",
            f"--files-from={fl}",
            "--xml-output",
            "--sync-check",
            "--no-stat",
            self.tool.remote(),
        ]

        r = self.tool.run(args, f"sync_check_{v:03d}")

        result = "FAIL"
        sessionID: str | None = None

        if r is not None:
            out = r["stdout"]
            pattern = r'fname="([^"]*)"'
            fnames = self._extract_fname(pattern, out)
            pattern = r'status="([^"]*)"'
            statuses = self._extract_fname(pattern, out)
            pattern = r'sessionID="([^"]*)"'
            sessions = self._extract_fname(pattern, out)
            session = list(set(sessions))
            sessionID = session[0]
            file_count = len(fnames)
            for fname, status in zip(fnames, statuses):
                if status == "FAILURE":
                    file_count -= 1

            result = "PASS" if file_count == 0 else "FAIL"

        tc_name = f"SPLIT-BKP-SYNC-CHK-{v:03d}"
        if isCBT:
            tc_name = f"CBT-BKP-SYNC-CHK-{v:03d}"

        desc = "Split Backup Sync Check"
        if isCBT:
            desc = "CBT Backup Sync Check"

        self.add(
            tc_name,
            desc,
            f"{result}",
            "Sync Check",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )

        return sessionID

    def prepare_cbt_and_match(self, cbt_info, v: int, session, fl: Path):
        matched_splits = []
        cbt = {}
        cbt_splits = []
        for file_path, value in cbt_info.items():
            if len(value["matched"]) > 0:
                matched_splits.extend(value["matched"])
            for split_fname, blocks in value["cbt"].items():
                cbt_splits.append(split_fname)
                for block in blocks:
                    name = Path(split_fname).name
                    new_name = "cbt_" + name
                    new_cbt_split_path = Path(split_fname).parent.joinpath(new_name)
                    key = str(new_cbt_split_path)
                    if key not in cbt:
                        cbt[key] = [block]
                    else:
                        cbt[key].append(block)

        for cbt_path, blocks in cbt.items():
            with Path(cbt_path).open("w", encoding="utf-8") as f:
                for block in blocks:
                    f.writelines(str(block) + "\n")

        for match in matched_splits:
            split_fname = Path(match)
            with split_fname.open("wb") as f:
                f.write(b"")

        with fl.open("w", encoding="utf-8") as f:
            for match in matched_splits:
                f.writelines(match + ":" + session + "\n")

        return cbt_splits

    def send_cbt_match(self, fl: Path, v: int):
        args = [
            "--xml-output",
            "--add-progress",
            "--match-split",
            "--split-backup2",
            f"--files-from={fl}",
            "/",
            self.tool.remote(),
            f"--split-size={SPLIT_SIZE}",
        ]
        r = self.tool.run(args, f"cbt_send_match_{v:03d}")
        result = "FAIL"

        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"

        self.add(
            f"CBT-MATCH-BACKUP-{v:03d}",
            "Sending CBT Match splits",
            f"{result}",
            "Match Split",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )

    def _split_backup(
        self,
        session: str,
        origin_files_to_split: dict[str, Any],
        fl: Path,
        v: int,
        isCBT: bool = False,
        cbt_info={},
    ):
        # =======================
        # Command for split backup:
        # =====================
        #  ./idevsutil --password-file=1234 --port=900 / test3@localhost::home/
        #  --device-id=5c0bD015900593180007972994b5z
        #  --files-from=/opt/file1.txt --split-backup --pvt-key=1234
        # Syntax: Split file name:session_id
        # Example: /home/ARP/log.txt_0000:1590059456666234
        # File input[Session Id will be obtained from sync check command]:

        cbt_splits = []

        if v > 1 and isCBT:
            fl_match = self.cbt_lists / f"cbt_{v:03d}_match.txt"
            cbt_splits = self.prepare_cbt_and_match(
                cbt_info=cbt_info,
                v=v,
                session=session,
                fl=fl_match,
            )
            self.send_cbt_match(fl=fl_match, v=v)

        add_split_files_with_session(
            split_bkp_set_path=self.split_source if not isCBT else self.cbt_source,
            sessionID=session,
            fl=fl,
            mode="w",
            original_files_to_split=origin_files_to_split,
            isCBT=isCBT,
            cbt_splits=cbt_splits,
            v=v,
        )
        args = [
            "--xml-output",
            f"--files-from={fl}",
            "/",
            "--split-backup" if not isCBT else "--split-backup2",
            self.tool.remote(),
        ]
        if isCBT:
            args.append(f"--split-size={SPLIT_SIZE}")
        if isCBT and v > 1:
            args.append("--cbt")

        name = f"split_backup_{v:03d}"
        if isCBT:
            name = f"cbt_split_backup_{v:03d}"

        r = self.tool.run(args, name)
        result = "FAIL"
        ordered_file_paths = []

        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"
            ordered_file_paths = self.get_ordered_split_file_paths(
                output=r["stdout"], v=v
            )

        tc_name = f"SPLIT-SPLITBACKUP-{v:03d}"
        if isCBT:
            tc_name = f"CBT-SPLIT-BACKUP2-{v:03d}"

        desc = "CBT Backup After Sync Check"
        if not isCBT:
            desc = "Split Backup After Sync Check"

        self.add(
            tc_name,
            desc,
            f"{result}",
            "Split Backup",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )

        return ordered_file_paths

    def _send_split_metadata(
        self,
        original_files_to_split: dict[str, Any],
        sessionID: str,
        split_count: int,
        fl: Path,
        v: int,
        isCBT: bool = False,
    ):
        # =======================
        # Command for Metadata-send:
        # =======================
        # ./idevsutil --password-file=1234 --port=900
        # --xml-output / test5@localhost::home/ --device-id=5c0bD015900480780007683194b5z
        # --files-from=/opt/file2.txt --metadata-send --pvt-key=1234 --type
        #
        # File input[Pass same session id which is used in split backup]:
        # Syntax: Config.xml file name:MDT$size$split_count$session_id
        # Example: /home/ARP/log.txt_config.xml:1524789612$1073765760$2$1590052109775811
        #

        # --xml-output / test5@localhost::home/ --device-id=5c0bD015900480780007683194b5z
        # --files-from=/opt/file2.txt --metadata-send --pvt-key=1234 --type
        add_split_files_metadata(
            # split_metadata_fl=Path(self.split_bkp_syntax_path),
            split_metadata_fl=fl,
            original_split_files=original_files_to_split,
            split_count=split_count,
            sessionID=sessionID,
        )
        args = [
            "--xml-output",
            "/",
            # f"--files-from={self.split_bkp_syntax_path}",
            f"--files-from={fl}",
            "--metadata-send",
            self.tool.remote(),
        ]

        r = self.tool.run(args, f"split_send_metadata_{v:03d}")
        result = "FAIL"

        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"

        tc_name = f"SPLIT-BKP-SEND-META-{v:03d}"
        if isCBT:
            tc_name = f"CBT-BKP-SEND-META-{v:03d}"

        desc = "Split Backup Send Metadata"

        if isCBT:
            desc = "CBT Backup Send Metadata"

        self.add(
            tc_name,
            desc,
            f"{result}",
            "Send Metadata",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )

        return result == "PASS"

    def split_receive_metadata(self, fl: Path, dst: str, v: int):
        # Metadata-receive:
        # ==============
        # Input: /IDDriveImage/random_1gb_file1.bin_config.xml_IBVER001
        # Ex:
        # ./idevsutil --xml-output --add-progress --files-from=/home/opt/file.txt
        # --device-id=5c0bD017718384600007254654b5z --password-file=1234 --port=900 test1@localhost::home/
        # /home/IDdr/
        # --metadata-receive
        args = [
            "--xml-output",
            "--add-progress",
            f"--files-from={fl}",
            self.tool.remote(),
            dst,
            "--metadata-receive",
        ]
        r = self.tool.run(args, "receive_metadata")
        result = "FAIL"
        metadata = {}
        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"
            output = r["stdout"]
            metadata = extract_split_received_metadata(output)

        self.add(
            f"SPLIT-RESTORE-RECEIVE-META-{v:03d}",
            "Split Restore Receive Metadata",
            f"{result}",
            "Receive Metadata",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )
        return metadata

    def _split_restore(
        self,
        split_meta: dict[str, Any],
        fl: Path,
        dst: str = "/",
        v: int = 1,
    ):
        # Split-res
        # ./idevsutil --xml-output --add-progress --files-from=/home/opt/file.txt  --device-id=5c0bD017718384600007254654b5z --password-file=1234 --port=900 test1@localhost::home/ /home/IDdr/ --split-res
        # input should be split file with version no
        # IBVER001
        # input /home/opt/sandeep/split_backup_files/file_00001.bin_00000_IBVER001
        split_restore_create_split_restore_file(
            fl=fl,
            split_meta=split_meta,
            v=v,
        )
        args = [
            "--xml-output",
            "--add-progress",
            f"--files-from={fl}",
            self.tool.remote(),
            dst,
            "--split-res",
        ]
        r = self.tool.run(args, f"split_restore_{v:03d}")
        result = "FAIL"
        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"

        self.add(
            f"SPLIT-RESTORE-{v:03d}",
            "Restore Splits",
            f"{result}",
            "Restore Splits",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )
        return result == "PASS"

    def merge_splits(
        self, target_file: str, split_count: int, v: int, isCBT: bool = False
    ):
        # Merge
        # ./idevsutil --password-file=1234 --port=900 --xml-output --pvt-key=1234 --device-id=5c0bD017718384600007254654b5z test1@localhost::home/
        # --destination-file="/home/IDdr/IDDriveImage/random_1gb_file1.bin"
        # --type  --merge-file
        # --split-count=3
        args = [
            "--xml-output",
            "--merge-file",
            "--type",
            f"--destination-file={target_file}",
            f"--split-count={split_count}",
            self.tool.remote(),
        ]
        r = self.tool.run(args, f"merge_splits_{v:03d}")
        result = "FAIL"
        if r is not None:
            result = "PASS" if r["return_code"] == 0 else "FAIL"

        name = Path(target_file).name
        self.add(
            f"SPLIT-RESTORE-MERGE-SPLITS-{name}",
            "Merge Restored Splits",
            f"{result}",
            "Merge Splits",
            str(r["return_code"]),
            r["stderr"],
            f"Build: {self.tool.build.name}",
        )
        return result == "PASS"

    def split_restore(
        self,
        original_files: dict[str, Any],
        v: int,
        split_count: int,
        isCBT: bool = False,
    ):
        src = self.split_source
        dst = self.split_restored / f"V{v:03d}"
        snapshot = self.split_snapshots
        filelist = self.split_lists
        receive_meta_name = f"restore_{v:03d}_receive_metadata.txt"
        split_restore_name = f"restore_{v:03d}_split_restore.txt"

        if isCBT:
            src = self.cbt_source
            dst = self.cbt_restored / f"V{v:03d}"
            snapshot = self.cbt_snapshots
            filelist = self.cbt_lists
            receive_meta_name = f"cbt_{v:03d}_receive_metadata.txt"
            split_restore_name = f"cbt_{v:03d}_split_restore.txt"

        fl: Path = filelist / receive_meta_name

        split_restore_create_config_xml_file(fl, src, v=v)
        # dst = input("Restore Location: ").strip() or "/"

        snapFiles: list[Path] = []

        for file_path in original_files.keys():
            file = Path(file_path)
            source: str = ""
            absPath: str = ""
            relPath: str = ""
            if os.name == "nt":
                source = toPosix(src)
                absPath = toPosix(file.parent)
            else:
                source = str(src)
                absPath = str(file.parent)

            relPath = absPath.split(source)[1].lstrip("/")

            versioned = ""
            if relPath == "":
                versioned = file.name + f"_V{v:03d}"
            else:
                versioned = relPath + "/" + file.name + f"_V{v:03d}"

            snap = snapshot / versioned

            if os.name == "nt":
                snap = toPosix(Path(snap))

            if isinstance(snap, str):
                snap = Path(snap)

            snapFiles.append(snap)

        if not dst.exists():
            dst.mkdir(parents=True, exist_ok=True)

        split_meta = self.split_receive_metadata(fl=fl, dst=str(dst), v=v)

        # fl = self.split_lists / f"restore_{v:03d}_split_restore.txt"
        fl = filelist / split_restore_name

        self._split_restore(split_meta=split_meta, fl=fl, dst=str(dst), v=v)

        for path in original_files.keys():
            abs_path = Path(dst).joinpath(path.lstrip("/"))
            self.merge_splits(target_file=str(abs_path), split_count=split_count, v=v)

        return self.validate_restore(
            dest=dst,
            uploadedFiles=snapFiles,
            v=v,
            isRegularFile=0,
            original_files_dict=original_files,
            isCBT=isCBT,
        )

    def split_backup(
        self, v: int, split_count: int, files: list[Path] = []
    ) -> dict[str, Any]:
        all_files: list[Path] = files

        if len(all_files) == 0:
            all_files = get_all_files_from_list(self.tool.env.fileListPath)
        origin_files_to_split: dict[str, Any] = {}

        fl = self.split_lists / f"backup_{v:03d}_sync_check.txt"

        for i, file in enumerate(all_files):
            mode = "a" if i > 0 else "w"
            stats = split_file(
                file_path=str(file),
                split_count=split_count,
                # fl_path=self.split_bkp_syntax_path,
                fl_path=str(fl),
                mode=mode,
            )
            if stats is not None:
                path = stats["path"]
                origin_files_to_split[path] = stats
                for f in stats["splits_info"]:
                    name = f["name"]
                    size = f["size"]
                    checksum = f["checksum"]
                    mdt = f["mdt"]
                    self.add_file(name=name, checksum=checksum, size=size, mdt=mdt)

        file_csv = self.split_source / f"split_info_{v:03d}.json"
        self.write_file_info(file_csv)

        session = self.sync_check(str(fl), v=v)

        fl = self.split_lists / f"backup_{v:03d}_split_backup.txt"
        ordered_file_paths: list[Path] = []
        if session is not None:
            ordered_file_paths = self._split_backup(
                session, origin_files_to_split=origin_files_to_split, fl=fl, v=v
            )

            fl = self.split_lists / f"backup_{v:03d}_send_meta.txt"

            self._send_split_metadata(
                original_files_to_split=origin_files_to_split,
                sessionID=session,
                split_count=split_count,
                fl=fl,
                v=v,
            )
            self._copy_snapshot(
                v=v,
                files=files,
                files_source=self.split_source,
                files_snapshot=self.split_snapshots,
            )
        return {
            "origin_files_to_split": origin_files_to_split,
            "ordered_file_paths": ordered_file_paths,
        }

    def validate_backup(self, isRegularFile: int = 1, module: str = "SPLIT-FILES"):
        print("-" * 90)
        if bool(isRegularFile):
            print("FULL & INC Backup Complete. Validating Results..")
        else:
            print("FULL & INC Split Backup Complete. Validating Results..")
        print("-" * 90)

        all_files = self.db.get_all(table="ibtable", isRegularFile=isRegularFile)
        dirs = {}

        for item in all_files:
            id = item["uid"]
            if id != "":
                itempath = self.db.get_path_by_uid(id)
                parent = str(Path(itempath).parent)
                if os.name == "nt":
                    parent = Path(itempath).parent.as_posix()
                name = Path(itempath).name
                if parent not in dirs:
                    dirs[parent] = [name]
                else:
                    dirs[parent].append(name)

        for dir, children in dirs.items():
            name = "auth_list" + str(dir).replace("/", "_")
            r = self.tool.auth_list(
                True, remotePath=dir, isRegularFile=isRegularFile, name=name
            )
            # r = self.tool.search(isSuiteRunning=True, filesOnly=True)
            tc_name = "AUTH-LIST-REGULAR-FILE" if bool(isRegularFile) else module
            if r["return_code"] != 0:
                self.add(
                    tc_name,
                    f"Not all Files Present in cloud after upload - Actual [{len(self.files)}] has to be present",
                    "FAIL",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.tool.build.name}",
                )
                return False

            else:
                pattern = r'fname="([^"]*)"'
                itemsFound = re.findall(pattern, r["stdout"])

                items = set()

                for name in children:
                    items.add(name)

                for _, item in enumerate(itemsFound):
                    data = str(item)
                    # `!@#$%^&    *()_+=-|;:\'         "?,<   .>
                    # `!@#$%^&amp;*()_+=-|;:&apos;&quot;?,&lt;.&gt;
                    # `!@#$%^&    *()_+=-|;:'\     "         ?,<.>,
                    data = data.replace("&amp;", "&")
                    data = data.replace("&apos;", "'")
                    data = data.replace("&quot;", '"')
                    data = data.replace("&lt;", "<")
                    data = data.replace("&gt;", ">")
                    try:
                        items.remove(data.strip())
                    except Exception as e:
                        print(f"Key not found: {data.strip()}", e)

                self.add(
                    tc_name,
                    f"Items Supposed to be Present in {dir} after upload - {len(children)}",
                    f"{'PASS' if len(items) == 0 else 'FAIL'}",
                    "Return code 0",
                    str(r["return_code"]),
                    r["stderr"],
                    f"Build: {self.tool.build.name}",
                )
        # self.finish()

    def write_file_info(self, json_path: Path):
        json_path.write_text(
            json.dumps([asdict(r) for r in self.filesInfo], indent=2), encoding="utf-8"
        )
        self.filesInfo = []

    def finish(self):
        passed = sum(r.status == "PASS" for r in self.results)
        failed = sum(r.status == "FAIL" for r in self.results)

        json_path = self.root / "regression_results.json"
        csv_path = self.root / "regression_results.csv"
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
        print(f"BACKUP & RESTORE REGRESSION COMPLETE: PASS={passed} FAIL={failed}")
        print(f"CSV: {csv_path}")
        print(f"JSON: {json_path}")
        print("=" * 90)
        return failed == 0
