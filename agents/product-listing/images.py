"""Read raster dimensions without decoding or altering source images."""
import struct


def image_size(path):
    data = path.read_bytes()
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR':
            size = struct.unpack('>II', data[16:24])
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            size = struct.unpack('<HH', data[6:10])
        elif data[:2] == b'\xff\xd8':
            size = jpeg_size(data)
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            kind, payload = data[12:16], data[20:]
            if kind == b'VP8X':
                if len(payload) < 10: raise ValueError('잘린 WebP 헤더')
                size = (1 + int.from_bytes(payload[4:7], 'little'),
                        1 + int.from_bytes(payload[7:10], 'little'))
            elif kind == b'VP8 ' and payload[3:6] == b'\x9d\x01\x2a':
                size = tuple(v & 0x3fff for v in struct.unpack('<HH', payload[6:10]))
            elif kind == b'VP8L' and payload[0:1] == b'\x2f':
                bits = struct.unpack('<I', payload[1:5])[0]
                size = (1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff))
            else:
                raise ValueError('지원하지 않는 WebP 헤더')
        else:
            raise ValueError('이미지 헤더를 확인할 수 없음')
        if not all(v > 0 for v in size): raise ValueError('이미지 크기는 양수여야 함')
        return list(size)
    except (struct.error, IndexError) as exc:
        raise ValueError('잘린 이미지 헤더') from exc


def jpeg_size(data):
    offset = 2
    while offset < len(data):
        if data[offset] != 0xff: break
        while offset < len(data) and data[offset] == 0xff: offset += 1
        marker = data[offset]; offset += 1
        if marker in (0xd9, 0xda): break
        if marker == 0x01 or 0xd0 <= marker <= 0xd7: continue
        length = struct.unpack('>H', data[offset:offset+2])[0]
        if length < 2 or offset + length > len(data): break
        if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            height, width = struct.unpack('>HH', data[offset+3:offset+7])
            return width, height
        offset += length
    raise ValueError('JPEG 크기 헤더 없음')
