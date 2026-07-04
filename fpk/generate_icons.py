#!/usr/bin/env python3
"""
Generate placeholder PNG icons for the FPK package.
Creates ICON.PNG (128x128) and ICON_256.PNG (256x256) and ui/images/64.png.
Uses a simple fan/cooling themed design.
"""
import struct
import zlib
import os
import math

def create_png(width, height, pixels):
    """Create a PNG file from RGBA pixel data."""
    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xffffffff)
        return struct.pack(">I", len(data)) + chunk + crc

    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = make_chunk(b'IHDR', ihdr_data)

    # IDAT chunk - pixel data with filter byte per row
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # filter: none
        for x in range(width):
            idx = (y * width + x) * 4
            raw_data += bytes(pixels[idx:idx+4])
    compressed = zlib.compress(raw_data, 9)
    idat = make_chunk(b'IDAT', compressed)

    # IEND chunk
    iend = make_chunk(b'IEND', b'')

    return signature + ihdr + idat + iend

def draw_icon(size):
    """Draw a fan/cooling icon."""
    pixels = bytearray(size * size * 4)
    cx, cy = size // 2, size // 2
    r_outer = int(size * 0.42)
    r_inner = int(size * 0.15)

    # Colors
    bg = (26, 29, 39, 255)       # Dark background
    fan_color = (79, 140, 247, 255)  # Blue
    center_color = (34, 211, 238, 255)  # Cyan
    glow = (79, 140, 247, 60)    # Soft glow

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx*dx + dy*dy)

            # Background
            r, g, b, a = bg

            # Outer glow ring
            if r_outer - 8 < dist < r_outer + 4:
                t = 1.0 - abs(dist - r_outer) / 8
                r = int(r * (1-t) + glow[0] * t)
                g = int(g * (1-t) + glow[1] * t)
                b = int(b * (1-t) + glow[2] * t)
                a = 255

            # Fan blades (4 blades, 90 degrees apart)
            if dist < r_outer and dist > r_inner:
                angle = math.atan2(dy, dx)
                # Normalize to 0-2pi
                if angle < 0:
                    angle += 2 * math.pi

                # Check if in a blade region
                for blade_offset in [0, math.pi/2, math.pi, 3*math.pi/2]:
                    blade_angle = angle - blade_offset
                    blade_angle = blade_angle % (2 * math.pi)
                    if blade_angle > math.pi:
                        blade_angle = 2 * math.pi - blade_angle

                    # Blade width decreases toward center
                    blade_width = 0.5 - (dist / r_outer) * 0.2
                    if blade_angle < blade_width:
                        t = 1.0 - (dist / r_outer) * 0.3
                        r = int(fan_color[0] * t + 20 * (1-t))
                        g = int(fan_color[1] * t + 29 * (1-t))
                        b = int(fan_color[2] * t + 39 * (1-t))
                        a = 255
                        break

            # Center hub
            if dist < r_inner:
                t = 1.0 - dist / r_inner
                r = int(center_color[0] * t + fan_color[0] * (1-t))
                g = int(center_color[1] * t + fan_color[1] * (1-t))
                b = int(center_color[2] * t + fan_color[2] * (1-t))
                a = 255

            # Outer ring border
            if r_outer - 2 < dist < r_outer:
                r, g, b, a = fan_color

            pixels[idx] = r
            pixels[idx+1] = g
            pixels[idx+2] = b
            pixels[idx+3] = a

    return pixels

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Generate icons
    for size, name in [(128, "ICON.PNG"), (256, "ICON_256.PNG")]:
        print(f"Generating {name} ({size}x{size})...")
        pixels = draw_icon(size)
        png_data = create_png(size, size, pixels)
        path = os.path.join(base_dir, name)
        with open(path, 'wb') as f:
            f.write(png_data)
        print(f"  Saved: {path} ({len(png_data)} bytes)")

    # Generate ui/images/icon_64.png
    print("Generating ui/images/icon_64.png (64x64)...")
    pixels = draw_icon(64)
    png_data = create_png(64, 64, pixels)
    images_dir = os.path.join(base_dir, "ui", "images")
    os.makedirs(images_dir, exist_ok=True)
    path = os.path.join(images_dir, "icon_64.png")
    with open(path, 'wb') as f:
        f.write(png_data)
    print(f"  Saved: {path} ({len(png_data)} bytes)")

    # Copy icon_256.png to ui/images/
    pixels = draw_icon(256)
    png_data = create_png(256, 256, pixels)
    path = os.path.join(images_dir, "icon_256.png")
    with open(path, 'wb') as f:
        f.write(png_data)
    print(f"  Saved: {path} ({len(png_data)} bytes)")

    print("\nAll icons generated successfully!")

if __name__ == "__main__":
    main()
