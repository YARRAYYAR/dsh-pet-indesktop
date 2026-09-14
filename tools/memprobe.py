# -*- coding: utf-8 -*-
"""进程内存探针：不依赖 ps / RUSAGE_CHILDREN，直接读 libproc 的真实占用。

本机（macOS）常见限制：
- 沙箱内 `ps` 被禁用，`subprocess.run(['ps', ...])` 抛 PermissionError；
- `resource.getrusage(RUSAGE_CHILDREN)` 只统计已 wait 的子进程，长期存活的
  ffmpeg 不计入，数值偏低不可信；
- `ru_maxrss` 是历史峰值，不能当常驻内存用。

因此统一改用 libproc：
- `proc_pid_rusage(pid, RUSAGE_INFO_V4, buf)` → `ri_phys_footprint`
  （≈ 活动监视器「内存」列）与 `ri_resident_size`；
- `proc_listallpids` + `proc_pidinfo(PROC_PIDTBSDINFO)` → 枚举子进程与状态。

CLI 用法：
    python tools/memprobe.py                 # 采样自身
    python tools/memprobe.py --pid 1234      # 采样指定进程
    python tools/memprobe.py --json          # 输出 JSON
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, asdict

PROC_PIDTBSDINFO = 3
RUSAGE_INFO_V4 = 4
_RUSAGE_BUF_SIZE = 4096
_BSDINFO_SIZE = 136

# proc_bsdinfo 字段偏移（uint32 序列）
_PBI_STATUS_OFFSET = 4
_PBI_PID_OFFSET = 12
_PBI_PPID_OFFSET = 16

# pbi_status 取值
PROC_STATUS_NAMES = {1: 'I', 2: 'R', 3: 'S', 4: 'T', 5: 'Z'}


class _Libproc:
    """惰性加载 libproc；非 macOS 或加载失败时 available 为 False。"""

    def __init__(self) -> None:
        self.available = False
        self._lib = None
        if sys.platform != 'darwin':
            return
        try:
            path = ctypes.util.find_library('proc') or '/usr/lib/libproc.dylib'
            lib = ctypes.cdll.LoadLibrary(path)
        except OSError:
            return
        lib.proc_pid_rusage.restype = ctypes.c_int
        lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        lib.proc_listallpids.restype = ctypes.c_int
        lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.proc_pidinfo.restype = ctypes.c_int
        lib.proc_pidinfo.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
        ]
        self._lib = lib
        self.available = True


_LIBPROC = _Libproc()


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    resident_mib: float
    footprint_mib: float
    status: str = '?'

    def to_dict(self) -> dict:
        return asdict(self)


def available() -> bool:
    """libproc 是否可用；不可用时调用方应回退到 /usr/bin/time -l。"""
    return _LIBPROC.available


def usage(pid: int) -> ProcessUsage | None:
    """返回单进程占用；进程不存在或无权限时返回 None。"""
    if not _LIBPROC.available:
        return None
    buf = ctypes.create_string_buffer(_RUSAGE_BUF_SIZE)
    if _LIBPROC._lib.proc_pid_rusage(int(pid), RUSAGE_INFO_V4, buf) != 0:
        return None
    raw = buf.raw
    # struct rusage_info_v4: uuid_t(16B) 起，随后为 uint64 序列
    resident = struct.unpack_from('<Q', raw, 16 + 6 * 8)[0]
    footprint = struct.unpack_from('<Q', raw, 16 + 7 * 8)[0]
    return ProcessUsage(
        pid=int(pid),
        resident_mib=round(resident / 1048576.0, 3),
        footprint_mib=round(footprint / 1048576.0, 3),
        status=process_status(int(pid)) or '?',
    )


def _process_table() -> dict[int, tuple[int, int]]:
    """pid -> (ppid, status)；枚举失败返回空表。"""
    if not _LIBPROC.available:
        return {}
    lib = _LIBPROC._lib
    count = lib.proc_listallpids(None, 0)
    if count <= 0:
        return {}
    arr = (ctypes.c_int * count)()
    got = lib.proc_listallpids(arr, ctypes.sizeof(arr))
    buf = ctypes.create_string_buffer(_BSDINFO_SIZE)
    table: dict[int, tuple[int, int]] = {}
    for index in range(got):
        pid = arr[index]
        if lib.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, buf, _BSDINFO_SIZE) != _BSDINFO_SIZE:
            continue
        raw = buf.raw
        status = struct.unpack_from('<I', raw, _PBI_STATUS_OFFSET)[0]
        child_pid = struct.unpack_from('<I', raw, _PBI_PID_OFFSET)[0]
        ppid = struct.unpack_from('<I', raw, _PBI_PPID_OFFSET)[0]
        table[int(child_pid)] = (int(ppid), int(status))
    return table


def process_status(pid: int) -> str | None:
    table = _process_table()
    entry = table.get(int(pid))
    return PROC_STATUS_NAMES.get(entry[1], str(entry[1])) if entry else None


def child_pids(pid: int | None = None, *, recursive: bool = False) -> list[int]:
    """直接子进程（recursive=True 时含全部后代）。"""
    parent = os.getpid() if pid is None else int(pid)
    table = _process_table()
    children = [p for p, (pp, _) in table.items() if pp == parent]
    if not recursive:
        return sorted(children)
    seen = set(children)
    frontier = list(children)
    while frontier:
        current = frontier.pop()
        for p, (pp, _) in table.items():
            if pp == current and p not in seen:
                seen.add(p)
                frontier.append(p)
    return sorted(seen)


def process_tree(pid: int | None = None, *, recursive: bool = True) -> dict:
    """自身 + 子进程的内存合计，供 A/B 对比直接使用。"""
    root = os.getpid() if pid is None else int(pid)
    own = usage(root)
    children = []
    for child in child_pids(root, recursive=recursive):
        item = usage(child)
        if item is not None:
            children.append(item)
    total = (own.footprint_mib if own else 0.0) + sum(c.footprint_mib for c in children)
    return {
        'pid': root,
        'self': own.to_dict() if own else None,
        'children': [c.to_dict() for c in children],
        'child_count': len(children),
        'child_total_mib': round(sum(c.footprint_mib for c in children), 3),
        'total_mib': round(total, 3),
    }


def sample_peak(seconds: float, *, interval: float = 0.05, pid: int | None = None) -> dict:
    """在时间窗内对进程树取峰值，避免只抓到一个瞬时点。"""
    root = os.getpid() if pid is None else int(pid)
    peak_child = 0.0
    peak_total = 0.0
    peak_count = 0
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        snapshot = process_tree(root)
        peak_child = max(peak_child, snapshot['child_total_mib'])
        peak_total = max(peak_total, snapshot['total_mib'])
        peak_count = max(peak_count, snapshot['child_count'])
        if time.monotonic() >= deadline:
            break
        time.sleep(interval)
    return {
        'seconds': seconds,
        'peak_child_mib': round(peak_child, 3),
        'peak_total_mib': round(peak_total, 3),
        'peak_child_count': peak_count,
    }


def _self_check() -> None:
    assert available(), 'libproc 不可用，本机无法使用该探针'
    own = usage(os.getpid())
    assert own is not None and own.footprint_mib > 0
    # 自身 pid 必须在进程表里，否则说明字段偏移写错了
    assert process_status(os.getpid()) in set(PROC_STATUS_NAMES.values()), '进程表偏移错误'
    assert isinstance(child_pids(), list)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='libproc 进程内存探针')
    parser.add_argument('--pid', type=int, default=None)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--peak', type=float, default=0.0)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args(argv)

    if args.self_check:
        _self_check()
        print('memprobe: OK (libproc 可用)')
        return 0

    if args.peak > 0:
        result = sample_peak(args.peak, pid=args.pid)
    else:
        result = process_tree(args.pid)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"pid={result['pid']} self={result['self']['footprint_mib']}MiB "
          f"children={result['child_count']} ({result['child_total_mib']}MiB) "
          f"total={result['total_mib']}MiB")
    for child in result['children']:
        print(f"  child pid={child['pid']} status={child['status']} "
              f"footprint={child['footprint_mib']}MiB")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
