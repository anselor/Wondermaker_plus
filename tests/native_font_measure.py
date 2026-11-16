"""Execute the pinned factory LVGL text measurement, including real kerning."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess


class StockFontMeasure:
    def __init__(self, root):
        import unicorn
        from unicorn import arm64_const as registers
        self.registers = registers
        profile = json.loads((root/'client-preload/unified-ui/native/profile1113.json').read_text())
        client = root/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
        data = client.read_bytes()
        assert hashlib.sha256(data).hexdigest() == profile['client_sha256']
        symbols = subprocess.check_output(['nm', '-n', str(client)], text=True)
        self.entry = int(next(line.split()[0] for line in symbols.splitlines()
                              if line.endswith(' lv_txt_get_size')), 16)
        self.fonts = {int(row['address'], 16) for row in profile['functions']
                      if row['name'].startswith('MyriadPro_')}
        phoff = struct.unpack_from('<Q', data, 32)[0]
        size, count = struct.unpack_from('<HH', data, 54)
        segments = [struct.unpack_from('<IIQQQQQQ', data, phoff+i*size)
                    for i in range(count)]
        loads = [s for s in segments if s[0] == 1]
        self.emu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        self.emu.mem_map(0x400000, ((max(s[3]+s[6] for s in loads)+4095)&~4095)-0x400000)
        for _, _, offset, address, _, length, _, _ in loads:
            self.emu.mem_write(address, data[offset:offset+length])
        self.emu.mem_map(0x20000000, 0x200000)
        self.cache = {}

    def measure(self, font, text, width):
        assert font in self.fonts, hex(font)
        assert 0 < width < 8192
        key = font, text, width
        if key in self.cache:
            return self.cache[key]
        r = self.registers
        output, source, stop = 0x20100000, 0x20101000, 0x201ff000
        encoded = text.encode('utf-8') + b'\0'
        assert len(encoded) < 60000
        self.emu.mem_write(source, encoded)
        for i, value in enumerate((output, source, font, 0, 0, width, 0)):
            self.emu.reg_write(r.UC_ARM64_REG_X0+i, value)
        self.emu.reg_write(r.UC_ARM64_REG_SP, 0x200ff000)
        self.emu.reg_write(r.UC_ARM64_REG_X30, stop)
        self.emu.emu_start(self.entry, stop, timeout=5000000, count=10000000)
        assert self.emu.reg_read(r.UC_ARM64_REG_PC) == stop, 'Text measurement did not return'
        result = struct.unpack('<hh', self.emu.mem_read(output, 4))
        self.cache[key] = result
        return result
