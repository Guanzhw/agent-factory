"""Windows task job containment, retained across detached ORX supervisors.

This is process/resource containment for an approved original recipe, not an OS
security sandbox. No KILL_ON_JOB_CLOSE: Factory restart must retain the old run.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Any

from .openresearch import OpenResearchError


class TaskWindowsJob:
    # Declared outside the platform guard so portable static checks can inspect
    # methods without pretending Windows DLLs exist on other platforms.
    kernel: Any
    ntdll: Any

    def __init__(self, task_id: str, limits: dict[str, Any]):
        if os.name != "nt":
            raise OpenResearchError("CONTAINMENT_UNAVAILABLE", "The local ORX profile requires Windows Job Objects")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.name = "Local\\factory-orx-" + task_id
        self.handle = None
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        self.ntdll.NtResumeProcess.restype = ctypes.c_long

        class Security(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]

        security = Security(ctypes.sizeof(Security), None, True)
        self.handle = self.kernel.CreateJobObjectW(ctypes.byref(security), self.name)
        if not self.handle:
            self._fail()
        self._configure(limits, existing=ctypes.get_last_error() == 183)

    def _fail(self) -> None:
        raise OpenResearchError("CONTAINMENT_UNAVAILABLE", "Windows task job operation failed")

    def _configure(self, limits: dict[str, Any], *, existing: bool) -> None:
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t),
                ("process_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t)]

        class CPU(ctypes.Structure):
            _fields_ = [("flags", wintypes.DWORD), ("rate", wintypes.DWORD)]

        # JOB_TIME, ACTIVE_PROCESS, JOB_MEMORY. No breakaway/silent-breakaway;
        # both ORX's detached supervisor and nested upstream local job stay here.
        info = Extended()
        info.basic.flags = 0x4 | 0x8 | 0x200
        info.basic.job_time = int(limits["cpuSeconds"] * 10_000_000)
        info.basic.process_limit = limits["maxProcesses"]
        info.job_memory = limits["memoryBytes"]
        if not existing and not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self._fail()
        cpu = CPU(1 | 4, limits["cpuPercent"] * 100)  # ENABLE | HARD_CAP
        if not existing and not self.kernel.SetInformationJobObject(self.handle, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
            self._fail()
        observed, observed_cpu = Extended(), CPU()
        if (not self.kernel.QueryInformationJobObject(self.handle, 9, ctypes.byref(observed), ctypes.sizeof(observed), None)
                or not self.kernel.QueryInformationJobObject(self.handle, 15, ctypes.byref(observed_cpu), ctypes.sizeof(observed_cpu), None)
                or observed.basic.flags & (0x4 | 0x8 | 0x200) != (0x4 | 0x8 | 0x200)
                or observed.basic.flags & (0x800 | 0x1000 | 0x2000)
                or observed.job_memory != info.job_memory or observed.basic.process_limit != info.basic.process_limit
                or observed.basic.job_time != info.basic.job_time or observed_cpu.flags != cpu.flags or observed_cpu.rate != cpu.rate):
            self._fail()
        self.limits = dict(limits)

    def admit_and_resume(self, pid: int) -> None:
        process = self.kernel.OpenProcess(0x100 | 0x800 | 0x1 | 0x400, False, pid)
        if not process:
            self._fail()
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                self._fail()
            if self.ntdll.NtResumeProcess(process) != 0:
                self._fail()
        finally:
            self.kernel.CloseHandle(process)

    def process_ids(self) -> list[int]:
        class ProcessList(ctypes.Structure):
            _fields_ = [("assigned", wintypes.DWORD), ("count", wintypes.DWORD), ("pids", ctypes.c_size_t * 64)]

        info = ProcessList()
        if not self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info), None):
            self._fail()
        if info.count > 64:
            self._fail()
        return list(info.pids[:info.count])

    def terminate(self) -> None:
        if not self.kernel.TerminateJobObject(self.handle, 1):
            self._fail()

    def evidence(self) -> dict[str, Any]:
        pids = self.process_ids()
        return {"kind": "windows_task_job", "activeProcesses": len(pids),
            "allStopped": len(pids) == 0, "limits": self.limits,
            "enforced": ["aggregate_memory", "aggregate_cpu_time", "cpu_rate", "active_processes"],
            "securitySandbox": False}

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
