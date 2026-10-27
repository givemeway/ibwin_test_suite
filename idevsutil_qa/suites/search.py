from __future__ import annotations

import csv
import random
import time
import re
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Any

from ..core.idevsutil import IdevsUtil
from ..models import Result
from ..utils import build_file_tree, all_nodes, copy_tmp_dump
from ..db import FileTreeDatabase


class SearchSuite:
    """Interactive search commands and executable search regression tests."""

    def __init__(
        self,
        idevs: IdevsUtil,
        run_dir: Optional[Path] = None,
        db: FileTreeDatabase | None = None,
        files: List[Path] = [],
    ):
        self.tool = idevs
        self.files = files
        self.run_dir = run_dir or idevs.run_dir
        self.results: List[Result] = []
        self.isSearchSuiteRunning = False
        self.seed = 1234
        self.db = db
        self.updater_binary = Path(self.tool.build.working_dir).parent.joinpath(
            "UPDATER", "src", "idevsupdate"
        )

    def _record(
        self,
        test_id: str,
        description: str,
        result: dict,
        details: str,
        duration: str = "",
    ) -> bool:
        """Convert an idevsutil execution result into a QA PASS/FAIL."""
        passed = result.get("passed", False)
        expected = result.get("expected", "")
        actual = result.get("actual", "")
        status = "PASS" if passed else "FAIL"
        self.results.append(
            Result(
                test_id=test_id,
                expected=f"Expected {expected} items in search",
                actual=f"Actual {actual} items in search",
                description=description,
                status=status,
                build=f"{self.tool.build.name} - {self.tool.build.release}",
                details=details,
                duration=duration,
            )
        )
        print(f"[{status}] {test_id} - {description}")
        return passed

    def delete_items(self, v: int = 1, remotePath: str = "/", seed: int = 412384):
        if self.db is None:
            return

        fl: Path = self.run_dir / "filelist.txt"

        all_items_ibtable = self.db.get_all(isRegularFile=1)
        rng = random.Random(seed)

        folders_only = []
        files_only = []
        for item in all_items_ibtable:
            if bool(item["is_folder"]):
                folders_only.append(item)
            if not bool(item["is_folder"]):
                files_only.append(item)

        choice = rng.choice(["folder", "file"])
        toDelete: dict[str, Any] | None = None

        if choice == "folder" and len(folders_only) > 0:
            print("Folder is the Choice")
            toDelete = rng.choice(folders_only)

        if choice == "file" and len(files_only) > 0:
            print("File is the Choice")
            toDelete = rng.choice(files_only)

        itemsToWriteOnFilelist = set()
        itemsToCompare: set[str] = set()
        itemsSupposedToBeDeleted = set()

        if toDelete is not None:
            if bool(toDelete["is_folder"]):
                # children = self.db.list_record_children(toDelete["parent_id"])
                # for child in children:
                #    path = self.db.get_path_by_uid(child["uid"])
                #    itemsToWriteOnFilelist.add(path)
                with fl.open("w", encoding="utf-8") as f:
                    path = self.db.get_path_by_uid(toDelete["uid"])
                    f.write(path + "\n")

            else:
                path = self.db.get_path_by_uid(toDelete["uid"]).rstrip("/")
                itemsToWriteOnFilelist.add(path)
                with fl.open("w", encoding="utf-8") as f:
                    for item in itemsToWriteOnFilelist:
                        f.writelines(item + "\n")

            if int(self.tool.env.dedup) == 1:
                self.tool.env.device_id = toDelete["device_id"]

            # self.tool.run(["killall", "idevsupdate"], name="sys_cmds")
            out = self.tool.delete_items(fl=str(fl), isSuiteRunning=True, v=str(v))

            # copy_tmp_dump(
            #     self.run_dir, Path(self.tool.env.userRoot), self.tool.env.username
            # )
            # self.tool.run([self.updater_binary, "--daemon"], name="sys_cmds")

            # time.sleep(5)

            # details = out.get("stderr", "").strip()
            details = out.get("stdout", "").strip()  # if details == "" else details

            itemsDeletedWithServerRoot = self._extract_fname(details)
            itemsDeletedWithoutServerRoot: set[str] = set()

            self.db.delete(toDelete["uid"], move_to_trash=True)
            trash_items = self.db.get_all(table="trash")

            for item in trash_items:
                path = self.db.get_path_by_uid(
                    item["uid"],
                    table="trash",
                    parent_id_ibtable=item["parent_id_ibtable"],
                )

                if path is not None:
                    if not bool(item["is_folder"]):
                        path = path.rstrip("/")
                    itemsSupposedToBeDeleted.add(path)

            if int(self.tool.env.dedup) == 1:
                for item in itemsDeletedWithServerRoot:
                    parts = item.split("/")[2:]
                    p = "/" + "/".join(parts)
                    itemsDeletedWithoutServerRoot.add(p)

            itemsToCompare = (
                itemsDeletedWithoutServerRoot
                if int(self.tool.env.dedup) == 1
                else itemsDeletedWithServerRoot
            )

            for item in itemsSupposedToBeDeleted:
                try:
                    itemsToCompare.remove(item)
                except:
                    print("Key Not found: ", item)

            result = {
                "expected": len(itemsSupposedToBeDeleted),
                "passed": False,
                "actual": len(itemsDeletedWithServerRoot),
            }

            if len(itemsToCompare) == 0:
                result["passed"] = True

            test_id = f"SEARCH-{v:03d}"
            description = "Delete Item"

            self._record(
                test_id=test_id,
                description=description,
                result=result,
                details=details,
                duration=out["duration"],
            )

        return itemsSupposedToBeDeleted

    def search_recent_files(
        self, v: int = 1, recent: int = 0, key: str = "", dst: str = "/"
    ):
        args = [
            "--search",
            "--xml-output",
            "--file",
            f"--recent={recent}",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

        test_id = f"SIMPLE-SEARCH-{v:03d}"
        log_name = f"SEARCH-{v:03d}"
        name = "Simple Search - Recent Files"

        out = self.tool.run(args, log_name)
        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        itemsFoundInSearch = self._extract_fname(details)
        itemsToMatch = set()

        all_items_ibtable = self.db.get_all(
            table="ibtable",
            order_by="rowid",
            sort="desc",
            limit=recent,
            is_folder=0,
        )

        for item in all_items_ibtable:
            if not bool(item["is_folder"]):
                path: str
                if (
                    int(self.tool.env.dedup) == 1
                    and item["device_id"] == self.tool.env.device_id
                ):
                    path = self.db.get_path_by_uid(item["uid"])
                else:
                    path = self.db.get_path_by_uid(item["uid"])
                itemsToMatch.add(path.rstrip("/"))

        result = self.validate_search(itemsToMatch, itemsFoundInSearch)
        self._record(
            test_id=test_id,
            description=name,
            result=result,
            details=details,
            duration=out["duration"],
        )

    def search_simple(
        self,
        filesOnly: bool,
        foldersOnly: bool,
        v: int = 1,
        key: str = "",
        dst: str = "/",
    ):
        """
        ./idevsutil --search test5@localhost::home/
            --port=900 --password-file=1234 --xml-output --device-id=
        --Above is root/account search

        ./idevsutil --search --search-key=.jpg:file test5@localhost::home/
        --port=900 --password-file=1234 --xml-output --device-id=

        """
        # key = input("Search Keyword: ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        args = ["--xml-output", "--search", self.tool.remote(dst)]

        if self.db is None:
            return

        if key != "":
            args.append(f"--search-key={key}")
        if filesOnly:
            args.append("--file")
        if foldersOnly:
            args.append("--folder")
        name = "Simple Search - Files & Folders"
        log_name = "search_simple_all_files_folders"
        if filesOnly:
            name = "Simple Search - Files Only"
            log_name = "search_simple_files_only"
        if foldersOnly:
            name = "Simple Search - Folders Only"
            log_name = "search_simple_folders_only"

        test_id = f"SIMPLE-SEARCH-{v:03d}"

        out = self.tool.run(args, log_name)
        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        itemsFoundInSearch = self._extract_fname(details)
        itemsToMatch = set()

        folders: bool = False
        files: bool = False

        if not foldersOnly and not filesOnly:
            folders = True
            files = True
        if foldersOnly and not filesOnly:
            folders = True
            files = False
        if filesOnly and not foldersOnly:
            files = True
            folders = False

        all_items_ibtable = self.db.get_all(table="ibtable", findAll=True)

        if folders:
            for item in all_items_ibtable:
                if bool(item["is_folder"]):
                    path: str
                    if (
                        int(self.tool.env.dedup) == 1
                        and item["device_id"] == self.tool.env.device_id
                    ):
                        path = self.db.get_path_by_uid(item["uid"])
                    else:
                        path = self.db.get_path_by_uid(item["uid"])
                    itemsToMatch.add(path)
        if files:
            for item in all_items_ibtable:
                if not bool(item["is_folder"]):
                    path: str
                    if (
                        int(self.tool.env.dedup) == 1
                        and item["device_id"] == self.tool.env.device_id
                    ):
                        path = self.db.get_path_by_uid(item["uid"])
                    else:
                        path = self.db.get_path_by_uid(item["uid"])
                    itemsToMatch.add(path.rstrip("/"))

        result = self.validate_search(itemsToMatch, itemsFoundInSearch)
        self._record(
            test_id=test_id,
            description=name,
            result=result,
            details=details,
            duration=out["duration"],
        )

        return details

    def search_trash(
        self,
        toBeMatched: set[str] = set(),
        v: int = 1,
        expected: int = 0,
        key: str = "",
        dst: str = "/",
    ):
        """
        ./idevsutil --search --trash test5@localhost::home/
        --port=900 --password-file=1234 --xml-output --device-id=
        """
        # key = input("Search Keyword: ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        args = ["--xml-output", "--search", "--trash", self.tool.remote(dst)]

        if key != "":
            args.append(f"--search-key={key}")
        out = self.tool.run(args, "search_trash")
        # details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip()  # if details == "" else details

        itemsFoundInSearch = self._extract_fname(details)
        itemsToMatch = toBeMatched

        result = self.validate_search(itemsToMatch, itemsFoundInSearch)
        test_id = f"SEARCH-{v:03d}"
        description = "Search Trash"
        self._record(
            test_id=test_id,
            description=description,
            result=result,
            details=details,
            duration=out["duration"],
        )

    def search_all(
        self,
        key: str = "",
        dst: str = "/",
    ):
        """
        ./idevsutil --search --all test5@localhost::home/
        --port=900 --password-file=1234 --xml-output --device-id=
        """
        #        key = input("Search Keyword: ").strip() or ""
        #        dst = input("Remote DST path: ").strip() or "/"
        args = ["--xml-output", "--search", "--all", self.tool.remote(dst)]

        if key != "":
            args.append(f"--search-key={key}")

    def search_file_index64(self, idx: int = 0, key: str = "", dst: str = "/"):
        """
        ./idevsutil --search --file-index64=0 --app-index64 test5@localhost::home/
            --port=900 --password-file=1234
            --xml-output --device-id=
        """
        # idx = input("file-index64 [0]: ").strip() or 0
        # key = input("Search Keyword: ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            f"--file-index64={idx}",
            # "--app-index64",
            self.tool.remote(dst),
        ]

        if key != "":
            args.append(f"--search-key={key}")

    def search_key(self):
        key = input("Search keyword: ").strip() or ""
        dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--search",
            "--xml-output",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_dirid(self, key: str = "", dst: str = "/"):
        # key = input("Search Keywoard : ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            "--dirid",
            "--ref-id",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_attrib(self, key: str = "", dst: str = "/"):
        #        key = input("Search Keywoard : ").strip() or ""
        #        dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            "--attrib",
            "--starred",
            self.tool.remote(dst),
        ]

        if key != "":
            args.append(f"--search-key={key}")

    def search_no_versions(self, key: str = "", dst: str = "/"):
        #        key = input("Search Keywoard : ").strip() or ""
        #        dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            "--no-versions",
            "--file",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_previous_version(
        self, key: str = "", dst: str = "/", vr_limit: str = "1"
    ):
        #        vr_limit = input("Version to limit[INT]: ").strip() or "1"
        #        key = input("Search Keywoard : ").strip() or ""
        #        dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            f"--prv-versions={vr_limit}",
            "--file",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_file(self):
        """
        ./idevsutil --search --file test5@localhost::home/
        --port=900 --password-file=1234 --xml-output --device-id=
        """
        key = input("Search Keywoard : ").strip() or ""
        dst = input("Remote DST to search: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            "--file",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_regx(
        self,
        v: int = 0,
        key: str = "",
        dst: str = "/",
        filesOnly: bool = False,
        foldersOnly: bool = False,
        toBeMatched: set[str] = set(),
    ):
        """
         It can be verified by passing destination or root both are valid
         Suppose /home/IDrive/EVS/TEST/ is the path and destination given is
            /home//TEST/-- should work as regular expression

        ./idevsutil --search --regx test5@localhost::home/home/*/TEST/
        --port=900 --password-file=1234 --xml-output --device-id=

        """
        # key = input("Regex Keyword: ").strip() or ""
        # dst = input("Remote DST to search: ").strip() or "/"
        dst += key

        args = [
            "--xml-output",
            "--search",
            "--regx",
            self.tool.remote(dst),
        ]

        if filesOnly:
            args.append("--file")

        if foldersOnly:
            args.append("--folder")

        out = self.tool.run(args, "search_regex")
        details = out.get("stderr", "").strip()
        details = out.get("stdout", "").strip() if details == "" else details

        itemsFoundInSearch = self._extract_fname(details)
        itemsToMatch = toBeMatched

        result = self.validate_search(itemsToMatch, itemsFoundInSearch)
        test_id = f"SEARCH-{v:03d}"
        description = "Search Trash"
        self._record(
            test_id=test_id,
            description=description,
            result=result,
            details=details,
            duration=out["duration"],
        )

    def search_lorder_torder(self):
        args = [
            "--xml-output",
            "--search",
            "--lorder",
            "--corder",
            "--torder",
            self.tool.remote(),
        ]

    def quick_search(self, dst: str = "/", rowid: int = 1):
        args = [
            "--xml-output",
            "--search",
            "--quick-search",
            "--search-criteria=2",
            "--file-index64=0",
            f"--rowid={rowid}",
            f"--o={self.run_dir}/o.txt",
            f"--e={self.run_dir}/e.txt",
            self.tool.remote(dst),
        ]
        r = self.tool.run(args, "quick_search")
        outfile = Path(self.run_dir).joinpath("o.txt")
        errfile = Path(self.run_dir).joinpath("e.txt")
        stdout = ""
        stderr = ""
        with outfile.open("r", encoding="utf-8") as f:
            stdout = f.read()
        with errfile.open("r", encoding="utf-8") as f:
            stderr = f.read()

        itemsFound = set()
        item = self.db.get_by_path(dst)
        itemsToMatchItems = self.db.list_children(
            item["uid"] if item is not None else None
        )
        itemsToMatch = set()

        for item in itemsToMatchItems:
            path = self.db.get_path_by_uid(item["uid"])
            if path is not None:
                itemsToMatch.add(path)

        if stdout != "":
            itemsFound = self._extract_fname(stdout)
        if len(itemsFound) > 0:
            result = self.validate_search(
                itemsToMatch=itemsToMatch, itemsFoundInSearch=itemsFound
            )
            print(result)

    def search_criteria2(self, key: str = "", dst: str = "/"):
        # key = input("Search Keywoard : ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        args = [
            "--xml-output",
            "--search",
            "--search-criteria=2",
            self.tool.remote(dst),
        ]
        if key != "":
            args.append(f"--search-key={key}")

    def search_label(self, label: str, itemsToMatch, key: str = "", dst: str = "/"):
        # key = input("Label Keywoard : ").strip() or ""
        # dst = input("Remote DST path: ").strip() or "/"
        if key == "":
            print("Invalid Label")
            return
        args = [
            "--xml-output",
            "--search",
            f"--label={label}",
            self.tool.remote(dst),
        ]

        if key != "":
            args.append(f"--search-key={key}")

        out = self.tool.run(args, "search_label")
        details = out.get("stderr", "")
        details = out.get("stdout", "") if details == "" else details
        itemsFound = self._extract_fname(details)
        result = self.validate_search(itemsToMatch=set(), itemsFoundInSearch=itemsFound)

    def _extract_fname(self, stdout: str) -> set:
        pattern = r'fname="([^"]*)"'
        itemsFound = re.findall(pattern, stdout)
        _set = set()
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
            _set.add(data.strip())
        return _set

    def get_mto_items(self, seed: int):
        trash_items = self.db.get_all(table="trash", findAll=True)
        rng = random.Random(seed)

        folders_only = []
        files_only = []
        for item in trash_items:
            if bool(item["is_folder"]):
                folders_only.append(item)
            if not bool(item["is_folder"]):
                files_only.append(item)

        choice = rng.choice(["folder", "file"])
        toDelete: dict[str, Any] | None = None

        if choice == "folder" and len(folders_only) > 0:
            print("Folder is the Choice")
            toDelete = rng.choice(folders_only)

        if choice == "file" and len(files_only) > 0:
            print("File is the Choice")
            toDelete = rng.choice(files_only)

        return toDelete

    def move_to_original(self, to_move: list[str], v: int):
        fl: Path = self.run_dir / "MTO_list.txt"
        with fl.open("w", encoding="utf-8") as f:
            for path in to_move:
                f.writelines(path + "\n")
        r = self.tool.move_to_original(
            isSuiteRunning=True, filelist=str(fl), name=f"move_to_original_{v}"
        )
        if r is not None:
            details = r.get("stdout", "").strip()  # if details == "" else details

            itemsDeletedWithServerRoot = self._extract_fname(details)
            itemsDeletedWithoutServerRoot: set[str] = set()
            for path in to_move:
                movedItem = self.db.get_by_path_new(path=path, isRegularFile=1)
                self.db.restore_subtree_from_trash(uid=movedItem["uid"])

            trash_items = self.db.get_all(table="trash")

            for item in trash_items:
                path = self.db.get_path_by_uid(
                    item["uid"],
                    table="trash",
                    parent_id_ibtable=item["parent_id_ibtable"],
                )

                if path is not None:
                    if not bool(item["is_folder"]):
                        path = path.rstrip("/")
                    itemsSupposedToBeDeleted.add(path)

            if int(self.tool.env.dedup) == 1:
                for item in itemsDeletedWithServerRoot:
                    parts = item.split("/")[2:]
                    p = "/" + "/".join(parts)
                    itemsDeletedWithoutServerRoot.add(p)

            itemsToCompare = (
                itemsDeletedWithoutServerRoot
                if int(self.tool.env.dedup) == 1
                else itemsDeletedWithServerRoot
            )

            for item in itemsSupposedToBeDeleted:
                try:
                    itemsToCompare.remove(item)
                except:
                    print("Key Not found: ", item)

            result = {
                "expected": len(itemsSupposedToBeDeleted),
                "passed": False,
                "actual": len(itemsDeletedWithServerRoot),
            }

            if len(itemsToCompare) == 0:
                result["passed"] = True

            test_id = f"SEARCH-{v:03d}"
            description = "Delete Item"

            self._record(
                test_id=test_id,
                description=description,
                result=result,
                details=details,
                duration=r["duration"],
            )

    def validate_search(self, itemsToMatch: set, itemsFoundInSearch: set) -> dict:
        _set = itemsToMatch
        expected = len(_set)
        actual = len(itemsFoundInSearch)

        for item in itemsFoundInSearch:
            try:
                _set.remove(item.strip())
            except Exception as e:
                print(f"Key not found <==>: {item}", e)
        passed: bool = False
        if len(_set) == 0:
            passed = True

        return {"expected": expected, "passed": passed, "actual": actual}

    def run_full_suite(self) -> bool:
        self.results.clear()
        self.tool.isRegression = True

        print("\n" + "#" * 90)
        print("SEARCH REGRESSION SUITE")
        print("#" * 90)
        print(f"Build: {self.tool.build.name} / {self.tool.build.release}")

        self.search_simple(v=1, filesOnly=False, foldersOnly=False)
        self.search_simple(v=2, filesOnly=True, foldersOnly=False)
        self.search_simple(v=3, filesOnly=False, foldersOnly=True)
        self.search_trash(toBeMatched=set(), v=4, expected=0)

        deletedItemsToMatch = self.delete_items(v=5, seed=12022024)

        time.sleep(5)

        self.search_trash(
            toBeMatched=set(deletedItemsToMatch), v=6, expected=len(deletedItemsToMatch)
        )

        deletedItemsToMatch = self.delete_items(v=7, seed=14011986)

        time.sleep(5)

        self.search_trash(
            toBeMatched=set(deletedItemsToMatch), v=8, expected=len(deletedItemsToMatch)
        )

        self.search_recent_files(v=9, recent=10)

        # self.search_all()
        # self.search_file_index64()

        return self.finish()

    def finish(self) -> bool:
        passed = sum(r.status == "PASS" for r in self.results)
        failed = sum(r.status == "FAIL" for r in self.results)
        total = len(self.results)

        self.run_dir.mkdir(parents=True, exist_ok=True)

        json_path = self.run_dir / "search_results.json"
        csv_path = self.run_dir / "search_results.csv"

        json_path.write_text(
            json.dumps([asdict(r) for r in self.results], indent=2),
            encoding="utf-8",
        )

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "test_id",
                    "description",
                    "status",
                    "expected",
                    "actual",
                    "build",
                    "details",
                    "duration",
                ],
            )
            writer.writeheader()
            for result in self.results:
                writer.writerow(asdict(result))

        overall = "PASS" if failed == 0 and total > 0 else "FAIL"

        print("\n" + "=" * 90)
        print(f"SEARCH SUITE RESULT  : {overall}")
        print(f"TOTAL                : {total}")
        print(f"PASS                 : {passed}")
        print(f"FAIL                 : {failed}")
        print(f"CSV                  : {csv_path}")
        print(f"JSON                 : {json_path}")
        print("=" * 90)

        return overall == "PASS"

    def menu(self):
        while True:
            print("\n" + "=" * 80)
            print("SEARCH SUITE")
            print("=" * 80)
            print(" 1. Search")
            print(" 2. --trash")
            print(" 3. --all")
            print(" 4. --file-index64=0 --app-index64")
            print(" 5. --dirid re-fid")
            print(" 6. --attrib --starred")
            print(" 7. --no-versions --file")
            print(" 8. --prv-version=1 --file")
            print(" 9. --search-key")
            print("10. --lorder --torder")
            print("11. --search-criteria=2")
            print("12. --file only ")
            print("13. --rowid --limit")
            print("14. --fld-rowid --rowid --limit")
            print("15. --search-by-passing-destination-at-the-folder")
            print("16. --dedup-search")
            print("17. --dedup-search2")
            print("18. --fileindex-last")
            print("19. --label")
            print("20. --regx search")
            print("21. RUN FULL SEARCH SUITE")
            print("22. Quick Search")
            print(" 0. Back")
            c = input("\n SEARCH > ").strip()
            if c == "0":
                return
            elif c == "1":
                self.search_simple()
            elif c == "2":
                self.search_trash()
            elif c == "3":
                self.search_all()
            elif c == "4":
                self.search_file_index64()
            elif c == "5":
                self.search_dirid()
            elif c == "6":
                self.search_attrib()
            elif c == "7":
                self.search_no_versions()
            elif c == "8":
                self.search_previous_version()
            elif c == "9":
                self.search_key()
            elif c == "10":
                self.search_lorder_torder()
            elif c == "11":
                self.search_criteria2()
            elif c == "12":
                self.search_file()
            elif c == "20":
                self.search_regx()
            elif c == "21":
                self.run_full_suite()
            elif c == "22":
                self.quick_search()
            else:
                return
