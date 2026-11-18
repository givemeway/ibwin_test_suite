#!/usr/bin/env python3
"""
gen_testdata.py - generate realistic, VALID dummy files for backup / sync benchmarking.

Every file is a real, openable file of its type (PNG opens in a viewer, MP4/AVI plays,
ZIP extracts, DLL has a valid PE header, SQLite opens, DOCX/XLSX open in Office, ...).

Sub-commands
  generate   create a tree of files (by --total size and/or --count)
  mutate     change an existing tree (modify / add / delete / touch) -> test incremental backups
  manifest   write path,size,sha256 for a tree
  verify     compare a (restored) tree against a manifest -> test restore integrity

Examples
  python gen_testdata.py generate --out D:\\bench\\src --total 5GB --seed 1
  python gen_testdata.py generate --out ./src --count 20000 --profile small --dup-pct 10
  python gen_testdata.py generate --out ./src --total 2GB --types jpg,mp4,zip,dll,xml,txt
  python gen_testdata.py mutate ./src --modify 10 --add 5 --delete 2 --touch 3
  python gen_testdata.py verify ./restored --manifest src_manifest.csv

Optional extras (script works without them, with fewer formats):
  pip install pillow            -> adds JPEG, GIF, WEBP, TIFF
  pip install imageio-ffmpeg    -> bundled ffmpeg => real H.264 MP4 / MKV  (or install ffmpeg on PATH)
Without ffmpeg, videos are written as uncompressed AVI using only the standard library.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import io
import json
import math
import os
import random
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import wave
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from PIL import Image  # type: ignore
    HAVE_PIL = True
except Exception:  # pragma: no cover
    HAVE_PIL = False

KB, MB, GB = 1024, 1024 ** 2, 1024 ** 3


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG = find_ffmpeg()
_VCODEC = None


def video_codec():
    global _VCODEC
    if _VCODEC is None:
        try:
            out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
            _VCODEC = "libx264" if "libx264" in out else "mpeg4"
        except Exception:
            _VCODEC = "mpeg4"
    return _VCODEC


def parse_size(s: str) -> int:
    s = s.strip().upper().replace("IB", "B")
    for u, m in (("TB", 1024 ** 4), ("GB", GB), ("MB", MB), ("KB", KB), ("B", 1)):
        if s.endswith(u):
            return int(float(s[: -len(u)]) * m)
    return int(s)


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return str(n)


# --------------------------------------------------------------------------------------
# Shared content helpers
# --------------------------------------------------------------------------------------
_WORDS = """backup restore snapshot archive version delta chunk block index folder file sync client
server cloud storage bucket object upload download checksum hash integrity retention policy schedule
incremental differential full deduplication compression encryption latency throughput bandwidth quota
device volume partition metadata catalog journal commit rollback replica shard cluster node region
network packet stream buffer cache queue worker thread process kernel driver service daemon config
setting profile account user group permission token session audit report summary invoice order
customer product price total balance payment shipping delivery photo video music document spreadsheet
presentation email message contact calendar meeting project task deadline milestone budget forecast
quarter annual monthly weekly daily""".split()


def _build_pool():
    r = random.Random(20260116)
    pool = []
    for _ in range(20000):
        s = " ".join(r.choice(_WORDS) for _ in range(r.randint(6, 16))).capitalize() + ".\n"
        if r.random() < 0.1:
            s += "\n"
        pool.append(s)
    return pool


POOL = _build_pool()
FIRST = ["Asha", "Ravi", "Meera", "John", "Maria", "Chen", "Aiko", "Omar", "Sara", "Luca", "Priya", "Tom"]
LAST = ["Patil", "Sharma", "Smith", "Garcia", "Wang", "Tanaka", "Khan", "Rossi", "Kumar", "Brown", "Joshi"]
TABLES = [bytes((i + k) & 255 for i in range(256)) for k in range(256)]


def text_chunk(rng, nbytes: int) -> bytes:
    parts, total = [], 0
    while total < nbytes:
        s = "".join(rng.choices(POOL, k=(nbytes - total) // 80 + 1))
        parts.append(s)
        total += len(s)
    return "".join(parts)[:nbytes].encode()


def person(rng, i):
    fn, ln = rng.choice(FIRST), rng.choice(LAST)
    return {
        "id": i, "name": f"{fn} {ln}", "email": f"{fn}.{ln}{rng.randint(1, 999)}@example.com".lower(),
        "amount": round(rng.uniform(1, 5000), 2),
        "date": time.strftime("%Y-%m-%d", time.gmtime(time.time() - rng.randint(0, 5 * 365 * 86400))),
        "note": rng.choice(POOL).strip().replace(",", ""),
    }


def mix_bytes(rng, n: int) -> bytes:
    """Binary data like real executables/databases: random + zeros + repeating records."""
    out = bytearray()
    while len(out) < n:
        k, L = rng.random(), rng.randint(512, 8192)
        if k < 0.4:
            out += rng.randbytes(L)
        elif k < 0.7:
            out += bytes(L)
        else:
            pat = rng.randbytes(rng.choice([4, 8, 16, 32]))
            out += pat * (L // len(pat))
    return bytes(out[:n])


# --------------------------------------------------------------------------------------
# Stream writers: fn(f, nbytes, rng)
# --------------------------------------------------------------------------------------
def w_txt(f, n, rng):
    left = n
    while left > 0:
        c = min(left, MB)
        f.write(text_chunk(rng, c))
        left -= c


def w_md(f, n, rng):
    f.write(f"# {rng.choice(_WORDS).title()} {rng.choice(_WORDS).title()}\n\n".encode())
    written = 0
    while written < n:
        s = f"## {rng.choice(_WORDS).title()} {rng.choice(_WORDS)}\n\n".encode()
        s += text_chunk(rng, rng.randint(300, 1500)) + b"\n- " + b"\n- ".join(
            rng.choice(POOL).strip().encode() for _ in range(3)) + b"\n\n"
        f.write(s)
        written += len(s)


LEVELS = ["INFO"] * 8 + ["DEBUG"] * 4 + ["WARN"] * 2 + ["ERROR"]
COMPONENTS = ["chunker", "uploader", "scanner", "indexer", "scheduler", "vss", "dedup", "auth", "api"]


def w_log(f, n, rng):
    t = time.time() - rng.randint(0, 90 * 86400)
    left, buf, size = n, [], 0
    while left > 0:
        t += rng.random() * 2
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t)) + f".{int(t % 1 * 1000):03d}"
        line = (f"{ts} {rng.choice(LEVELS):<5} [{rng.choice(COMPONENTS)}-{rng.randint(1, 16)}] "
                f"{rng.choice(POOL).strip()} id={rng.getrandbits(48):012x} ms={rng.randint(1, 900)}\n")
        buf.append(line)
        size += len(line)
        if size >= 1 << 20 or size >= left:
            data = "".join(buf).encode()[:left]
            f.write(data)
            left -= len(data)
            buf, size = [], 0


def _records(f, n, rng, head, row, tail, sep=b""):
    f.write(head)
    written, i = len(head) + len(tail), 0
    while written < n:
        b = row(i)
        if i and sep:
            b = sep + b
        f.write(b)
        written += len(b)
        i += 1
    f.write(tail)


def w_csv(f, n, rng):
    head = b"id,name,email,amount,date,note\n"
    _records(f, n, rng, head, lambda i: ("{id},{name},{email},{amount},{date},{note}\n".format(**person(rng, i))).encode(), b"")


def w_json(f, n, rng):
    _records(f, n, rng, b"[\n", lambda i: json.dumps(person(rng, i)).encode(), b"\n]\n", sep=b",\n")


def w_xml(f, n, rng):
    def row(i):
        p = person(rng, i)
        return (f'  <record id="{p["id"]}">\n    <name>{p["name"]}</name>\n    <email>{p["email"]}</email>\n'
                f'    <amount currency="USD">{p["amount"]}</amount>\n    <date>{p["date"]}</date>\n'
                f'    <note>{p["note"]}</note>\n  </record>\n').encode()
    _records(f, n, rng, b'<?xml version="1.0" encoding="UTF-8"?>\n<records generated="test">\n', row, b"</records>\n")


def w_html(f, n, rng):
    def row(i):
        p = person(rng, i)
        return f'<tr><td>{p["id"]}</td><td>{p["name"]}</td><td>{p["email"]}</td><td>{p["amount"]}</td></tr>\n'.encode()
    head = (b"<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\"><title>Report</title></head><body>\n<h1>Report</h1>\n"
            b"<table border=\"1\">\n<tr><th>ID</th><th>Name</th><th>Email</th><th>Amount</th></tr>\n")
    _records(f, n, rng, head, row, b"</table>\n</body></html>\n")


def w_bin(f, n, rng):
    left = n
    while left > 0:
        c = min(left, MB)
        f.write(rng.randbytes(c))
        left -= c


def w_dat(f, n, rng):
    left = n
    while left > 0:
        c = min(left, MB)
        f.write(mix_bytes(rng, c))
        left -= c


# ---- PDF -------------------------------------------------------------------------------
def w_pdf(f, n, rng):
    pos = 0
    offs = {}

    def w(b):
        nonlocal pos
        f.write(b)
        pos += len(b)

    def obj(num, body):
        offs[num] = pos
        w(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")

    npages = max(1, n // 4400)
    w(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(npages))
    obj(2, f"<< /Type /Pages /Count {npages} /Kids [{kids}] >>".encode())
    obj(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i in range(npages):
        lines = rng.choices(POOL, k=52)
        stream = "BT /F1 9 Tf 36 806 Td 14 TL\n" + "".join(f"({l.strip()[:95]}) '\n" for l in lines) + "ET"
        sb = stream.encode()
        obj(4 + 2 * i, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {5 + 2 * i} 0 R "
                        f"/Resources << /Font << /F1 3 0 R >> >> >>").encode())
        obj(5 + 2 * i, f"<< /Length {len(sb)} >>\nstream\n".encode() + sb + b"\nendstream")
    total = 4 + 2 * npages
    xref = pos
    w(f"xref\n0 {total}\n".encode() + b"0000000000 65535 f \n")
    for k in range(1, total):
        w(f"{offs[k]:010d} 00000 n \n".encode())
    w(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())


# ---- PE (dll / exe) ---------------------------------------------------------------------
def w_pe(f, n, rng, is_dll=True):
    """Structurally valid PE32+ with a tiny code section and a big data section."""
    FA, SA, HDR, TEXT_RAW = 0x200, 0x1000, 0x400, 0x200
    rdata_raw = max(FA, (n - HDR - TEXT_RAW + FA - 1) // FA * FA)
    img_size = (0x2000 + rdata_raw + SA - 1) // SA * SA
    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    coff = struct.pack("<HHIIIHH", 0x8664, 2, int(time.time()) - rng.randint(0, 3 * 365 * 86400), 0, 0, 240,
                       0x2022 if is_dll else 0x0022)
    opt = struct.pack("<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
                      0x20B, 14, rng.randint(0, 40), TEXT_RAW, rdata_raw, 0, 0x1000, 0x1000,
                      0x180000000 if is_dll else 0x140000000, SA, FA, 6, 0, 0, 0, 6, 0, 0,
                      img_size, HDR, 0, 2 if is_dll else 3, 0x0100,
                      0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    assert len(opt) == 112
    dirs = bytes(128)
    sec = struct.pack("<8sIIIIIIHHI", b".text", 6, 0x1000, TEXT_RAW, HDR, 0, 0, 0, 0, 0x60000020)
    sec += struct.pack("<8sIIIIIIHHI", b".rdata", rdata_raw, 0x2000, rdata_raw, HDR + TEXT_RAW, 0, 0, 0, 0, 0x40000040)
    hdr = bytes(dos) + b"PE\0\0" + coff + opt + dirs + sec
    f.write(hdr.ljust(HDR, b"\0"))
    code = b"\xb8\x01\x00\x00\x00\xc3" if is_dll else b"\x31\xc0\xc3"  # DllMain: return TRUE / main: return 0
    f.write(code.ljust(TEXT_RAW, b"\xcc"))
    left = rdata_raw
    while left > 0:
        c = min(left, MB)
        f.write(mix_bytes(rng, c))
        left -= c


def w_exe(f, n, rng):
    w_pe(f, n, rng, is_dll=False)


# ---- Images -------------------------------------------------------------------------------
MAXPX = 24_000_000
MINPX = 32 * 32


def make_rows(w, h, rng, noise):
    """Return list of bytearray RGB rows: gradient + coloured blocks + noise."""
    row_len = w * 3
    xs = bytes((x * 255) // max(1, w - 1) for x in range(w))
    base = bytearray(row_len)
    base[0::3] = xs
    base[1::3] = xs[::-1]
    off = rng.randrange(256)
    base[2::3] = bytes((v + off) & 255 for v in xs)
    mask = int.from_bytes(bytes([noise]) * row_len, "big")
    rows = []
    for y in range(h):
        r = base.translate(TABLES[(y * 255 // max(1, h)) & 255])
        nz = int.from_bytes(rng.randbytes(row_len), "big") & mask
        rows.append(bytearray((int.from_bytes(r, "big") ^ nz).to_bytes(row_len, "big")))
    for _ in range(rng.randint(3, 8)):
        x0 = rng.randrange(w)
        x1 = min(w, x0 + rng.randint(w // 10 + 1, w // 3 + 2))
        y0 = rng.randrange(h)
        y1 = min(h, y0 + rng.randint(h // 10 + 1, h // 3 + 2))
        seg = bytes(rng.randrange(256) for _ in range(3)) * (x1 - x0)
        for y in range(y0, y1):
            rows[y][x0 * 3:x1 * 3] = seg
    return rows


def fit_encode(encode, target, rng, bpp):
    aspect = rng.choice([4 / 3, 3 / 2, 16 / 9, 1.0, 3 / 4])
    px = min(max(target / bpp, MINPX), MAXPX)
    data = b""
    for _ in range(3):
        w = max(16, int((px * aspect) ** 0.5))
        h = max(16, int(px / w))
        data = encode(w, h)
        ok = 0.8 * target <= len(data) <= target
        limit = (len(data) < target and px >= MAXPX) or (len(data) > target and px <= MINPX)
        if ok or limit:
            break
        px = min(max(px * target / max(1, len(data)) * 0.95, MINPX), MAXPX)
    return data


def png_bytes(w, h, rows):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


def pad_png(data, target, rng):
    pad = target - len(data) - 12
    if pad <= 0:
        return data
    body = rng.randbytes(pad)
    junk = struct.pack(">I", pad) + b"juNk" + body + struct.pack(">I", zlib.crc32(b"juNk" + body) & 0xFFFFFFFF)
    return data[:-12] + junk + data[-12:]


def pad_jpeg(data, target, rng):
    pad, out = target - len(data), bytearray()
    while pad > 4:
        L = min(pad - 4, 65533)
        out += b"\xff\xfe" + struct.pack(">H", L + 2) + rng.randbytes(L)
        pad -= L + 4
    return data[:2] + bytes(out) + data[2:]


def w_png(f, n, rng):
    data = fit_encode(lambda w, h: png_bytes(w, h, make_rows(w, h, rng, 0x0F)), n, rng, 1.8)
    f.write(pad_png(data, n, rng))


def w_bmp(f, n, rng):
    aspect = rng.choice([4 / 3, 3 / 2, 16 / 9])
    px = min(max((n - 54) / 3, MINPX), MAXPX)
    w = max(16, int((px * aspect) ** 0.5) // 4 * 4)
    h = max(16, int((n - 54) // (w * 3)))
    rows = make_rows(w, h, rng, 0x3F)
    size = 54 + w * 3 * h
    f.write(b"BM" + struct.pack("<IHHI", size, 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, w * 3 * h, 2835, 2835, 0, 0))
    for r in reversed(rows):  # BMP is bottom-up BGR
        b = bytearray(r)
        b[0::3], b[2::3] = r[2::3], r[0::3]
        f.write(b)


def _pil_writer(fmt, bpp, noise, **kw):
    def writer(f, n, rng):
        def enc(w, h):
            rows = make_rows(w, h, rng, noise)
            im = Image.frombytes("RGB", (w, h), b"".join(bytes(r) for r in rows))
            if fmt == "GIF":
                im = im.quantize(colors=256)
            buf = io.BytesIO()
            q = dict(kw)
            if fmt == "JPEG":
                q["quality"] = rng.choice([80, 85, 90, 95])
            im.save(buf, fmt, **q)
            return buf.getvalue()
        data = fit_encode(enc, n, rng, bpp)
        if fmt == "JPEG":
            data = pad_jpeg(data, n, rng)
        f.write(data)
    return writer


if HAVE_PIL:
    w_jpg = _pil_writer("JPEG", 0.9, 0x1F)
    w_gif = _pil_writer("GIF", 1.0, 0x0F)
    w_webp = _pil_writer("WEBP", 0.7, 0x1F, quality=85)
    w_tif = _pil_writer("TIFF", 3.0, 0x3F)


# ---- Audio -------------------------------------------------------------------------------
def g_wav(path, n, rng):
    sr = 44100
    tones = [rng.choice([220, 261.6, 329.6, 392, 440, 523.3]) for _ in range(3)]
    one = array.array("h", (int(9000 * sum(math.sin(2 * math.pi * t * i / sr) for t in tones) / 3) for i in range(sr)))
    base = one.tobytes()
    mask = int.from_bytes(b"\x0f\x00" * sr, "big")
    total = max(1, (n - 44) // 2)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        done = 0
        while done < total:
            nz = int.from_bytes(rng.randbytes(len(base)), "big") & mask
            chunk = (int.from_bytes(base, "big") ^ nz).to_bytes(len(base), "big")
            frames = min(sr, total - done)
            w.writeframes(chunk[:frames * 2])
            done += frames


# ---- Video -------------------------------------------------------------------------------
def g_video_ffmpeg(path, n, rng, ext):
    codec = video_codec()
    bitrate = rng.choice([1_000_000, 2_000_000, 4_000_000])
    dur = max(2.0, min(1800.0 if n > 400 * MB else 600.0, n * 8 / bitrate))
    bitrate = int(n * 8 / dur * 0.92)
    w, h = (1920, 1080) if n > 400 * MB else rng.choice([(640, 360), (854, 480), (1280, 720)])
    seed = rng.randrange(1 << 30)
    cmd = [FFMPEG, "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=24",
           "-f", "lavfi", "-i", f"sine=frequency={rng.randint(200, 900)}:sample_rate=44100",
           "-vf", f"hue=h={rng.randint(0, 360)},noise=alls=25:allf=t:all_seed={seed}",
           "-t", f"{dur:.2f}", "-c:v", codec, "-b:v", str(max(bitrate, 100_000)), "-pix_fmt", "yuv420p"]
    if codec == "libx264":
        cmd += ["-preset", "ultrafast"]
    cmd += (["-c:a", "pcm_s16le"] if ext == "avi" else ["-c:a", "aac", "-b:a", "96k"])
    cmd += ["-fs", str(n), str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("ffmpeg failed: " + r.stderr[-300:])


def g_avi_raw(path, n, rng):
    """Playable uncompressed AVI (24-bit DIB frames), standard library only."""
    W, H, FPS = 320, 180, 24
    fb = W * H * 3
    N = max(1, (n - 1024) // (fb + 8 + 16))
    hdrl_size = 4 + (8 + 56) + (8 + 4 + (8 + 56) + (8 + 40))
    movi_size = 4 + N * (8 + fb)
    riff_size = 4 + (8 + hdrl_size) + (8 + movi_size) + (8 + N * 16)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", riff_size) + b"AVI ")
        f.write(b"LIST" + struct.pack("<I", hdrl_size) + b"hdrl")
        f.write(b"avih" + struct.pack("<I", 56)
                + struct.pack("<14I", 1_000_000 // FPS, fb * FPS, 0, 0x10, N, 0, 1, fb, W, H, 0, 0, 0, 0))
        f.write(b"LIST" + struct.pack("<I", 4 + 64 + 48) + b"strl")
        f.write(b"strh" + struct.pack("<I4s4sIHHIIIIIIII4h", 56, b"vids", b"DIB ", 0, 0, 0, 0, 1, FPS, 0, N, fb, 0xFFFFFFFF, 0, 0, 0, W, H))
        f.write(b"strf" + struct.pack("<I", 40)
                + struct.pack("<IiiHHIIiiII", 40, W, H, 1, 24, 0, fb, 2835, 2835, 0, 0))
        f.write(b"LIST" + struct.pack("<I", movi_size) + b"movi")
        xs = bytes((x * 255) // (W - 1) for x in range(W))
        base = bytearray(W * 3)
        base[0::3], base[1::3], base[2::3] = xs, xs[::-1], bytes((v // 2) for v in xs)
        mask = int.from_bytes(b"\x0f" * (W * 3), "big")
        for i in range(N):
            f.write(b"00db" + struct.pack("<I", fb))
            ph = (i * 3) & 255
            bx = (i * 4) % (W - 40)
            rows = []
            for y in range(H):
                r = base.translate(TABLES[(y + ph) & 255])
                v = int.from_bytes(r, "big") ^ (int.from_bytes(rng.randbytes(W * 3), "big") & mask)
                row = bytearray(v.to_bytes(W * 3, "big"))
                if H // 3 <= y < H // 3 + 40:
                    row[bx * 3:(bx + 40) * 3] = b"\xff\xff\xff" * 40
                rows.append(row)
            for r in reversed(rows):
                f.write(r)
        f.write(b"idx1" + struct.pack("<I", N * 16))
        for i in range(N):
            f.write(b"00db" + struct.pack("<III", 0x10, 4 + i * (8 + fb), fb))


def g_video(ext):
    def g(path, n, rng):
        if FFMPEG:
            g_video_ffmpeg(path, n, rng, ext)
        else:
            g_avi_raw(path, n, rng)
    return g


# ---- Containers / documents -------------------------------------------------------------
def _stream_bytes(fn, n, rng):
    b = io.BytesIO()
    fn(b, n, rng)
    return b.getvalue()


def g_zip(path, n, rng):
    kinds = {"txt": w_txt, "csv": w_csv, "json": w_json, "xml": w_xml, "log": w_log, "bin": w_bin, "dat": w_dat}
    root = f"archive_{rng.randint(1000, 9999)}"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        i = 0
        while True:
            k = rng.choice(list(kinds))
            sz = int(rng.uniform(2 * KB, max(8 * KB, min(n / 3, 8 * MB))))
            z.writestr(f"{root}/part{i // 10}/file_{i:04d}.{k}", _stream_bytes(kinds[k], sz, rng))
            i += 1
            if z.fp.tell() >= n:
                break


def g_sqlite(path, n, rng):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT, size INTEGER, sha TEXT, mtime REAL, note TEXT, data BLOB)")
    k = 0
    while True:
        rows = []
        for _ in range(500):
            k += 1
            rows.append((f"/home/user/{rng.choice(_WORDS)}/{rng.choice(_WORDS)}/f{k}.dat", rng.randint(1, 1 << 30),
                         f"{rng.getrandbits(256):064x}", time.time() - rng.randint(0, 10 ** 8),
                         rng.choice(POOL).strip(), rng.randbytes(rng.randint(100, 2000))))
        con.executemany("INSERT INTO files(path,size,sha,mtime,note,data) VALUES(?,?,?,?,?,?)", rows)
        con.commit()
        if os.path.getsize(path) >= n:
            break
    con.close()


def _fit_path(build, n, rng):
    """build(rawbytes) writes the file; rescale once if size is far off."""
    raw = n * 2.5
    for _ in range(3):
        build(int(raw))
        size = os.path.getsize(build.path)
        if 0.85 * n <= size <= 1.15 * n or size == 0:
            return
        raw = raw * n / size


def g_docx(path, n, rng):
    def make(raw):
        body, size = [], 0
        while size < raw:
            t = text_chunk(rng, rng.randint(200, 900)).decode().replace("\n", " ")
            p = f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
            body.append(p)
            size += len(p)
        doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
               + "".join(body) + "</w:body></w:document>")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       '<Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
            z.writestr("word/document.xml", doc)
    make.path = path
    _fit_path(make, n, rng)


def g_xlsx(path, n, rng):
    def make(raw):
        rows, size, r = [], 0, 1
        while size < raw:
            p = person(rng, r)
            row = (f'<row r="{r}"><c t="inlineStr"><is><t>{p["name"]}</t></is></c><c t="inlineStr"><is><t>{p["email"]}</t></is></c>'
                   f'<c><v>{p["id"]}</v></c><c><v>{p["amount"]}</v></c><c t="inlineStr"><is><t>{p["date"]}</t></is></c>'
                   f'<c t="inlineStr"><is><t>{p["note"]}</t></is></c></row>')
            rows.append(row)
            size += len(row)
            r += 1
        sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                 + "".join(rows) + "</sheetData></worksheet>")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml",
                       '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                       '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                       '<Default Extension="xml" ContentType="application/xml"/>'
                       '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                       '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            z.writestr("_rels/.rels",
                       '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            z.writestr("xl/workbook.xml",
                       '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/worksheets/sheet1.xml", sheet)
    make.path = path
    _fit_path(make, n, rng)


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------
def stream(fn):
    def g(path, n, rng):
        with open(path, "wb") as f:
            fn(f, n, rng)
    return g


GEN = {
    "txt": stream(w_txt), "md": stream(w_md), "log": stream(w_log), "csv": stream(w_csv), "json": stream(w_json),
    "xml": stream(w_xml), "html": stream(w_html), "bin": stream(w_bin), "dat": stream(w_dat),
    "pdf": stream(w_pdf), "dll": stream(w_pe), "exe": stream(w_exe), "png": stream(w_png), "bmp": stream(w_bmp),
    "wav": g_wav, "zip": g_zip, "sqlite": g_sqlite, "docx": g_docx, "xlsx": g_xlsx,
    "mp4": g_video("mp4"), "mkv": g_video("mkv"), "avi": g_video("avi"),
}
if HAVE_PIL:
    GEN.update({"jpg": stream(w_jpg), "gif": stream(w_gif), "webp": stream(w_webp), "tif": stream(w_tif)})

EXT = {"sqlite": "db"}
PREFIX = {"jpg": "IMG", "png": "Screenshot", "gif": "anim", "bmp": "scan", "webp": "img", "tif": "scan",
          "mp4": "VID", "mkv": "movie", "avi": "clip", "wav": "audio", "pdf": "Document", "docx": "Report",
          "xlsx": "Budget", "zip": "archive", "sqlite": "data", "dll": "lib", "exe": "setup", "log": "app",
          "csv": "export", "json": "data", "xml": "config", "html": "page", "md": "notes", "txt": "note",
          "bin": "blob", "dat": "cache"}
WEIGHTS = {"jpg": 14, "png": 8, "gif": 1, "bmp": 1, "webp": 1, "tif": 1, "mp4": 3, "mkv": 1, "avi": 1, "wav": 2,
           "txt": 10, "log": 6, "csv": 6, "json": 6, "xml": 5, "html": 3, "md": 3, "pdf": 6, "docx": 4,
           "xlsx": 3, "zip": 6, "sqlite": 2, "dll": 6, "exe": 2, "bin": 4, "dat": 4}
RANGES = {"jpg": (200 * KB, 8 * MB), "png": (50 * KB, 6 * MB), "gif": (20 * KB, 2 * MB), "bmp": (100 * KB, 6 * MB),
          "webp": (30 * KB, 3 * MB), "tif": (500 * KB, 20 * MB), "mp4": (5 * MB, 200 * MB), "mkv": (5 * MB, 200 * MB),
          "avi": (5 * MB, 100 * MB), "wav": (500 * KB, 40 * MB), "txt": (KB, 5 * MB), "log": (10 * KB, 50 * MB),
          "csv": (10 * KB, 30 * MB), "json": (2 * KB, 20 * MB), "xml": (2 * KB, 20 * MB), "html": (4 * KB, 2 * MB),
          "md": (KB, 200 * KB), "pdf": (50 * KB, 20 * MB), "docx": (20 * KB, 5 * MB), "xlsx": (20 * KB, 8 * MB),
          "zip": (20 * KB, 100 * MB), "sqlite": (100 * KB, 100 * MB), "dll": (10 * KB, 30 * MB),
          "exe": (50 * KB, 50 * MB), "bin": (KB, 50 * MB), "dat": (KB, 50 * MB)}
FOLDERS = ["Documents", "Photos", "Projects", "Videos", "Music", "Backups", "Work", "Archive", "Downloads",
           "Desktop", "Source", "Reports", "Invoices", "Travel", "Family", "Misc"]


def size_range(t, profile, min_size, max_size):
    lo, hi = RANGES[t]
    if profile == "small":
        lo, hi = KB, min(hi, 256 * KB)
    elif profile == "large":
        lo, hi = lo * 5, hi * 5
    if min_size is not None or max_size is not None:   # explicit range wins over per-type defaults
        lo = min_size if min_size is not None else min(lo, max_size)
        hi = max_size if max_size is not None else max(hi, lo)
        lo = min(lo, hi)
    return max(lo, 512), max(hi, 512)


# --------------------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------------------
def sha256_file(p, bs=4 * MB):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(bs)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def resolve_types(a):
    wanted = [t.strip().lower() for t in a.types.split(",")] if a.types != "all" else list(WEIGHTS)
    weights = {}
    for t in wanted:
        if t in ("jpeg",):
            t = "jpg"
        if t not in WEIGHTS:
            sys.exit(f"unknown type '{t}'. known: {', '.join(WEIGHTS)}")
        if t not in GEN:
            print(f"  ! '{t}' needs Pillow (pip install pillow) - skipped", file=sys.stderr)
            continue
        if t in ("mp4", "mkv") and not FFMPEG:
            print(f"  ! '{t}' needs ffmpeg (pip install imageio-ffmpeg) - using raw AVI instead", file=sys.stderr)
            t = "avi"
        weights[t] = weights.get(t, 0) + WEIGHTS[t]
    return weights


def make_dirs(out: Path, n_dirs, depth, rng):
    dirs, dep = [Path(".")], {Path("."): 0}
    for i in range(n_dirs):
        parent = rng.choice([d for d in dirs if dep[d] < depth])
        d = parent / f"{rng.choice(FOLDERS)}_{i:03d}"
        dirs.append(d)
        dep[d] = dep[parent] + 1
        (out / d).mkdir(parents=True, exist_ok=True)
    return dirs


def plan(a, rng, weights, dirs, start_idx=0):
    types, w = list(weights), list(weights.values())
    items, total, i = [], 0, 0
    count = a.count if a.count else (None if a.total else 100)
    while (count is None or i < count) and (not a.total or total < a.total):
        t = rng.choices(types, w)[0]
        lo, hi = size_range(t, a.profile, a.min_size, a.max_size)
        size = int(math.exp(rng.uniform(math.log(lo), math.log(hi))))
        if a.total:
            size = min(size, a.total - total)
            if size < 512:
                break
        idx = start_idx + i
        name = f"{PREFIX.get(t, 'file')}_{idx:06d}.{EXT.get(t, t)}"
        rel = rng.choice(dirs) / name
        items.append((idx, t, size, rel, time.time() - rng.uniform(0, 3 * 365 * 86400)))
        total += size
        i += 1
    return items


def run_items(out: Path, items, a, label="generate"):
    manifest, errors, done_bytes, t0 = [], 0, 0, time.time()
    last = 0.0

    def work(it):
        idx, t, size, rel, mt = it
        p = out / rel
        GEN[t](str(p), size, random.Random(a.seed * 1_000_003 + idx))
        if not a.no_mtime:
            os.utime(p, (mt, mt))
        real = p.stat().st_size
        return it, real, ("" if a.no_hash else sha256_file(p))

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, it): it for it in items}
        for k, fu in enumerate(as_completed(futs), 1):
            try:
                it, real, digest = fu.result()
                manifest.append((it[3].as_posix(), it[1], real, digest))
                done_bytes += real
            except Exception as e:
                errors += 1
                print(f"\n  ! {futs[fu][3]} ({futs[fu][1]}): {e}", file=sys.stderr)
            now = time.time()
            if now - last > 0.5 or k == len(items):
                last = now
                el = max(now - t0, 1e-6)
                print(f"\r  {label}: {k}/{len(items)} files  {human(done_bytes)}  {done_bytes / MB / el:.1f} MB/s   ", end="", flush=True)
    print()
    return manifest, errors, time.time() - t0


def write_manifest(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "type", "size", "sha256"])
        w.writerows(sorted(rows))


def cmd_generate(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    weights = resolve_types(a)
    if not weights:
        sys.exit("no usable file types")
    print(f"types: {', '.join(weights)}")
    print(f"ffmpeg: {'yes' if FFMPEG else 'no (raw AVI fallback)'}   pillow: {'yes' if HAVE_PIL else 'no'}")
    dirs = make_dirs(out, a.dirs, a.depth, rng)
    items = plan(a, rng, weights, dirs)
    print(f"planned {len(items)} files, ~{human(sum(i[2] for i in items))} into {out}")
    manifest, errors, el = run_items(out, items, a)
    if a.dup_pct and manifest:
        k = int(len(manifest) * a.dup_pct / 100)
        dups = []
        for j, (rel, t, size, digest) in enumerate(rng.sample(manifest, min(k, len(manifest)))):
            src = out / rel
            dst_rel = rng.choice(dirs) / f"copy_{j:05d}_{src.name}"
            shutil.copyfile(src, out / dst_rel)
            dups.append((dst_rel.as_posix(), t, size, digest))
        manifest += dups
        print(f"  added {len(dups)} exact duplicates (dedup test)")
    tot = sum(m[2] for m in manifest)
    mp = Path(a.manifest) if a.manifest else out.parent / f"{out.name}_manifest.csv"
    if not a.no_hash:
        write_manifest(mp, manifest)
        print(f"manifest: {mp}")
    by = {}
    for _, t, s, _ in manifest:
        c, b = by.get(t, (0, 0))
        by[t] = (c + 1, b + s)
    print(f"\n{len(manifest)} files, {human(tot)}, {el:.1f}s, errors={errors}")
    for t, (c, b) in sorted(by.items(), key=lambda x: -x[1][1]):
        print(f"  {t:<7}{c:>7} files {human(b):>11}")


# --------------------------------------------------------------------------------------
# mutate / manifest / verify
# --------------------------------------------------------------------------------------
def walk_files(root: Path):
    for dp, _, fns in os.walk(root):
        for fn in fns:
            yield Path(dp) / fn


def cmd_mutate(a):
    root = Path(a.dir)
    rng = random.Random(a.seed)
    files = list(walk_files(root))
    rng.shuffle(files)
    N = len(files)
    take = lambda pct: [files.pop() for _ in range(min(len(files), int(N * pct / 100)))]
    mod, dele, touch = take(a.modify), take(a.delete), take(a.touch)
    mbytes = 0
    for p in mod:
        size = p.stat().st_size
        with open(p, "r+b") as f:
            if rng.random() < 0.5 or size < 8 * KB:   # append
                data = rng.randbytes(rng.randint(KB, 256 * KB))
                f.seek(0, 2)
            else:                                     # overwrite a block in the middle (delta-sync test)
                L = min(size // 2, rng.randint(4 * KB, 256 * KB))
                f.seek(rng.randint(0, size - L))
                data = rng.randbytes(L)
            f.write(data)
            mbytes += len(data)
    freed = 0
    for p in dele:
        freed += p.stat().st_size
        p.unlink()
    now = time.time()
    for p in touch:
        os.utime(p, (now, now))
    added = 0
    if a.add:
        a.count, a.total, a.min_size = max(1, int(N * a.add / 100)), None, None
        a.no_mtime, a.no_hash = False, True
        weights = resolve_types(argparse.Namespace(types="all"))
        dirs = [Path(dp).relative_to(root) for dp, _, _ in os.walk(root)]
        items = plan(a, rng, weights, dirs, start_idx=int(time.time()) % 10 ** 6 * 10)
        run_items(root, items, a, label="add")
        added = len(items)
    print(f"modified {len(mod)} (+{human(mbytes)} written), deleted {len(dele)} ({human(freed)}), "
          f"touched {len(touch)}, added {added}")


def cmd_manifest(a):
    root = Path(a.dir)
    rows = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(sha256_file, p): p for p in walk_files(root)}
        for fu in as_completed(futs):
            p = futs[fu]
            rows.append((p.relative_to(root).as_posix(), p.suffix.lstrip("."), p.stat().st_size, fu.result()))
    write_manifest(a.out, rows)
    print(f"{len(rows)} files -> {a.out}")


def cmd_verify(a):
    root = Path(a.dir)
    with open(a.manifest, newline="", encoding="utf-8") as f:
        want = {r["path"]: r for r in csv.DictReader(f)}
    missing, bad_size, bad_hash = [], [], []

    def chk(rel, r):
        p = root / rel
        if not p.exists():
            return "missing", rel
        if p.stat().st_size != int(r["size"]):
            return "size", rel
        if r["sha256"] and sha256_file(p) != r["sha256"]:
            return "hash", rel
        return "ok", rel

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for kind, rel in ex.map(lambda kv: chk(*kv), want.items()):
            {"missing": missing, "size": bad_size, "hash": bad_hash}.get(kind, []).append(rel)
    extra = {p.relative_to(root).as_posix() for p in walk_files(root)} - set(want)
    print(f"checked {len(want)} files: missing={len(missing)} size-mismatch={len(bad_size)} "
          f"hash-mismatch={len(bad_hash)} extra={len(extra)}")
    for lab, lst in (("MISSING", missing), ("SIZE", bad_size), ("HASH", bad_hash)):
        for rel in lst[:20]:
            print(f"  {lab}: {rel}")
    sys.exit(1 if (missing or bad_size or bad_hash) else 0)


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cpu = min(8, os.cpu_count() or 4)

    g = sub.add_parser("generate", help="create a tree of test files")
    g.add_argument("--out", required=True)
    g.add_argument("--total", type=parse_size, help="stop when this much data is generated, e.g. 5GB")
    g.add_argument("--count", type=int, help="number of files (default 100 if --total not set)")
    g.add_argument("--types", default="all", help="comma list, e.g. jpg,mp4,zip,dll  (default: all)")
    g.add_argument("--profile", choices=["mixed", "small", "large"], default="mixed",
                   help="small = many tiny files (<=256KB); large = 5x bigger files")
    g.add_argument("--min-size", type=parse_size, help="overrides per-type size ranges, e.g. 1GB")
    g.add_argument("--max-size", type=parse_size, help="overrides per-type size ranges, e.g. 5GB")
    g.add_argument("--dirs", type=int, default=40, help="number of sub-folders")
    g.add_argument("--depth", type=int, default=4, help="max folder depth")
    g.add_argument("--dup-pct", type=float, default=0, help="%% of extra exact-duplicate files (dedup test)")
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--workers", type=int, default=cpu)
    g.add_argument("--no-hash", action="store_true", help="skip sha256 + manifest (faster)")
    g.add_argument("--no-mtime", action="store_true", help="don't randomise modified-times")
    g.add_argument("--manifest", help="manifest path (default: <out>_manifest.csv next to out dir)")
    g.set_defaults(fn=cmd_generate)

    m = sub.add_parser("mutate", help="modify an existing tree to test incremental backups")
    m.add_argument("dir")
    m.add_argument("--modify", type=float, default=10, help="%% of files to change content")
    m.add_argument("--add", type=float, default=5, help="%% new files")
    m.add_argument("--delete", type=float, default=2, help="%% deleted files")
    m.add_argument("--touch", type=float, default=3, help="%% files with only mtime changed")
    m.add_argument("--profile", choices=["mixed", "small", "large"], default="mixed")
    m.add_argument("--max-size", type=parse_size, default=parse_size("50MB"))
    m.add_argument("--seed", type=int, default=int(time.time()) % 100000)
    m.add_argument("--workers", type=int, default=cpu)
    m.set_defaults(fn=cmd_mutate)

    mf = sub.add_parser("manifest", help="hash a tree into a manifest csv")
    mf.add_argument("dir")
    mf.add_argument("--out", required=True)
    mf.add_argument("--workers", type=int, default=cpu)
    mf.set_defaults(fn=cmd_manifest)

    v = sub.add_parser("verify", help="check a restored tree against a manifest")
    v.add_argument("dir")
    v.add_argument("--manifest", required=True)
    v.add_argument("--workers", type=int, default=cpu)
    v.set_defaults(fn=cmd_verify)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
