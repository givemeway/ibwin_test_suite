from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Iterable, Mapping
from .models import FileTreeNode
import sqlite3
import uuid

# ---------------------------------------------------------------------------
# Database model
# ---------------------------------------------------------------------------


IBTABLE_COLUMNS = (
    "uid",
    "parent_id",
    "is_folder",
    "name",
    "mdt",
    "save_time",
    "label",
    "size",
    "vernum",
    "checksum",
    "backuptime",
    "device_id",
    "computer_id",
    "isRegularFile",
)

TRASH_COLUMNS = IBTABLE_COLUMNS


VERSION_COLUMNS = (
    "uid",
    "verid",
    "checksum",
    "backuptime",
    "mdt",
    "parent_id",
    "size",
    "isRegularFile",
)


@dataclass(slots=True)
class IBTableRecord:
    uid: str
    parent_id: str | None
    is_folder: bool
    name: str
    mdt: int | None = None
    save_time: int | None = None
    label: str | None = None
    size: int | None = None
    vernum: int | None = None
    checksum: str | None = None
    backuptime: int | None = None
    device_id: str | None = None
    computer_id: str | None = None
    isRegularFile: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "IBTableRecord":
        return cls(
            uid=row["uid"],
            parent_id=row["parent_id"],
            is_folder=bool(row["is_folder"]),
            name=row["name"],
            mdt=row["mdt"],
            save_time=row["save_time"],
            label=row["label"],
            size=row["size"],
            vernum=row["vernum"],
            checksum=row["checksum"],
            backuptime=row["backuptime"],
            device_id=row["device_id"],
            computer_id=row["computer_id"],
            isRegularFile=row["isRegularFile"],
        )

    def to_db_values(self) -> tuple[Any, ...]:
        return (
            self.uid,
            self.parent_id,
            int(self.is_folder),
            self.name,
            self.mdt,
            self.save_time,
            self.label,
            self.size,
            self.vernum,
            self.checksum,
            self.backuptime,
            self.device_id,
            self.computer_id,
            self.isRegularFile,
        )


@dataclass(slots=True)
class TrashRecord:
    uid: str
    parent_id: str | None
    is_folder: bool
    name: str
    mdt: int | None = None
    save_time: int | None = None
    label: str | None = None
    size: int | None = None
    vernum: int | None = None
    checksum: str | None = None
    backuptime: int | None = None
    device_id: str | None = None
    computer_id: str | None = None
    isRegularFile: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "TrashRecord":
        return cls(
            uid=row["uid"],
            parent_id=row["parent_id"],
            is_folder=bool(row["is_folder"]),
            name=row["name"],
            mdt=row["mdt"],
            save_time=row["save_time"],
            label=row["label"],
            size=row["size"],
            vernum=row["vernum"],
            checksum=row["checksum"],
            backuptime=row["backuptime"],
            device_id=row["device_id"],
            computer_id=row["computer_id"],
            isRegularFile=row["isRegularFile"],
        )

    def to_db_values(self) -> tuple[Any, ...]:
        return (
            self.uid,
            self.parent_id,
            int(self.is_folder),
            self.name,
            self.mdt,
            self.save_time,
            self.label,
            self.size,
            self.vernum,
            self.checksum,
            self.backuptime,
            self.device_id,
            self.computer_id,
            self.isRegularFile,
        )


@dataclass(slots=True)
class VersionRecord:
    uid: str
    verid: int
    checksum: str | None = None
    backuptime: int | None = None
    mdt: int | None = None
    parent_id: str | None = None
    size: int | None = None
    isRegularFile: bool = True

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "VersionRecord":
        return cls(
            uid=row["uid"],
            verid=row["verid"],
            checksum=row["checksum"],
            backuptime=row["backuptime"],
            mdt=row["mdt"],
            parent_id=row["parent_id"],
            size=row["size"],
            isRegularFile=row["isRegularFile"],
        )

    def to_db_values(self) -> tuple[Any, ...]:
        return (
            self.uid,
            self.verid,
            self.checksum,
            self.backuptime,
            self.mdt,
            self.parent_id,
            self.size,
            self.isRegularFile,
        )


