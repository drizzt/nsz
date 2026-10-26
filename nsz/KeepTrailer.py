import json
from hashlib import sha256
from pathlib import Path
from zstandard import ZstdCompressor, ZstdDecompressor, ZstdError
from nsz.Fs import factory, Xci
from nsz.nut import Print

# The trailer is appended after the NSZ/XCZ container. Readers only follow the
# PFS0/HFS0 offsets, so they ignore it. Layout:
#   [zstd stream: gap bytes]  [zstd frame: JSON map]  [footer]
# footer: u64 gapStreamSize, u64 mapSize, magic
MAGIC = b"NSZKEEP1"
FOOTER_SIZE = 24
CHUNK_SZ = 0x100000


def absoluteOffset(f):
    offset = 0
    while True:
        offset += f.offset
        if not f.isPartition:
            return offset
        f = f.f


def containerFiles(container):
    # (partition, index, file) of every leaf file, partition is "" for NSP and
    # index is the position of the file in its partition, as names can repeat
    if isinstance(container, Xci.Xci):
        return [
            (partition._path, i, f)
            for partition in container.hfs0.files
            for i, f in enumerate(partition.files)
        ]
    return [("", i, f) for i, f in enumerate(container.files)]


def appendTrailer(sourceContainer, sourcePath, outPath, pleaseNoPrint=None):
    outContainer = factory(Path(outPath))
    outContainer.open(str(outPath), "rb")
    try:
        # Output entries by name, in order, so repeated names pair up in order
        outFiles = {}
        for p, i, f in containerFiles(outContainer):
            outFiles.setdefault((p, f._path), []).append((i, f.size))
    finally:
        outContainer.close()

    leaves = []
    for partition, _, f in containerFiles(sourceContainer):
        name = f._path
        same = outFiles.get((partition, name), [])
        ncz = outFiles.get((partition, name[:-4] + ".ncz"), [])
        if same and same[0][1] == f.size:
            leaves.append([absoluteOffset(f), f.size, partition, same.pop(0)[0]])
        elif name.endswith(".nca") and ncz:
            # The trailing 1 tells the rebuild to decompress the NCZ
            leaves.append([absoluteOffset(f), f.size, partition, ncz.pop(0)[0], 1])
    leaves.sort()

    sourceSize = Path(sourcePath).stat().st_size
    segments = []
    pos = 0
    for leaf in leaves:
        offset, size = leaf[0], leaf[1]
        if offset < pos or offset + size > sourceSize:
            continue  # overlapping or truncated entry, keep its bytes as gap
        if offset > pos:
            segments.append([pos, offset - pos])
        segments.append(leaf)
        pos = offset + size
    if pos < sourceSize:
        segments.append([pos, sourceSize - pos])

    hash = sha256()
    compressor = ZstdCompressor().compressobj()
    with open(sourcePath, "rb") as src, open(outPath, "ab") as out:
        gapStart = out.tell()
        for segment in segments:
            remaining = segment[1]
            src.seek(segment[0])
            while remaining > 0:
                chunk = src.read(min(CHUNK_SZ, remaining))
                if not chunk:
                    raise IOError("Unexpected end of {0}".format(sourcePath))
                remaining -= len(chunk)
                hash.update(chunk)
                if len(segment) == 2:
                    out.write(compressor.compress(chunk))
        out.write(compressor.flush())
        gapSize = out.tell() - gapStart
        keepMap = {
            "version": 1,
            "size": sourceSize,
            "sha256": hash.hexdigest(),
            "segments": segments,
        }
        mapData = ZstdCompressor().compress(json.dumps(keepMap).encode())
        out.write(mapData)
        out.write(gapSize.to_bytes(8, "little"))
        out.write(len(mapData).to_bytes(8, "little"))
        out.write(MAGIC)
    Print.info(
        "{0} gap bytes stored in {1} bytes".format(
            sum(s[1] for s in segments if len(s) == 2), gapSize
        ),
        "KEEP",
        pleaseNoPrint=pleaseNoPrint,
    )


def readTrailer(path):
    # Returns (gapStreamOffset, map) or None when the file has no trailer
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        if size < FOOTER_SIZE:
            return None
        f.seek(size - FOOTER_SIZE)
        footer = f.read(FOOTER_SIZE)
        if footer[16:] != MAGIC:
            return None
        gapSize = int.from_bytes(footer[0:8], "little")
        mapSize = int.from_bytes(footer[8:16], "little")
        mapOffset = size - FOOTER_SIZE - mapSize
        try:
            if mapOffset < gapSize:
                raise ValueError("sizes out of range")
            f.seek(mapOffset)
            keepMap = json.loads(ZstdDecompressor().decompress(f.read(mapSize)))
            if not isinstance(keepMap, dict):
                raise ValueError("map is not an object")
        except (ZstdError, ValueError) as e:
            # The container is still valid, decompress it the regular way
            Print.warning(
                "Corrupted --keep trailer in {0} ({1}), ignoring it".format(path, e)
            )
            return None
        if keepMap.get("version") != 1:
            # The container is still valid, decompress it the regular way
            Print.warning(
                "Unsupported --keep trailer version in {0}, ignoring it".format(path)
            )
            return None
        return (mapOffset - gapSize, keepMap)


class GapReader:
    def __init__(self, path, offset):
        self.f = open(path, "rb")
        self.f.seek(offset)
        self.reader = ZstdDecompressor().stream_reader(self.f)

    def read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.reader.read(size - len(data))
            if not chunk:
                raise IOError("Unexpected end of --keep gap stream")
            data += chunk
        return data

    def close(self):
        self.reader.close()
        self.f.close()
