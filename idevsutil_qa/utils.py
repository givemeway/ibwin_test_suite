from __future__ import annotations

import hashlib
import os
import re
import math
import random
import shutil
import subprocess
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import List, Any
from .models import FileTreeNodeNew
from .db import VersionRecord

MB: int = 1024 * 1024
KB: int = 1024
SPLIT_SIZE = 1024 * 1024 * 512
BLOCK_SIZE = 1024 * 32
BLOCKS_IN_SPLIT = SPLIT_SIZE // BLOCK_SIZE


def copy_tmp_dump(root: Path, userRoot: Path, username: str):
    tmp_db_path = userRoot.joinpath(username, "user_root_tmp_db")
    dump_path = root.joinpath("tmp_dump")
    if not dump_path.exists():
        dump_path.mkdir(parents=True, exist_ok=True)

    for txt_file in tmp_db_path.rglob("*.txt"):
        if txt_file.is_file():
            shutil.copy2(txt_file, str(dump_path))
            print(f"Copied: {txt_file.name}")


def log_to_file(log_file, message: str):
    with open(log_file, "a") as f:
        f.write(message + "\n")


def compare_dicts_and_format(
    dict_one, dict_two, separator="27α/ß20", repo_link_flag: int = 0, version: int = 1
):
    # dict_one = { path: {checksum: checksum,checksumpath: checksumpath} }
    # dict_two = { checksum: [paths] }
    result_list = []
    no_link_list = []
    log_to_file("dict_two.log", f"{dict_two}")
    log_to_file("dict_one.log", f"{dict_one}")
    for val in dict_one.values():
        checksum = val["checksum"].strip()
        checksumpath = val["checksumpath"]
        log_to_file("dicts.log", f"checksum: {checksum}")
        log_to_file("dicts.log", f"checksumpath: {checksumpath}")
        if checksum in dict_two:
            value: list[str] | dict[str, Any] = dict_two[checksum]
            formatted_line: str = ""
            src_chk_path: str
            link_path: str
            ver: int
            repo_no: str
            repo_flag: int = 0
            if isinstance(value, list):
                src_chk_path = val["checksumpath"]
                if isinstance(value[0], dict):
                    link_path = value[0]["fname"]
                    ver = value[0]["version"]
                    repo_no = value[0]["repo_number"]
                    repo_flag = repo_link_flag

                if isinstance(value[0], str):
                    link_path = value[0]
                    ver = version
                    repo_no = "NA"
                    repo_flag = repo_link_flag

            formatted_line = (
                f"{src_chk_path}{separator}{link_path}${ver}${repo_no}${repo_flag}"
            )

            result_list.append(formatted_line)
        else:
            no_link_list.append(checksumpath)

    return {"link": result_list, "nolink": no_link_list}


def extract_repo_info(stdout: str) -> dict[str, Any]:
    print("Extracting items ....", stdout)
    fname = r'fname="([^"]*)"'
    version = r'version="([^"]*)"'
    repo_no = r'repo_number="([^"]*)"'
    checksum = r'checksum="([^"]*)"'
    ref_id = r'ref_id="([^"]*)"'
    fullpath_seekid = r'fullpath_seekid="([^"]*)"'
    softlink = r'soft_link="([^"]*)"'

    fnamesFound = re.findall(fname, stdout)
    versionsFound = re.findall(version, stdout)
    repoFound = re.findall(repo_no, stdout)
    checksumFound = re.findall(checksum, stdout)
    refidFound = re.findall(ref_id, stdout)
    seekidFound = re.findall(fullpath_seekid, stdout)
    softlinkFound = re.findall(softlink, stdout)
    repo_list = []
    repo_dict = {}

    for fname, version, repo, chk, refid, seekid, softlink in zip_longest(
        fnamesFound,
        versionsFound,
        repoFound,
        checksumFound,
        refidFound,
        seekidFound,
        softlinkFound,
    ):
        data = str(fname)
        # `!@#$%^&    *()_+=-|;:\'         "?,<   .>
        # `!@#$%^&amp;*()_+=-|;:&apos;&quot;?,&lt;.&gt;
        # `!@#$%^&    *()_+=-|;:'\     "         ?,<.>,
        data = data.replace("&amp;", "&")
        data = data.replace("&apos;", "'")
        data = data.replace("&quot;", '"')
        data = data.replace("&lt;", "<")
        data = data.replace("&gt;", ">")
        fname = data.strip()
        _dict = {
            "checksum": chk,
            "fname": fname,
            "version": version,
            "repo_number": repo,
            "ref_id": refid,
            "fullpath_seekid": seekid,
            "soft_link": softlink,
        }
        if chk not in repo_dict:
            repo_dict[chk] = [_dict]
            repo_list.append(_dict)
        else:
            repo_dict[chk].append(_dict)
    print("Extracting items DONE....")

    return repo_dict


