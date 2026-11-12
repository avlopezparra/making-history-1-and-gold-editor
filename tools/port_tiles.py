"""Carries over terrain texture changes (OperationalTerrain, headerless DXT5) from one game to another.

Making History Gold has the same textures as MH1 with another color (less saturated sea...): it is a
pixel-by-pixel color transform (verified: an MH1 -> Gold color table hits with mean error < 1/255).
For each tile modified by an MH1 mod:
  1. the MH1 original and the mod's are compared, 4x4 block by 4x4 block (16 DXT5 bytes);
  2. in the blocks that change, the mod's pixel is put through the MH1 -> target color table
     (learned from the pixels of the MH1 original and of the target in those same tiles; if a color is not in the
     table, linear fit);
  3. only those blocks are recompressed over the target texture (tile and its 4 mipmaps).

Usage: python port_tiles.py <art original MH1> <art del mod> <art del destino> <carpeta salida>
     (each is an OperationalTerrain folder with the OperationalTerrain-CC-RR[-0N].tga files)
"""
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_texture import decode, splice  # noqa: E402

NAME = re.compile(r'^OperationalTerrain-(\d\d)-(\d\d)(?:-(\d\d))?\.tga$', re.I)


def size_of(name):
    m = NAME.match(name)
    return 1024 >> int(m.group(3) or 0)


def load(path, size):
    return np.asarray(decode(open(path, 'rb').read(), size)).astype(np.int32)


class ColorMap:
    def __init__(self, src_pixels, dst_pixels):
        q = src_pixels >> 3
        key = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
        self.cnt = np.bincount(key, minlength=1 << 15)
        self.lut = np.stack([np.bincount(key, weights=dst_pixels[:, i], minlength=1 << 15) for i in range(3)], 1) \
            / np.maximum(self.cnt, 1)[:, None]
        X = np.c_[src_pixels, np.ones(len(src_pixels))]
        idx = np.random.default_rng(0).choice(len(X), min(len(X), 300000), replace=False)
        self.W = np.linalg.lstsq(X[idx], dst_pixels[idx], rcond=None)[0]

    def __call__(self, px):
        q = px >> 3
        key = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
        out = self.lut[key]
        sparse = self.cnt[key] < 3
        if sparse.any():
            out[sparse] = np.c_[px[sparse], np.ones(sparse.sum())] @ self.W
        return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def port(orig_dir, mod_dir, target_dir, out_dir, log=print):
    names = sorted(n for n in os.listdir(mod_dir) if NAME.match(n))
    os.makedirs(out_dir, exist_ok=True)
    # one color table per mipmap level (mipmaps are filtered and compressed separately)
    by_size = {}
    for n in names:
        by_size.setdefault(size_of(n), []).append(n)
    report = []
    for size, group in sorted(by_size.items(), reverse=True):
        src = np.concatenate([load(os.path.join(orig_dir, n), size)[..., :3].reshape(-1, 3) for n in group])
        dst = np.concatenate([load(os.path.join(target_dir, n), size)[..., :3].reshape(-1, 3) for n in group])
        cmap = ColorMap(src, dst)
        err = np.abs(cmap(src) - dst).mean()
        for n in group:
            ob, mb, tb = (open(os.path.join(d, n), 'rb').read() for d in (orig_dir, mod_dir, target_dir))
            if mb == ob:
                continue
            mod_img = load(os.path.join(mod_dir, n), size)
            tgt_img = decode(tb, size)
            new = np.asarray(tgt_img).copy()
            nb = size // 4
            blocks = 0
            for i in range(nb * nb):
                if mb[i * 16:(i + 1) * 16] != ob[i * 16:(i + 1) * 16]:
                    by, bx = divmod(i, nb)
                    sl = (slice(by * 4, by * 4 + 4), slice(bx * 4, bx * 4 + 4))
                    px = mod_img[sl][..., :3].reshape(-1, 3)
                    new[sl][..., :3] = cmap(px).reshape(4, 4, 3)
                    new[sl][..., 3] = mod_img[sl][..., 3]
                    blocks += 1
            data, changed = splice(tb, Image.fromarray(new, 'RGBA'), tgt_img, size)
            open(os.path.join(out_dir, n), 'wb').write(data)
            report.append((n, blocks, changed, round(float(err), 2)))
            log('%s: %d bloques cambiados en el mod, %d recomprimidos (error de la tabla de color %.2f)' % (n, blocks, changed, err))
    return report


if __name__ == '__main__':
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    port(*sys.argv[1:])
