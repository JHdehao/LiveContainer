#!/usr/bin/env python3
# dylibify drops __PAGEZERO but leaves LC_DYLD_CHAINED_FIXUPS' seg_count untouched,
# so dyld rejects the dylib ("seg_count exceeds number of segments").
# Drop the leading (empty) __PAGEZERO entry from dyld_chained_starts_in_image to match.
import struct, sys

LC_SEGMENT_64, LC_DYLD_CHAINED_FIXUPS, MH_MAGIC_64 = 0x19, 0x80000034, 0xFEEDFACF

path = sys.argv[1]
data = bytearray(open(path, 'rb').read())
magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<8I', data, 0)
if magic != MH_MAGIC_64:
    sys.exit(f'{path}: not a thin 64-bit Mach-O')

off, nsegs, fixups = 32, 0, None
for _ in range(ncmds):
    cmd, size = struct.unpack_from('<2I', data, off)
    if cmd == LC_SEGMENT_64:
        nsegs += 1
    elif cmd == LC_DYLD_CHAINED_FIXUPS:
        fixups = struct.unpack_from('<2I', data, off + 8)
    off += size

if fixups is None:
    print('no chained fixups, nothing to do'); sys.exit(0)
starts = fixups[0] + struct.unpack_from('<I', data, fixups[0] + 4)[0]
seg_count = struct.unpack_from('<I', data, starts)[0]
print(f'segments={nsegs} seg_count={seg_count}')
if seg_count == nsegs:
    sys.exit(0)
offsets = struct.unpack_from(f'<{seg_count}I', data, starts + 4)
if seg_count != nsegs + 1 or offsets[0] != 0:
    sys.exit('unexpected layout, refusing to patch')
struct.pack_into(f'<{seg_count}I', data, starts, seg_count - 1, *offsets[1:])
open(path, 'wb').write(data)
print(f'patched seg_count -> {seg_count - 1}')