def extract_split_received_metadata(output: str) -> dict[str, Any]:
    split_count_pattern = r"SplitCount=(\d+)"
    size_pattern = r"Size=(\d+)"
    mdt_long_pattern = r"Mdt_Long=(\d+)"

    split_no_pattern = r"SplitNumber=(\d+)"
    version_no_pattern = r"VersionNumber=(\d+)"
    split_size_pattern = r"SplitSize=(\d+)"

    fname_pattern = r'fname="([^"]*)"'

    split_counts = re.findall(split_count_pattern, output)
    mdts = re.findall(mdt_long_pattern, output)
    sizes = re.findall(size_pattern, output)
    fnames = re.findall(fname_pattern, output)
    fnames_sanitized = []

    for data in fnames:
        data = data.replace("&amp;", "&")
        data = data.replace("&apos;", "'")
        data = data.replace("&quot;", '"')
        data = data.replace("&lt;", "<")
        data = data.replace("&gt;", ">")
        fnames_sanitized.append(data)

    split_numbers = re.findall(split_no_pattern, output)
    split_versions = re.findall(version_no_pattern, output)
    split_sizes = re.findall(split_size_pattern, output)

    metadata = {}
    start = 0
    end = 0
    for count, size, mdt, fname in zip(split_counts, sizes, mdts, fnames_sanitized):
        ori_filename = "/" + fname.split("_config.xml")[0].strip()
        end = end + int(count)
        if ori_filename not in metadata:
            file_split_nos = split_numbers[start:end]
            file_split_vers = split_versions[start:end]
            file_split_sizes = split_sizes[start:end]
            file_splits = []
            for n, v, s in zip(file_split_nos, file_split_vers, file_split_sizes):
                obj = {"SplitNumber": n, "VersionNumber": v, "SplitSize": s}
                file_splits.append(obj)
            metadata[ori_filename] = {
                "Size": size,
                "Mdt_Long": mdt,
                "SplitCount": count,
                "Splits_Info": file_splits,
            }
            start = int(count)
    return metadata


def create_file_dict(
    fromFile: bool = False,
    output: str = "",
    chk_file_list_path: Path = Path("/"),
    file_list_path: Path = Path("/"),
):
    link_chk_file_list = []
    print("Creating Link file set ...")
    log_to_file("details2.log", output)

    if not fromFile and output != "":
        link_chk_file_list = [
            line.strip()
            for line in output.splitlines()
            if line.strip() != "DES keylen=8 ivlen=8 EVP_BytesToKey result=8"
        ]
    if fromFile and output == "":
        with chk_file_list_path.open("r", encoding="utf-8") as f:
            link_chk_file_list = [line.strip("\n") for line in f if line.strip()]

    print("Creating Link file set DONE...")

    link_file_paths = []

    with file_list_path.open("r", encoding="utf-8") as f:
        link_file_paths = [line.strip("\n") for line in f if line.strip()]

    link_dict = {}
    print("Creating Link file DICT...")

    for path, checksumpath in zip(link_file_paths, link_chk_file_list):
        parts = checksumpath.split(path)
        if len(parts) > 1:
            checksum = parts[1].split("$")[0].split(":")[1].strip()
            if path not in link_dict:
                link_dict[path] = {
                    "checksumpath": checksumpath,
                    "checksum": checksum,
                }
    print("Creating Link file DICT DONE...")

    return link_dict


