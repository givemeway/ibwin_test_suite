from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileTreeNode:
    name: str
    is_folder: bool
    parent: FileTreeNode | None = None
    children: list[FileTreeNode] = field(default_factory=list)

    # Database metadata
    uid: str | None = None
    mdt: int | None = None
    save_time: int | None = None
    label: str | None = None
    size: int | None = None
    vernum: int | None = None
    checksum: str | None = None
    backuptime: int | None = None
    device_id: str | None = None
    computer_id: str | None = None

    def split_path(self, path: str) -> list[str]:
        return [part for part in path.strip().split("/") if part]

    @property
    def path(self) -> str:
        if self.parent is None:
            return "/"

        parent_path = self.parent.path.rstrip("/")
        current_path = f"{parent_path}/{self.name}"

        return current_path + "/" if self.is_folder else current_path

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def add_child(self, child: FileTreeNode) -> FileTreeNode:
        child.parent = self
        self.children.append(child)
        return child

    def get_child(
        self,
        name: str,
        is_folder: bool | None = None,
    ) -> FileTreeNode | None:
        for child in self.children:
            if child.name == name and (
                is_folder is None or child.is_folder == is_folder
            ):
                return child

        return None

    @property
    def root(self) -> FileTreeNode:
        current = self

        while current.parent is not None:
            current = current.parent

        return current

    def find(self, path: str) -> FileTreeNode | None:
        parts = self.split_path(path)

        if not parts:
            return self if self.is_root else self.root

        current = self.root

        for part in parts:
            child = current.get_child(part)

            if child is None:
                return None

            current = child

        return current

    def remove_child(self, child: FileTreeNode) -> None:
        self.children.remove(child)
        child.parent = None

    @property
    def paths(self) -> set[str]:
        result = {self.path}

        for child in self.children:
            result.update(child.paths)

        return result

    def remove(self) -> None:
        if self.parent is not None:
            self.parent.remove_child(self)

    def sorted_children(self) -> list[FileTreeNode]:
        return sorted(
            self.children,
            key=lambda node: (
                not node.is_folder,
                node.name.casefold(),
            ),
        )


@dataclass
class FileTreeNodeNew:
    name: str
    is_folder: bool
    parent: FileTreeNodeNew | None = None
    children: list[FileTreeNodeNew] = field(default_factory=list)

    def split_path(self, path: str) -> list[str]:
        return [part for part in path.strip().split("/") if part]

    @property
    def path(self) -> str:
        """Return the full path of this node."""
        if self.parent is None:
            return "/"

        parent_path = self.parent.path.rstrip("/")
        current_path = f"{parent_path}/{self.name}"

        return current_path + "/" if self.is_folder else current_path

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def add_child(self, child: FileTreeNodeNew) -> FileTreeNodeNew:
        """Add a child node and assign this node as its parent."""
        child.parent = self
        self.children.append(child)
        return child

    def get_child(
        self,
        name: str,
        is_folder: bool | None = None,
    ) -> FileTreeNodeNew | None:
        """Return a direct child by name."""
        for child in self.children:
            if child.name == name and (
                is_folder is None or child.is_folder == is_folder
            ):
                return child

        return None

    def find(self, path: str) -> FileTreeNodeNew | None:
        """Find a node by its absolute path."""
        parts = self.split_path(path)

        if not parts:
            return self if self.is_root else self.root

        current = self.root

        for index, part in enumerate(parts):
            child = current.get_child(part)

            if child is None:
                return None

            current = child

        return current

    @property
    def root(self) -> FileTreeNodeNew:
        """Return the root node of this tree."""
        current = self

        while current.parent is not None:
            current = current.parent

        return current

    def remove_child(self, child: FileTreeNodeNew) -> None:
        """Remove a direct child from this node."""
        self.children.remove(child)
        child.parent = None

    @property
    def paths(self) -> set[str]:
        result = {self.path}
        for child in self.children:
            result.update(child.paths)

        return result

    def remove(self) -> None:
        """Remove this node from its parent."""
        if self.parent is not None:
            self.parent.remove_child(self)

    def sorted_children(self) -> list[FileTreeNodeNew]:
        """Return folders first, then files, sorted by name."""
        return sorted(
            self.children,
            key=lambda node: (
                not node.is_folder,
                node.name.casefold(),
            ),
        )


@dataclass
class Build:
    name: str
    executable: str
    release: str
    release_date: str
    selection: str
    osname: str = "nt"
    hostname: str = "Sandeep-Laptop"
    working_dir: str = r"C:\Program Files (x86)\IDriveWindows\cmd_sdutil"
    isTestBed: int = 0
    oppositeBuild: str = ""


@dataclass
class TestMachine:
    osname: str = "nt"
    hostname: str = "Sandeep-laptop"
    testBed: int = 0


@dataclass
class Environment:
    username: str = "sanity03"
    password: str = "1234"
    server: str = "localhost"
    device_id: str = ""
    server_root: str = ""
    private_key: str = "1234"
    remote_root: str = "home/"
    computer_name: str = ""
    port: int = 0
    workspace: Path = Path("./idevsutil_qa")
    timeout: int = 3600
    is_test_machine: int = 0
    use_utf8_encryption: int = 0
    dedup: int = 1
    syncDedup: int = 0
    fileListPath: str = "/home/sandeep/filelist.txt"
    linkFileListPath: str = "/home/sandeep/filelist_link.txt"
    userRoot: str = "/home/opt/data"


@dataclass
class Result:
    test_id: str
    description: str
    status: str
    expected: str
    actual: str
    build: str
    details: str = ""


@dataclass
class ChunkInfo:
    name: str
    checksum: str
    mdt: str
    size: str
