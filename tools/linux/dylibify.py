#!/usr/bin/env python3
# 把 iOS 可执行文件原地改成 LiveContainer 能当 guest 加载的 dylib：python3 dylibify.py <Mach-O>
# 做法同 LiveContainer 运行时给 guest 打的补丁（LCMachOUtils.m 的 LCPatchExecSlice，不注入 TweakLoader）：
# 文件类型改 MH_DYLIB、__PAGEZERO 缩成紧贴 __TEXT 的一页（段数不变，chained fixups 的 seg_count 不用动）、
# 开头插入 LC_ID_DYLIB。LC_MAIN 保留，LiveContainer 按它找 main。CI 用的 jakeajames/dylibify 是删掉 __PAGEZERO，
# 所以那边还得跑 fix_chained_seg_count.py；这里不需要。
import struct, sys

MH_MAGIC_64, MH_EXECUTE, MH_DYLIB = 0xFEEDFACF, 0x2, 0x6
MH_PIE, MH_NO_REEXPORTED_DYLIBS = 0x200000, 0x100000
LC_SEGMENT_64, LC_ID_DYLIB, LC_CODE_SIGNATURE = 0x19, 0xD, 0x1D

path = sys.argv[1]
b = bytearray(open(path, "rb").read())
magic, cpu, sub, filetype, ncmds, sizeofcmds, flags, _ = struct.unpack_from("<8I", b)
if magic != MH_MAGIC_64 or filetype != MH_EXECUTE:
    sys.exit(f"{path}: 不是 64 位 Mach-O 可执行文件")

off, first_data = 32, len(b)
for _ in range(ncmds):
    cmd, size = struct.unpack_from("<II", b, off)
    if cmd == LC_CODE_SIGNATURE:
        sys.exit(f"{path}: 已签名，改完签名就失效了，先用未签名的")
    if cmd == LC_SEGMENT_64:
        for i in range(struct.unpack_from("<I", b, off + 64)[0]):
            sect_off, sect_size = struct.unpack_from("<I", b, off + 72 + 80 * i + 48)[0], struct.unpack_from("<Q", b, off + 72 + 80 * i + 40)[0]
            if sect_off and sect_size:
                first_data = min(first_data, sect_off)
    off += size

# __PAGEZERO 必须是第一条：缩成 __TEXT（0x100000000）前的一页，避免 dylib 占掉 4GB 地址空间
cmd, _, segname, vmaddr, vmsize = struct.unpack_from("<II16sQQ", b, 32)
if cmd != LC_SEGMENT_64 or segname.rstrip(b"\0") != b"__PAGEZERO" or vmaddr != 0:
    sys.exit(f"{path}: 第一条加载命令不是 __PAGEZERO")
struct.pack_into("<QQ", b, 32 + 24, 0x100000000 - 0x4000, 0x4000)

# LC_ID_DYLIB 放第一条（同 LiveContainer / dylibify），名字取文件名
name = path.rsplit("/", 1)[-1].encode() + b"\0"
idcmd = struct.pack("<IIIIII", LC_ID_DYLIB, 24 + len(name) + (-len(name) % 8), 24, 2, 0x10000, 0x10000)
idcmd += name + b"\0" * (-len(name) % 8)
if 32 + sizeofcmds + len(idcmd) > first_data:
    sys.exit(f"{path}: 加载命令后面空间不够插 LC_ID_DYLIB（链接时加 -headerpad）")
b[32:32 + sizeofcmds + len(idcmd)] = idcmd + b[32:32 + sizeofcmds]
struct.pack_into("<IIII", b, 12, MH_DYLIB, ncmds + 1, sizeofcmds + len(idcmd), (flags | MH_NO_REEXPORTED_DYLIBS) & ~MH_PIE)
open(path, "wb").write(b)
print(f"{path}: 已转成 dylib（LC_ID_DYLIB {name[:-1].decode()}）")