def create_checksum_dict(
    fromFile: bool = False,
    chk_file_list_path: Path = Path("/"),
    output: str = "",
    file_list_path: Path = Path("/"),
) -> dict[str, Any]:
    print("Creating source file set...")
    log_to_file("output.log", output)
    source_chk_file_list = []
    if not fromFile and output != "":
        source_chk_file_list = [
            line.strip()
            for line in output.splitlines()
            if line.strip() != "DES keylen=8 ivlen=8 EVP_BytesToKey result=8"
        ]
    elif fromFile and output == "":
        with Path(chk_file_list_path).open("r", encoding="utf-8") as f:
            source_chk_file_list = [line.strip("\n") for line in f if line.strip()]

    source_file_paths = []

    with file_list_path.open("r", encoding="utf-8") as f:
        source_file_paths = [line.strip("\n") for line in f if line.strip()]

    print("Created source file set...")

    print("Creating source DICT ...")

    source_dict = {}

    for path, checksumpath in zip(source_file_paths, source_chk_file_list):
        parts = checksumpath.split(path.strip())
        if len(parts) > 1:
            checksum = parts[1].split("$")[0].split(":")[1].strip()
            if checksum not in source_dict:
                source_dict[checksum] = [path]
            else:
                source_dict[checksum].append(path)

    print("Creating source DICT DONE...")

    return source_dict


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


def create_arg_file(args: list[str], argFilePath: Path) -> None:
    print("args to be written: ", args)
    with argFilePath.open("w", encoding="utf8") as f:
        for arg in args:
            f.write(f"{arg}\n")
        f.write("--acl\n")
        f.write("--encode")


def create_enc_file(enc_str: str, argFilePath: Path) -> None:
    with argFilePath.open("w", encoding="utf8") as f:
        f.write(enc_str)


def create_utf8_file(utf8FilePath: Path, argFilePath: str) -> None:
    with utf8FilePath.open("w", encoding="utf8") as f:
        f.write(f"--utf8-cmd={argFilePath}")