class FileTreeDatabase:
    """
    The database stores:
        ibtable  - current file tree
        versions - historical file versions
        trash    - deleted nodes

    uid unique identifier of a file or folder.
    parent_id points to another uid in ibtable.
    """

    def __init__(
        self,
        database_path: str = "filetree.db",
        *,
        timeout: float = 5.0,
    ) -> None:
        self.conn = sqlite3.connect(
            database_path,
            timeout=timeout,
        )

        self.conn.row_factory = sqlite3.Row

        # These must be configured on each new SQLite connection.
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA journal_mode = WAL")

        self.create_tables()

    @property
    def get_conn(self) -> sqlite3.Connection | None:
        return self.conn

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> FileTreeDatabase:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()

        self.close()

    # -----------------------------------------------------------------------
    # Schema
    # -----------------------------------------------------------------------

    def create_tables(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS ibtable (
                    uid         TEXT PRIMARY KEY,
                    parent_id   TEXT NULL,
                    is_folder   INTEGER NOT NULL CHECK (is_folder IN (0, 1)),
                    name        TEXT NOT NULL,
                    mdt         INTEGER NULL,
                    save_time   INTEGER NULL,
                    label       TEXT NULL,
                    size        INTEGER NULL CHECK (size >= 0),
                    vernum      INTEGER NULL CHECK (vernum >= 0),
                    checksum    TEXT NULL,
                    backuptime  INTEGER NULL,
                    device_id   TEXT NULL,
                    computer_id TEXT NULL,
                    isRegularFile INTEGER NOT NULL CHECK (isRegularFile IN(0,1)),

                    UNIQUE (parent_id, name, is_folder,device_id,computer_id,isRegularFile),

                    FOREIGN KEY (parent_id)
                        REFERENCES ibtable(uid)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS versions (
                    uid         TEXT NOT NULL,
                    verid       INTEGER NOT NULL CHECK (verid >= 0),
                    checksum    TEXT NULL,
                    backuptime  INTEGER NULL,
                    mdt         INTEGER NULL,
                    parent_id   TEXT NULL,
                    size        INTEGER NULL CHECK (size >= 0),
                    isRegularFile INTEGER NOT NULL CHECK (isRegularFile IN(0,1)),

                    PRIMARY KEY (uid, verid),

                    FOREIGN KEY (uid)
                        REFERENCES ibtable(uid)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS trash (
                    uid         TEXT PRIMARY KEY,
                    parent_id   TEXT NULL,
                    parent_id_ibtable TEXT NULL,
                    is_folder   INTEGER NOT NULL CHECK (is_folder IN (0, 1)),
                    name        TEXT NOT NULL,
                    mdt         INTEGER NULL,
                    save_time   INTEGER NULL,
                    label       TEXT NULL,
                    size        INTEGER NULL CHECK (size >= 0),
                    vernum      INTEGER NULL CHECK (vernum >= 0),
                    checksum    TEXT NULL,
                    backuptime  INTEGER NULL,
                    device_id   TEXT NULL,
                    computer_id TEXT NULL,
                    isRegularFile INTEGER NOT NULL CHECK (isRegularFile IN(0,1)),


                    UNIQUE (parent_id, name, is_folder,device_id,computer_id,isRegularFile),

                    FOREIGN KEY (parent_id)
                        REFERENCES trash(uid)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_ibtable_parent_id
                    ON ibtable(parent_id);

                CREATE INDEX IF NOT EXISTS idx_ibtable_name
                    ON ibtable(name);

                CREATE INDEX IF NOT EXISTS idx_versions_uid
                    ON versions(uid);

                CREATE INDEX IF NOT EXISTS idx_versions_backuptime
                    ON versions(backuptime);

                CREATE INDEX IF NOT EXISTS idx_trash_parent_id
                    ON trash(parent_id);

                CREATE INDEX IF NOT EXISTS idx_trash_backuptime
                    ON trash(backuptime);
                """
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _new_uid() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _now() -> int:
        return int(datetime.now(timezone.utc).timestamp())

    @staticmethod
    def _bool_to_int(value: bool) -> int:
        return 1 if value else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _validate_uid(uid: str) -> None:
        if not uid:
            raise ValueError("uid must not be empty")

    def _node_to_ibtable_values(
        self,
        node: FileTreeNode,
        *,
        parent_id: str | None = None,
    ) -> tuple[Any, ...]:
        uid = node.uid or self._new_uid()
        node.uid = uid

        if node.save_time is None:
            node.save_time = self._now()

        return (
            uid,
            parent_id,
            self._bool_to_int(node.is_folder),
            node.name,
            node.mdt,
            node.save_time,
            node.label,
            node.size,
            node.vernum,
            node.checksum,
            node.backuptime,
            node.device_id,
            node.computer_id,
        )

    def _row_to_node(self, row: sqlite3.Row) -> FileTreeNode:
        return FileTreeNode(
            name=row["name"],
            is_folder=bool(row["is_folder"]),
            uid=row["uid"],
            mdt=row["mdt"],
            save_time=row["save_time"],
            label=row["label"],
            size=row["size"],
            vernum=row["vernum"],
            checksum=row["checksum"],
            backuptime=row["backuptime"],
            device_id=row["device_id"],
            computer_id=row["computer_id"],
        )

    # -----------------------------------------------------------------------
    # Generic reads
    # -----------------------------------------------------------------------

    def get_all(
        self,
        table: str | list = "ibtable",
        order_by: str | None = None,
        sort: str | None = None,
        limit: int | None = None,
        is_folder: int = 0,
        isRegularFile: int = 1,
        findAll: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[sqlite3.Row] = []
        if isinstance(table, str):
            if table not in {"ibtable", "trash", "version"}:
                raise ValueError("Table must be 'ibtable' or 'trash' or 'version'")
            query = ""
            if order_by and sort and limit and not bool(is_folder):
                query = f"SELECT * FROM {table} WHERE is_folder = {is_folder} AND isRegularFile = {isRegularFile} ORDER BY {order_by} {sort} limit {limit}"
            else:
                if not findAll:
                    query = (
                        f"SELECT * FROM {table} WHERE isRegularFile = {isRegularFile}"
                    )
                else:
                    query = f"SELECT * FROM {table};"

            rows = self.conn.execute(query).fetchall()

        elif isinstance(table, list):
            for t in table:
                if t not in {"ibtable", "trash", "version"}:
                    raise ValueError("Table must be 'ibtable' or 'trash' or 'version'")
                query = f"SELECT * FROM {table}"
                if order_by and sort and limit:
                    query += f" WHERE is_folder = {is_folder} AND isRegularFile = {isRegularFile} ORDER BY {order_by} {sort} limit {limit}"

                table_rows = self.conn.execute(query).fetchall()
                rows.extend(table_rows)

        return [self._row_to_dict(row) for row in rows]

    def get_path_by_uid(
        self,
        uid: str,
        separator: str = "/",
        table: str = "ibtable",
        parent_id_ibtable: str | None = None,
    ) -> str | None:
        if not uid:
            raise ValueError("uid must not be empty")

        if not separator:
            raise ValueError("separator must not be empty")

        parts: list[str] = []
        current_uid: str | None = uid
        is_folder = False
        path: str | None = None

        if table == "trash" and parent_id_ibtable:
            current_node: str | None = None
            while current_uid is not None:
                row = self.conn.execute(
                    """
                    SELECT
                        uid,
                        parent_id,
                        name,
                        is_folder,
                        parent_id_ibtable
                    FROM trash
                    WHERE uid = ?
                    """,
                    (current_uid,),
                ).fetchone()

                if row is None:
                    return None

                parts.append(row["name"])
                is_folder = bool(row["is_folder"])
                current_uid = row["parent_id"]
                current_node = row["parent_id_ibtable"]

            path = separator + separator.join(reversed(parts))
            parts = []
            current_uid = current_node

        effective_table = f"{'ibtable' if table == 'trash' else table}"
        while current_uid is not None:
            row = self.conn.execute(
                f"""
                SELECT
                    uid,
                    parent_id,
                    name,
                    is_folder
                FROM {effective_table}
                WHERE uid = ?
                """,
                (current_uid,),
            ).fetchone()

            if row is None:
                return None

            parts.append(row["name"])
            is_folder = bool(row["is_folder"])
            current_uid = row["parent_id"]

        if table == "trash" and parent_id_ibtable:
            trash_path = separator + separator.join(reversed(parts))
            path = trash_path + path
        else:
            path = separator + separator.join(reversed(parts))

        if is_folder:
            path += separator

        return path

    def get(
        self,
        uid: str,
        *,
        table: str = "ibtable",
    ) -> dict[str, Any] | None:
        if table not in {"ibtable", "trash"}:
            raise ValueError("table must be 'ibtable' or 'trash'")

        self._validate_uid(uid)

        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE uid = ?",
            (uid,),
        ).fetchone()

        return self._row_to_dict(row)

    def get_node(self, uid: str) -> FileTreeNode | None:
        row = self.conn.execute(
            "SELECT * FROM ibtable WHERE uid = ?",
            (uid,),
        ).fetchone()

        return self._row_to_node(row) if row else None

    def get_by_path_new(
        self,
        path: str,
        isRegularFile: int | None = None,
        computer_id: str | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            return None

        filters = ""
        extra: list[Any] = []
        if isRegularFile is not None:
            filters += " AND isRegularFile = ?"
            extra.append(isRegularFile)
        if computer_id is not None:
            filters += " AND computer_id = ?"
            extra.append(computer_id)
        if device_id is not None:
            filters += " AND device_id = ?"
            extra.append(device_id)

        sql = f"""
            SELECT *
            FROM ibtable
            WHERE parent_id IS ?
            AND name = ?
            {filters}
        """

        parent_id: str | None = None
        row: sqlite3.Row | None = None

        for part in parts:
            row = self.conn.execute(sql, (parent_id, part, *extra)).fetchone()
            if row is None:
                return None
            parent_id = row["uid"]

        return self._row_to_dict(row)

    def get_by_path(self, path: str) -> dict[str, Any] | None:
        """
        Resolve an absolute path such as:

            /documents/report.pdf

        The root row is not required. A root-level item has parent_id NULL.
        """
        parts = [part for part in path.strip("/").split("/") if part]

        if not parts:
            return None

        parent_id: str | None = None
        row: sqlite3.Row | None = None

        # parts = [home,opt,sandeep,qa-9-2026,sandeep.txt]
        for part in parts:
            row = self.conn.execute(
                """
                SELECT *
                FROM ibtable
                WHERE parent_id IS ?
                  AND name = ?
                """,
                (parent_id, part),
            ).fetchone()

            if row is None:
                return None

            parent_id = row["uid"]

        return self._row_to_dict(row)

    def get_record(self, uid: str) -> IBTableRecord | None:
        self._validate_uid(uid)

        row = self.conn.execute(
            """
            SELECT *
            FROM ibtable
            WHERE uid = ?
            """,
            (uid,),
        ).fetchone()

        return IBTableRecord.from_row(row) if row else None

    def get_trash_record(self, uid: str) -> TrashRecord | None:
        self._validate_uid(uid)

        row = self.conn.execute(
            """
            SELECT *
            FROM trash
            WHERE uid = ?
            """,
            (uid,),
        ).fetchone()

        return TrashRecord.from_row(row) if row else None

    def get_version_record(
        self,
        uid: str,
        verid: int,
    ) -> VersionRecord | None:
        self._validate_uid(uid)

        row = self.conn.execute(
            """
            SELECT *
            FROM versions
            WHERE uid = ?
            AND verid = ?
            """,
            (uid, verid),
        ).fetchone()

        return VersionRecord.from_row(row) if row else None

    def list_record_children(
        self,
        parent_id: str | None = None,
    ) -> list[IBTableRecord]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM ibtable
            WHERE parent_id IS ?
            ORDER BY
                is_folder DESC,
                name COLLATE NOCASE ASC
            """,
            (parent_id,),
        ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def list_trash_records(self) -> list[TrashRecord]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM trash
            ORDER BY
                save_time DESC,
                name COLLATE NOCASE ASC
            """
        ).fetchall()

        return [TrashRecord.from_row(row) for row in rows]

    def list_version_records(self, uid: str) -> list[VersionRecord]:
        self._validate_uid(uid)

        rows = self.conn.execute(
            """
            SELECT *
            FROM versions
            WHERE uid = ?
            ORDER BY verid DESC
            """,
            (uid,),
        ).fetchall()

        return [VersionRecord.from_row(row) for row in rows]

    def list_children(
        self,
        parent_id: str | None = None,
        *,
        folders_first: bool = True,
    ) -> list[dict[str, Any]]:
        order_by = (
            "is_folder DESC, name COLLATE NOCASE ASC"
            if folders_first
            else "name COLLATE NOCASE ASC"
        )

        rows = self.conn.execute(
            f"""
            SELECT *
            FROM ibtable
            WHERE parent_id IS ?
            ORDER BY {order_by}
            """,
            (parent_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def list_versions(self, uid: str) -> list[dict[str, Any]]:
        self._validate_uid(uid)

        rows = self.conn.execute(
            """
            SELECT *
            FROM versions
            WHERE uid = ?
            ORDER BY verid DESC
            """,
            (uid,),
        ).fetchall()

        return [dict(row) for row in rows]

    def list_trash(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM trash
            ORDER BY save_time DESC, name COLLATE NOCASE ASC
            """
        ).fetchall()

        return [dict(row) for row in rows]

    # -----------------------------------------------------------------------
    # Insert
    # -----------------------------------------------------------------------

    def insert_path(
        self,
        path: str,
        pathProperties: dict[str, Any],
        device_id: str | None = None,
        computer_id: str | None = None,
        separator: str = "/",
        isRegularFile: int = 1,
    ) -> str:
        """
        Create all missing components of a path in ibtable.

        Example:

            uid = db.insert_path(
                "/home/opt/SANDEEP/filelist.txt",
                "/",
            )

        This creates or reuses:

            home
            opt
            SANDEEP
            filelist.txt

        The first component gets parent_id=NULL.
        Each following component gets the UID of the previous component
        as its parent_id.

        Returns:
            UID of the final path component.
        """

        if not path or not path.strip():
            raise ValueError("path must not be empty")

        if not separator:
            raise ValueError("separator must not be empty")

        parts = [
            part.strip()
            for part in path.strip(separator).split(separator)
            if part.strip()
        ]

        if not parts:
            raise ValueError(f"invalid path: {path!r}")

        parent_id: str | None = None
        current_uid: str | None = None
        current_path = "/"
        computer_id = computer_id
        device_id = device_id

        with self.conn:
            for index, name in enumerate(parts):
                is_final = index == len(parts) - 1
                is_folder = not is_final

                row = self._find_ibtable_child(
                    parent_id=parent_id,
                    name=name,
                    is_folder=is_folder,
                    computer_id=computer_id,
                    device_id=device_id,
                    isRegularFile=isRegularFile,
                )
                size = 0
                mdt = 0
                backuptime = time.time_ns()
                checksum = None
                vernum = 0

                if row is not None:
                    current_uid = row["uid"]
                    current_path += name + "/"

                else:
                    current_uid = str(uuid.uuid4())

                    current_path += name + "/"

                    stripped_current_path = current_path.rstrip("/")

                    if stripped_current_path in pathProperties:
                        props = pathProperties[stripped_current_path]
                        try:
                            (
                                size,
                                mdt,
                                checksum,
                                vernum,
                            ) = (
                                props["size"],
                                props["mdt"],
                                props["checksum"],
                                props["vernum"],
                            )
                        except:
                            pass

                    self.conn.execute(
                        """
                        INSERT INTO ibtable (
                            uid,
                            parent_id,
                            is_folder,
                            name,
                            mdt,
                            backuptime,
                            size,
                            checksum,
                            vernum,
                            computer_id,
                            device_id,
                            isRegularFile
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            current_uid,
                            parent_id,
                            int(is_folder),
                            name,
                            mdt,
                            backuptime,
                            size,
                            checksum,
                            vernum,
                            computer_id,
                            device_id,
                            isRegularFile,
                        ),
                    )

                parent_id = current_uid
        return current_uid

    def insert_trash_record(self, record: TrashRecord) -> str:
        """
        Insert a row directly into trash.
        """
        self._validate_uid(record.uid)

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO trash (
                    uid,
                    parent_id,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id,
                    isRegularFile
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                record.to_db_values(),
            )

        return record.uid

    def insert_version_record(self, record: VersionRecord, v: int = 1) -> None:
        self._validate_uid(record.uid)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO versions (
                    uid,
                    verid,
                    checksum,
                    backuptime,
                    mdt,
                    parent_id,
                    size,
                    isRegularFile
                )
                VALUES (?, ?, ?, ?, ?, ?, ?,?)
                """,
                record.to_db_values(),
            )

    def insert(
        self,
        node: FileTreeNode,
        *,
        parent_id: str | None = None,
    ) -> str:
        """
        Insert one node into ibtable.

        The parent must already exist when parent_id is not NULL.
        """
        values = self._node_to_ibtable_values(
            node,
            parent_id=parent_id,
        )

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ibtable (
                    uid,
                    parent_id,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )

        return node.uid  # type: ignore[return-value]

    def insert_many(
        self,
        nodes: Iterable[tuple[FileTreeNode, str | None]],
    ) -> None:
        rows = [
            self._node_to_ibtable_values(node, parent_id=parent_id)
            for node, parent_id in nodes
        ]

        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO ibtable (
                    uid,
                    parent_id,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_version(
        self,
        version: VersionRecord,
    ) -> None:
        self._validate_uid(version.uid)

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO versions (
                    uid,
                    verid,
                    checksum,
                    backuptime,
                    mdt,
                    parent_id,
                    size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.uid,
                    version.verid,
                    version.checksum,
                    version.backuptime,
                    version.mdt,
                    version.parent_id,
                    version.size,
                ),
            )

    # -----------------------------------------------------------------------
    # Update
    # -----------------------------------------------------------------------

    def update(
        self,
        uid: str,
        values: Mapping[str, Any],
    ) -> None:
        """
        Update selected columns in ibtable.

        Example:

            db.update(
                uid,
                {
                    "size": 1024,
                    "checksum": "abc123",
                    "mdt": 1720000000,
                },
            )
        """
        self._validate_uid(uid)

        allowed_columns = {
            "parent_id",
            "is_folder",
            "name",
            "mdt",
            "save_time",
            "label",
            "size",
            "vernum",
            "checksum",
            "backuptime",
            "device_id",
            "computer_id",
            "isRegularFile",
        }

        if not values:
            return

        unknown_columns = set(values) - allowed_columns

        if unknown_columns:
            raise ValueError(f"Unknown or immutable columns: {sorted(unknown_columns)}")

        assignments = ", ".join(f"{column} = ?" for column in values)

        parameters = tuple(values[column] for column in values) + (uid,)

        with self.conn:
            cursor = self.conn.execute(
                f"""
                UPDATE ibtable
                SET {assignments}
                WHERE uid = ?
                """,
                parameters,
            )
            if cursor.rowcount == 0:
                raise KeyError(f"No ibtable node exists with uid={uid!r}")

    def update_version(
        self,
        uid: str,
        verid: int,
        values: Mapping[str, Any],
    ) -> None:
        self._validate_uid(uid)

        allowed_columns = {
            "checksum",
            "backuptime",
            "mdt",
            "parent_id",
            "size",
        }

        unknown_columns = set(values) - allowed_columns

        if unknown_columns:
            raise ValueError(
                f"Unknown or immutable version columns: {sorted(unknown_columns)}"
            )

        if not values:
            return

        assignments = ", ".join(f"{column} = ?" for column in values)

        parameters = tuple(values[column] for column in values)
        parameters += (uid, verid)

        with self.conn:
            cursor = self.conn.execute(
                f"""
                UPDATE versions
                SET {assignments}
                WHERE uid = ?
                  AND verid = ?
                """,
                parameters,
            )

            if cursor.rowcount == 0:
                raise KeyError(f"No version exists for uid={uid!r}, verid={verid}")

    # -----------------------------------------------------------------------
    # Upsert
    # -----------------------------------------------------------------------

    def upsert(
        self,
        node: FileTreeNode,
        *,
        parent_id: str | None = None,
    ) -> str:
        """
        Insert or update an ibtable row based on uid.

        The uid must remain stable for the same logical file/folder.
        """
        values = self._node_to_ibtable_values(
            node,
            parent_id=parent_id,
        )

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ibtable (
                    uid,
                    parent_id,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    is_folder = excluded.is_folder,
                    name = excluded.name,
                    mdt = excluded.mdt,
                    save_time = excluded.save_time,
                    label = excluded.label,
                    size = excluded.size,
                    vernum = excluded.vernum,
                    checksum = excluded.checksum,
                    backuptime = excluded.backuptime,
                    device_id = excluded.device_id,
                    computer_id = excluded.computer_id
                """,
                values,
            )

        return node.uid  # type: ignore[return-value]

    def upsert_version(
        self,
        version: VersionRecord,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO versions (
                    uid,
                    verid,
                    checksum,
                    backuptime,
                    mdt,
                    parent_id,
                    size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid, verid) DO UPDATE SET
                    checksum = excluded.checksum,
                    backuptime = excluded.backuptime,
                    mdt = excluded.mdt,
                    parent_id = excluded.parent_id,
                    size = excluded.size
                """,
                (
                    version.uid,
                    version.verid,
                    version.checksum,
                    version.backuptime,
                    version.mdt,
                    version.parent_id,
                    version.size,
                ),
            )

    # -----------------------------------------------------------------------
    # Delete
    # -----------------------------------------------------------------------

    def delete(
        self,
        uid: str,
        *,
        move_to_trash: bool = False,
    ) -> None:
        """
        Delete one node and its descendants.

        Because ibtable.parent_id uses ON DELETE CASCADE, deleting a folder
        deletes its complete subtree.

        If move_to_trash is True, all rows in the subtree are copied into
        trash before deleting them from ibtable.
        """
        self._validate_uid(uid)
        isCopied: bool = False
        with self.conn:
            if move_to_trash:
                isCopied = self._copy_subtree_to_trash(uid)

            if isCopied:
                cursor = self.conn.execute(
                    "DELETE FROM ibtable WHERE uid = ?",
                    (uid,),
                )

                if cursor.rowcount == 0:
                    raise KeyError(f"No ibtable node exists with uid={uid!r}")

    def delete_version(
        self,
        uid: str,
        verid: int,
    ) -> None:
        self._validate_uid(uid)

        with self.conn:
            cursor = self.conn.execute(
                """
                DELETE FROM versions
                WHERE uid = ?
                  AND verid = ?
                """,
                (uid, verid),
            )

            if cursor.rowcount == 0:
                raise KeyError(f"No version exists for uid={uid!r}, verid={verid}")

    def delete_from_trash(self, uid: str) -> None:
        self._validate_uid(uid)

        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM trash WHERE uid = ?",
                (uid,),
            )

            if cursor.rowcount == 0:
                raise KeyError(f"No trash row exists with uid={uid!r}")

    def restore_from_trash(
        self,
        uid: str,
        *,
        parent_id: str | None = None,
    ) -> str:
        """
        Restore one trash row into ibtable.

        This restores only the selected row. For a complete folder subtree,
        restore the rows in parent-before-child order.
        """
        self._validate_uid(uid)

        row = self.conn.execute(
            "SELECT * FROM trash WHERE uid = ?",
            (uid,),
        ).fetchone()

        if row is None:
            raise KeyError(f"No trash row exists with uid={uid!r}")

        restored_parent_id = parent_id if parent_id is not None else row["parent_id"]

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ibtable (
                    uid,
                    parent_id,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["uid"],
                    restored_parent_id,
                    row["is_folder"],
                    row["name"],
                    row["mdt"],
                    row["save_time"],
                    row["label"],
                    row["size"],
                    row["vernum"],
                    row["checksum"],
                    row["backuptime"],
                    row["device_id"],
                    row["computer_id"],
                ),
            )

            self.conn.execute(
                "DELETE FROM trash WHERE uid = ?",
                (uid,),
            )

        return uid

    # -----------------------------------------------------------------------
    # Tree insertion and loading
    # -----------------------------------------------------------------------

    def insert_tree(
        self,
        root: FileTreeNode,
        *,
        parent_id: str | None = None,
    ) -> str:
        """
        Insert an entire in-memory tree.

        The supplied root node itself is inserted, followed by its children.
        """
        with self.conn:
            return self._insert_tree_recursive(
                root,
                parent_id=parent_id,
            )

    def _insert_tree_recursive(
        self,
        node: FileTreeNode,
        *,
        parent_id: str | None,
    ) -> str:
        values = self._node_to_ibtable_values(
            node,
            parent_id=parent_id,
        )

        self.conn.execute(
            """
            INSERT INTO ibtable (
                uid,
                parent_id,
                is_folder,
                name,
                mdt,
                save_time,
                label,
                size,
                vernum,
                checksum,
                backuptime,
                device_id,
                computer_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

        for child in node.children:
            self._insert_tree_recursive(
                child,
                parent_id=node.uid,
            )

        return node.uid  # type: ignore[return-value]

    def load_tree(self) -> list[FileTreeNode]:
        """
        Load all database rows into a list of root nodes.

        The database may contain multiple root-level nodes because parent_id
        is NULL for root-level entries.
        """
        rows = self.conn.execute(
            """
            SELECT *
            FROM ibtable
            ORDER BY
                parent_id IS NOT NULL,
                parent_id,
                is_folder DESC,
                name COLLATE NOCASE
            """
        ).fetchall()

        nodes: dict[str, FileTreeNode] = {}
        roots: list[FileTreeNode] = []

        for row in rows:
            node = self._row_to_node(row)
            nodes[node.uid] = node  # type: ignore[index]

            parent_id = row["parent_id"]

            if parent_id is None:
                roots.append(node)
            else:
                parent = nodes.get(parent_id)

                if parent is None:
                    raise RuntimeError(
                        f"Invalid tree order or missing parent: {parent_id}"
                    )

                parent.add_child(node)

        return roots

    # -----------------------------------------------------------------------
    # Trash helpers
    # -----------------------------------------------------------------------

    def _copy_subtree_to_trash(self, uid: str) -> bool:
        """
        Copy uid and every descendant into trash using a recursive CTE.
        """
        try:
            self.conn.execute(
                """
                INSERT INTO trash (
                    uid,
                    parent_id,
                    parent_id_ibtable,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id,
                    isRegularFile
                )
                WITH RECURSIVE subtree AS (
                    SELECT *, parent_id AS orig_parent_id, 1 AS is_root
                    FROM ibtable
                    WHERE uid = :uid

                    UNION ALL

                    SELECT child.*, child.parent_id AS orig_parent_id, 0 AS is_root
                    FROM ibtable AS child
                    INNER JOIN subtree AS parent
                        ON child.parent_id = parent.uid
                )
                SELECT
                    uid,
                    CASE 
                        WHEN is_root = 1 THEN NULL 
                        ELSE parent_id 
                    END AS parent_id,
                    orig_parent_id AS parent_id_ibtable,
                    is_folder,
                    name,
                    mdt,
                    save_time,
                    label,
                    size,
                    vernum,
                    checksum,
                    backuptime,
                    device_id,
                    computer_id,
                    isRegularFile
                FROM subtree
                WHERE true 
                ON CONFLICT(uid) DO UPDATE SET
                    parent_id = excluded.parent_id,
                    parent_id_ibtable = excluded.parent_id_ibtable,
                    is_folder = excluded.is_folder,
                    name = excluded.name,
                    mdt = excluded.mdt,
                    save_time = excluded.save_time,
                    label = excluded.label,
                    size = excluded.size,
                    vernum = excluded.vernum,
                    checksum = excluded.checksum,
                    backuptime = excluded.backuptime,
                    device_id = excluded.device_id,
                    computer_id = excluded.computer_id,
                    isRegularFile = excluded.isRegularFile;
                """,
                {"uid": uid},
            )
            return True
        except Exception as e:
            print("Error Copying into Trash: ", e)
            return False

    def _find_ibtable_child(
        self,
        *,
        parent_id: str | None,
        name: str,
        is_folder: bool,
        device_id: str | None,
        computer_id: str | None,
        isRegularFile: int = 1,
    ) -> sqlite3.Row | None:
        """
        Find a direct child by parent, name, and type.

        IS ? is used instead of = ? so that parent_id=NULL works correctly.
        """
        return self.conn.execute(
            """
            SELECT *
            FROM ibtable
            WHERE parent_id IS ?
            AND name = ?
            AND is_folder = ?
            AND device_id IS ?
            AND computer_id IS ?
            AND isRegularFile = ?
            """,
            (parent_id, name, int(is_folder), device_id, computer_id, isRegularFile),
        ).fetchone()

    # -----------------------------------------------------------------------
    # Maintenance
    # -----------------------------------------------------------------------

    def count(
        self,
        *,
        table: str = "ibtable",
    ) -> int:
        if table not in {"ibtable", "versions", "trash"}:
            raise ValueError("table must be 'ibtable', 'versions', or 'trash'")

        row = self.conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()

        return int(row["count"])

    def vacuum(self) -> None:
        """
        Reclaim unused database space.

        VACUUM cannot run inside a transaction.
        """
        self.conn.commit()
        self.conn.execute("VACUUM")