def create_cred_file(credFilePath: Path, enc_psd: str, enc_pk: str) -> None:
    # enc_psd$$$enc_pk
    with credFilePath.open("w", encoding="utf8") as f:
        f.write(f"{enc_psd}$$${enc_pk}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(MB), b""):
            h.update(block)
    hex = h.hexdigest()
    return hex


def sha256_chunked(path: Path, chunk_size: int) -> List[str]:
    file_hash_chunked = []
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h = hashlib.sha256()
            h.update(chunk)
            chunk_hash = h.hexdigest()
            file_hash_chunked.append(chunk_hash)
    return file_hash_chunked


def verify_chunk(
    path: Path, chunk_index: int, expected_hash: str, chunk_size: int = 1 * MB
) -> bool:
    with open(path, "rb") as f:
        f.seek(chunk_index * chunk_size)
        block = f.read(chunk_size)
        actual_hash = hashlib.sha256(block).hexdigest()
        return actual_hash == expected_hash


def info(path: Path) -> dict:
    return {"size": path.stat().st_size, "sha256": sha256(path)}


def create_test_file(path: Path, mb: int, seed: int = 12345):
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    remaining = mb * KB
    with path.open("wb") as f:
        while remaining:
            n = min(KB, remaining)
            f.write(bytes(rng.randrange(256) for _ in range(n)))
            remaining -= n


def insert_data(path: Path, offset: int, data: bytes):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("rb") as src, tmp.open("wb") as dst:
        dst.write(src.read(offset))
        dst.write(data)
        shutil.copyfileobj(src, dst, KB)
    tmp.replace(path)


def remove_data(path: Path, offset: int, length: int):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("rb") as src, tmp.open("wb") as dst:
        dst.write(src.read(offset))
        src.seek(length, os.SEEK_CUR)
        shutil.copyfileobj(src, dst, KB)
    tmp.replace(path)


def replace_data(path: Path, offset: int, length: int, data: bytes):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("rb") as src, tmp.open("wb") as dst:
        dst.write(src.read(offset))
        dst.write(data)
        src.seek(length, os.SEEK_CUR)
        shutil.copyfileobj(src, dst, KB)
    tmp.replace(path)


def replace_data_for_cbt(
    path: Path, offset: int, data: bytes, block_size: int = 32 * 1024
):
    file_size = path.stat().st_size
    current_block_index = offset // block_size
    block_end = (current_block_index + 1) * block_size

    if offset + len(data) > file_size:
        raise ValueError(f"Replacement Data {len(data)} exceeds the size : {file_size}")

    if offset + len(data) > block_end:
        raise ValueError(
            f"Block boundary violation! Block size is {block_size:,} bytes. "
            f"The current block ends at offset {block_end:,}, but the replacement"
            f" data extends to {offset + len(data):,}."
        )

    with path.open("r+b") as f:
        f.seek(offset)
        f.write(data)


def command_line(args):
    return subprocess.list2cmdline(args)


def all_nodes(node: FileTreeNodeNew) -> list[FileTreeNodeNew]:
    nodes = [node]

    for child in node.children:
        nodes.extend(all_nodes(child))

    return nodes


def toPosix(path: Path) -> str:
    a = path.as_posix()
    parts = a.split(":")
    a = "/" + "".join(parts)
    return Path(a).as_posix()


def toWin(path: str) -> Path:
    idx = 1
    if not path.startswith("\\"):
        idx = 0
    parts = path.split("\\")[idx:]
    file = parts[0] + ":" + "\\" + "\\".join(parts[1:])
    return Path(file)


def build_file_tree(items: set[str]) -> FileTreeNodeNew:
    root = FileTreeNodeNew(
        name="",
        is_folder=True,
    )

    for item in items:
        is_folder = item.endswith("/")
        parts = [part for part in item.strip("/").split("/") if part]

        current = root

        for index, part in enumerate(parts):
            is_last_part = index == len(parts) - 1

            child_is_folder = is_folder if is_last_part else True

            child = next(
                (
                    node
                    for node in current.children
                    if node.name == part and node.is_folder == child_is_folder
                ),
                None,
            )

            if child is None:
                child = current.add_child(
                    FileTreeNodeNew(
                        name=part,
                        is_folder=child_is_folder,
                    )
                )

            current = child

    return root


def mutate_files(v, files: list[Path], size: int):
    match v:
        case 1:
            for file in files:
                create_test_file(file, size)
                print(f"V1: {file} : ", info(file))
        case 2:
            for file in files:
                prepend = b"PREPEND_V3\n" * 10000
                insert_data(file, 0, prepend)
        case 3:
            for file in files:
                prepend = b"PREPEND_V3\n" * 10000
                insert_data(file, 0, prepend)
        case 4:
            for file in files:
                insert_data(
                    file, file.stat().st_size // 2, b"MIDDLE_INSERT_V4\n" * 10000
                )
        case 5:
            for file in files:
                remove_data(file, file.stat().st_size // 3, 250_000)
        case 6:
            for file in files:
                same_len = 500_000
                data = (b"SAME_SIZE_REPLACEMENT_V6\n" * 30000)[:same_len]
                replace_data(file, file.stat().st_size // 2, same_len, data)
        case 7:
            for file in files:
                larger = b"LARGER_REPLACEMENT_V7\n" * 20000
                replace_data(file, file.stat().st_size // 4, 250_000, larger)
        case 8:
            for file in files:
                smaller = b"SMALLER_REPLACEMENT_V8\n" * 5000
                replace_data(file, file.stat().st_size // 3, 750_000, smaller)
        case 9:
            for file in files:
                with file.open("r+b") as f:
                    f.truncate(0)
        case 10:
            for file in files:
                smaller = b"SMALLER_REPLACEMENT_V9\n" * 5000
                replace_data(file, file.stat().st_size // 3, 750_000, smaller)


def mutate_cbt_files(v, files: list[Path], size: int = 1024 * 1024 * 1):  # size in kb
    if v == 1:
        file_to_copy = (
            input("VMWare File Path: [/home/sandeep/vmware.vmdk] : ")
            or "/home/sandeep/vmware.vmdk"
            if os.name != "nt"
            else "F:\\vmware.vmdk"
        )
        for file in files:
            print("Copying file ", file_to_copy, " of size: ", size, "...")
            print("To.. ", file.parent)
            shutil.copy2(file_to_copy, str(file.parent))
            # create_test_file(file, size)
            print(f"V1: {file.name} : ", info(file))
    if v > 1:
        # rng = random.Random(v)
        files_info = {}
        cbt_info = {}
        for file in files:
            splits_info = get_splits_and_blocks_to_modify(file=file, seed=v)
            matched_splits = splits_info["matched_splits"]
            to_be_modified_splits = splits_info["modified_splits"]

            for split_fname, blocks in to_be_modified_splits.items():
                for i, file_block in enumerate(blocks):
                    offset = file_block * BLOCK_SIZE
                    data = f"sandy_{i}_{v}".encode()
                    replace_data_for_cbt(file, offset=offset, data=data)
                    split_block = file_block % BLOCKS_IN_SPLIT
                    if split_fname not in cbt_info:
                        cbt_info[split_fname] = [split_block]
                    else:
                        cbt_info[split_fname].append(split_block)

            if str(file) not in files_info:
                files_info[str(file)] = {"matched": matched_splits, "cbt": cbt_info}

        print_cbt_info_considered(files_info=files_info)

        return files_info


def get_splits_and_blocks_to_modify(file: Path, seed: int = 123456):
    try:
        rng = random.Random(seed)
        size = file.stat().st_size
        total_blocks = size // BLOCK_SIZE
        split_count = size // SPLIT_SIZE

        if split_count == 0:
            return {}

        # blocks_per_split = SPLIT_SIZE // BLOCK_SIZE
        # no_of_splits_to_modify = rng.randint(1, split_count)
        # selected_splits = rng.sample(range(split_count), no_of_splits_to_modify)
        # matched_splits = set(list(range(split_count))) - set(selected_splits)
        # selected_blocks: list[dict[str, str]] = []
        #
        # matched_splits_info = []
        #
        # for match in matched_splits:
        #     name = file.name + f"_{match:04d}"
        #     matched_splits_info.append(str(file.parent.joinpath(name)))
        #
        # for split in selected_splits:
        #     block_start = split * blocks_per_split
        #     block_end = min(block_start + blocks_per_split, total_blocks)
        #     name = file.name + f"_{split:04d}"
        #     split_fname = str(file.parent.joinpath(name))
        #     obj = {
        #         "split_fname": split_fname,
        #         "block_start": block_start,
        #         "block_end": block_end,
        #         "split_index": split,
        #     }
        #     selected_blocks.append(obj)

        splits_modified = set()
        all_split_names = set()

        for v in range(split_count):
            name = file.name + f"_{v:04d}"
            split_fname = str(file.parent.joinpath(name))
            all_split_names.add(split_fname)

        no_of_blocks_to_modify = rng.randint(1, total_blocks)

        blocks_to_modify = rng.sample(range(total_blocks), no_of_blocks_to_modify)

        modified_splits = {}

        for block in blocks_to_modify:
            split = block // BLOCKS_IN_SPLIT
            # block_start = split * BLOCKS_IN_SPLIT
            # block_end = min(block_start + BLOCKS_IN_SPLIT, total_blocks)
            name = file.name + f"_{split:04d}"
            split_fname = str(file.parent.joinpath(name))

            splits_modified.add(split_fname)
            if split_fname not in modified_splits:
                modified_splits[split_fname] = [block]

            else:
                modified_splits[split_fname].append(block)

        matched_splits = list(all_split_names - splits_modified)

        return {
            "matched_splits": matched_splits,
            "modified_splits": modified_splits,
        }

    except Exception as e:
        print(f"Error processing file: {e}")
        return {}


def print_cbt_info_considered(files_info: dict):
    for fname, inf in files_info.items():
        for split_fname, blocks in inf["cbt"].items():
            print(
                f"In the file {Path(fname).name} split {Path(split_fname).name} {len(blocks)} blocks will be Modified"
            )
        if len(inf["matched"]) > 0:
            for split_fname in inf["matched"]:
                print(
                    f"In the file {Path(fname).name} split {Path(split_fname).name} will be matched."
                )
        else:
            print(f"In the file {Path(fname).name} no splits will be matched.")


def add_split_files_with_session(
    split_bkp_set_path: Path,
    sessionID: str,
    fl: Path,
    mode: str,
    original_files_to_split,
    v,
    isCBT: bool = False,
    cbt_splits=[],
):
    try:
        with fl.open(mode, encoding="utf-8") as f:
            if isCBT and v > 1:
                for split in cbt_splits:
                    path = split
                    if os.name == "nt":
                        path = str(toPosix(Path(split)))
                    f.writelines(path + ":" + sessionID + "\n")
            else:
                for item in split_bkp_set_path.rglob("*"):
                    if (
                        item.is_file()
                        and str(item) not in original_files_to_split
                        and not str(item).endswith(".json")
                        and not str(item).endswith("_config.xml")
                    ):  # Ensure we only add actual files, not subdirectories
                        fname = item.name
                        ori_fpath = split_bkp_set_path.joinpath(fname)
                        if os.name == "nt":
                            ori_fpath = toPosix(ori_fpath)
                        f.writelines(str(ori_fpath) + ":" + sessionID + "\n")
    except Exception as e:
        print(e)
        return


def split_create_config_xml(
    xml_path: Path, path: str, split_count: int, mdt: str, size: str
):
    with xml_path.open("w", encoding="utf-8") as f:
        "dummy"
        data = f"""
            <LargeFileBackupInfo>
            <FilePath>{path}</FilePath>
            <ChunksCount>{split_count}</ChunksCount>
            <Status>success</Status>
            <UploadTime>{mdt}</UploadTime>
            <TotalSize>{size}</TotalSize>
            </LargeFileBackupInfo>
            """
        f.write(data)


def split_restore_create_config_xml_file(
    fl: Path, split_bkp_set_path: Path, v: int = 1
):
    version = f"_IBVER{v:03d}"
    with fl.open("w", encoding="utf-8") as f:
        for file in split_bkp_set_path.rglob("*_config.xml"):
            if file.is_file():
                p = str(file)
                if os.name == "nt":
                    p = toPosix(file)
                f.writelines(p + version + "\n")


def split_restore_create_split_restore_file(
    fl: Path,
    split_meta: dict[str, Any],
    v: int = 1,
):
    # version = f"_IBVER{v:03d}"
    # with fl.open("w", encoding="utf-8") as f:
    #     for item in split_bkp_set_path.rglob("*"):
    #         if (
    #             item.is_file()
    #             and str(item) not in original_files
    #             and not str(item).endswith("_config.xml")
    #         ):
    #             f.writelines(str(item) + version + "\n")
    with fl.open("w", encoding="utf-8") as f:
        for ori_file, splits_info in split_meta.items():
            for split in splits_info["Splits_Info"]:
                split_no = int(split["SplitNumber"])
                split_suffix = f"_{split_no:04d}"
                version_no = int(split["VersionNumber"])
                v_suffix = f"_IBVER{version_no:03d}"
                split_path = ori_file + split_suffix + v_suffix
                f.writelines(split_path + "\n")


def add_split_files_metadata(
    split_metadata_fl: Path,
    original_split_files: dict[str, Any],
    split_count: int,
    sessionID: str,
):
    # Syntax: Config.xml file name:MDT$size$split_count$session_id
    # Example: /home/ARP/log.txt_config.xml:1524789612$1073765760$2$1590052109775811
    config_paths = []
    for path, value in original_split_files.items():
        filename = Path(path).name
        file_dir = Path(path).parent
        xml_path = file_dir.joinpath(filename + "_config.xml")
        posix_path = str(xml_path)
        if os.name == "nt":
            posix_path = toPosix(xml_path)
        config_path = (
            posix_path
            + ":"
            + str(value["mdt"])
            + "$"
            + str(value["size"])
            + "$"
            + str(split_count)
            + "$"
            + str(sessionID)
        )
        config_paths.append(config_path)
        split_create_config_xml(
            Path(xml_path), path, split_count, value["mdt"], value["size"]
        )

    with split_metadata_fl.open("w", encoding="utf-8") as f:
        for config in config_paths:
            f.writelines(config + "\n")


def create_sync_check_file_list(
    file_path: Path, fl: Path, split_count: int, mode: str = "w"
) -> dict[str, Any]:
    stats = file_path.stat()
    size = int(stats.st_size)
    mdt = int(stats.st_mtime)
    posix_file_path = file_path
    if os.name == "nt":
        posix_file_path = toPosix(file_path)
    with fl.open(mode, encoding="utf-8") as f:
        # Filename:MDT$size$split_count
        # /home/ARP/log.txt:1524789612$1073765830$3
        f.write(
            str(posix_file_path)
            + ":"
            + str(mdt)
            + "$"
            + str(size)
            + "$"
            + str(split_count)
            + "\n"
        )

    return {"size": size, "mdt": mdt}


def cbt_split_file(file_path: Path, split_size: int, fl_path: str, mode: str = "w"):
    if not file_path.exists():
        print(f"Error: File '{file_path}' not found.")
        return

    try:
        splits_info = []
        index = 0
        buffer_size = 1024 * 1024 * 1

        with file_path.open("rb") as f:
            while True:
                # chunk_data = f.read(split_size)
                # if not chunk_data:
                #     break
                name = file_path.name + f"_{index:04d}"
                out_file = file_path.parent.joinpath(name)

                bytes_written = 0

                with out_file.open("wb") as out:
                    while bytes_written < split_size:
                        to_read = min(buffer_size, split_size - bytes_written)
                        chunk = f.read(to_read)
                        if not chunk:
                            break
                        out.write(chunk)
                        bytes_written += len(chunk)

                if bytes_written == 0:
                    if out_file.exists():
                        out_file.unlink()
                    break

                chunk_sha = info(Path(out_file))
                chunk_stat = Path(out_file).stat()
                chunk_mdt = chunk_stat.st_mtime
                chunk_sz = chunk_stat.st_size

                obj = {
                    "name": str(out_file),
                    "mdt": chunk_mdt,
                    "size": chunk_sz,
                    "checksum": chunk_sha,
                }
                splits_info.append(obj)

                print(f"Created: {out_file} ({bytes_written}, bytes)")

                if bytes_written < split_size:
                    break
                index += 1

        stats = create_sync_check_file_list(
            Path(file_path), mode=mode, split_count=index, fl=Path(fl_path)
        )

        mdt = stats["mdt"]
        size = stats["size"]

        return {
            "path": str(file_path),
            "size": size,
            "mdt": mdt,
            "splits_info": splits_info,
        }

    except Exception as e:
        print(e)
        return None


def split_file(file_path: str, split_count: int, fl_path: str, mode: str = "w"):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return

    file_size = os.path.getsize(file_path)

    chunk_size = math.ceil(file_size / split_count)

    # Split filename and extension to inject the suffix properly
    file_dir, file_name = os.path.split(file_path)
    name_part, ext_part = os.path.splitext(file_name)

    # print(f"Splitting '{file_name}' ({file_size} bytes) into {split_count} pieces...")

    try:
        stats = create_sync_check_file_list(
            Path(file_path), mode=mode, split_count=split_count, fl=Path(fl_path)
        )
        mdt = stats["mdt"]
        size = stats["size"]
        # stats = Path(file_path).stat()
        # size = int(stats.st_size)
        # mdt = int(stats.st_mtime)
        # with Path(fl_path).open(mode, encoding="utf-8") as f:
        #     # Filename:MDT$size$split_count
        #     # /home/ARP/log.txt:1524789612$1073765830$3
        #     f.write(
        #         file_path
        #         + ":"
        #         + str(mdt)
        #         + "$"
        #         + str(size)
        #         + "$"
        #         + str(split_count)
        #         + "\n"
        #     )
        with open(file_path, "rb") as f_in:
            splits_info = []
            for i in range(split_count):
                # Generate the sequential suffix starting from 0000
                suffix = f"_{i:04d}"

                # Combine parts to form the new filename (e.g., document_0000.txt)
                output_filename = f"{name_part}{ext_part}{suffix}"
                output_path = os.path.join(file_dir, output_filename)

                # Read the precise slice of data
                chunk_data = f_in.read(chunk_size)

                # If there's no data left, stop (handles edge cases where file is empty or tiny)
                if not chunk_data:
                    break

                # Write data to the split file
                with open(output_path, "wb") as f_out:
                    f_out.write(chunk_data)
                chunk_sha = info(Path(output_path))
                chunk_stat = Path(output_path).stat()
                chunk_mdt = chunk_stat.st_mtime
                chunk_sz = chunk_stat.st_size
                obj = {
                    "name": output_path,
                    "mdt": chunk_mdt,
                    "size": chunk_sz,
                    "checksum": chunk_sha,
                }
                splits_info.append(obj)

                # print(f"Created: {output_filename}")
        # print("File splitting complete!")
        return {"path": file_path, "size": size, "mdt": mdt, "splits_info": splits_info}

    except Exception as e:
        print(e)
        return None


def update_version_info(
    file: Path,
    record: dict[str, Any],
    file_path: str,
    metadata: dict[str, Any],
    v: int,
    isRegularFile: int = 1,
) -> dict[str, Any]:
    uid = record["uid"]
    version_record = VersionRecord(
        uid=record["uid"],
        verid=record["vernum"],
        checksum=record["checksum"],
        backuptime=record["backuptime"],
        mdt=record["mdt"],
        parent_id=record["parent_id"],
        size=record["size"],
        isRegularFile=record["isRegularFile"],
    )
    del record["uid"]
    record["vernum"] = v
    record["checksum"] = sha256(file)
    record["mdt"] = metadata[file_path]["mdt"]
    record["size"] = metadata[file_path]["size"]
    record["backuptime"] = metadata[file_path]["ctime"]
    record["isRegularFile"] = isRegularFile
    return {"uid": uid, "record": record, "version": version_record}


class PathMetadata:
    def __init__(self):
        self.cache = {}

    def fix_windows_path(self, path):
        # Matches a leading backslash, a single drive letter, and another backslash (e.g., \F\...)
        # and converts it to a standard drive format (e.g., F:\...)
        fixed = re.sub(r"^\\([a-zA-Z])\\", r"\1:\\", str(path))

        # Ensure remaining slashes are normalized for Windows
        return os.path.normpath(fixed)

    def posix_to_windows(self, posix_path: str):
        # Handle Git Bash style paths like /c/Users -> C:\Users
        match = re.match(r"^/([a-zA-Z])/(.*)", posix_path)
        if match:
            drive, rest = match.groups()
            posix_path = f"{drive}:/{rest}"

        # Convert slashes and normalize to Windows format

        return os.path.normpath(posix_path)

    def fetch_hierarchy_properties(self, target_path: str) -> dict:
        """Fetches metadata for all hierarchical components of a given path

        from root to target, utilizing a cache, and normalizes paths
        to a strict POSIX format (removing drive colons, e.g., C:/ -> /c/).
        """
        path_obj = Path(target_path).resolve()

        # Generate hierarchical paths from root to target path
        all_paths = list(path_obj.parents)[::-1] + [path_obj]

        results = {}
        results_new = {}

        for p in all_paths:
            # Convert to strict POSIX path (removes colon and formats drive as /c/)
            path_str = self._to_pure_posix(p)
            meta = self._get_properties(p, path_str)
            results[path_str] = meta
            # Check if the path is already in the fetch_hierarchy_properties
            # if path_str in self.cache:
            #     results[path_str] = self.cache[path_str]
            # else:
            #     meta = self._get_properties(p, path_str)
            #     self.cache[path_str] = meta
            #     results[path_str] = meta
        for k, v in results.items():
            results_new[k.rstrip("/")] = v

        return results_new

    def _to_pure_posix(self, path_obj: Path) -> str:
        """Converts a Path object to a strict POSIX string,

        turning Windows drive letters like 'C:/' into '/c/'.
        """
        posix_str = path_obj.as_posix()

        # If the path has a drive (e.g., 'C:'), strip the colon and remap to POSIX root style
        if path_obj.drive:
            drive_letter = path_obj.drive[0]  # e.g., 'C'
            # Remove the drive portion from the string and prepend it with a slash
            relative_path = posix_str[len(path_obj.drive) :]
            posix_str = f"/{drive_letter.upper()}{relative_path}"

        return posix_str

    def _get_properties(self, path_obj: Path, posix_path_str: str) -> dict:
        """Helper method to extract properties of a single path object."""
        exists = path_obj.exists()
        is_file = path_obj.is_file() if exists else False
        is_dir = path_obj.is_dir() if exists else False

        size = None
        mtime = None
        ctime = None
        has_value = None

        if exists:
            try:
                stat = path_obj.stat()
                size = stat.st_size
                mtime = stat.st_mtime_ns
                ctime = stat.st_ctime_ns

                if is_file:
                    has_value = size > 0
            except (PermissionError, OSError) as e:
                return {"path": posix_path_str, "error": str(e), "exists": True}

        return {
            "path": posix_path_str,
            "exists": exists,
            "is_file": is_file,
            "is_dir": is_dir,
            "size": size,
            "mdt": mtime,
            "ctime": ctime,
            "has_value": has_value,
        }
