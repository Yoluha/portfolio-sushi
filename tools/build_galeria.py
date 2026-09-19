"""Gera a galeria do site a partir das fotos e vídeos originais em fotos/.

Lê tools/galeria-fontes.json (álbuns, ordem e ficheiros de origem) e escreve:
  galeria/<álbum>/NN.jpg    foto reduzida (lado maior 1600 px, sem EXIF)
  galeria/<álbum>/NN_t.jpg  miniatura (lado menor 560 px)
  galeria/<álbum>/NN.mp4    vídeo H.264 com faststart (miniatura = primeiro segundo)
  galeria/og.jpg            imagem de pré-visualização para WhatsApp/redes (1200x630)
  galeria/galeria.js        window.GALERIA com a lista usada pelo index.html

Uso: python tools/build_galeria.py   (FFMPEG=caminho para outro ffmpeg, se preciso)
"""
import json, os, re, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "fotos"
OUT = ROOT / "galeria"
FFMPEG = os.environ.get("FFMPEG", r"C:\Users\Lucas\AppData\Local\CapCut\Apps\9.4.0.4015\ffmpeg.exe")
FULL_EDGE, THUMB_SHORT = 1600, 560
VIDEO_EXT = {".mp4", ".mod", ".mov"}


def load_image(path, rotate=0):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return im.rotate(rotate, expand=True) if rotate else im


def save_scaled(im, dest, *, long_edge=None, short_edge=None, quality):
    w, h = im.size
    scale = min(1, long_edge / max(w, h)) if long_edge else min(1, short_edge / min(w, h))
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)
    return im.size


def probe(path):
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    w, h = map(int, re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", err).groups())
    return int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), "mpeg2video" in err, w, h


def encode_video(path, dest):
    duration, interlaced, w, h = probe(path)
    # lado maior no máximo 1280; vídeos antigos da câmara (MPEG-2 entrelaçado, pixel não quadrado) são corrigidos
    vf = "yadif,scale=trunc(iw*sar/2)*2:ih,setsar=1," if interlaced else ""
    vf += "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
    # teto de débito proporcional à área de saída: ~1.8 Mb/s a 720p, ~0.7 Mb/s nos vídeos pequenos
    area = w * h * min(1, 1280 / max(w, h)) ** 2
    maxrate = int(min(2000, max(700, area / 500)))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(path), "-vf", vf,
                    "-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "30", "-b:v", "0",
                    "-maxrate", f"{maxrate}k", "-bufsize", f"{2 * maxrate}k", "-profile:v", "high", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", str(dest)], check=True)
    return duration


def video_poster(video, dest, duration):
    # a miniatura sai do vídeo já convertido, por isso já tem orientação e proporção corretas
    frame = dest.with_suffix(".png")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", f"{min(1.0, duration / 3):.2f}", "-i", str(video),
                    "-frames:v", "1", str(frame)], check=True)
    size = save_scaled(Image.open(frame).convert("RGB"), dest, short_edge=THUMB_SHORT, quality=74)
    frame.unlink()
    return size


def main():
    cfg = json.loads((ROOT / "tools" / "galeria-fontes.json").read_text(encoding="utf-8"))
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    albums = []
    for album in cfg["albuns"]:
        folder = OUT / album["slug"]
        folder.mkdir()
        items = []
        for n, item in enumerate(album["itens"], 1):
            src = SRC / item["src"]
            base = f"{n:02d}"
            if src.suffix.lower() in VIDEO_EXT:
                duration = encode_video(src, folder / f"{base}.mp4")
                w, h = video_poster(folder / f"{base}.mp4", folder / f"{base}_t.jpg", duration)
                items.append({"v": 1, "src": f"{base}.mp4", "w": w, "h": h, "d": round(duration)})
            else:
                im = load_image(src, item.get("rodar", 0))
                w, h = save_scaled(im, folder / f"{base}.jpg", long_edge=FULL_EDGE, quality=80)
                save_scaled(im, folder / f"{base}_t.jpg", short_edge=THUMB_SHORT, quality=74)
                items.append({"src": f"{base}.jpg", "w": w, "h": h})
            print(f"  {album['slug']}/{base}  <- {item['src']}")
        albums.append({k: album[k] for k in ("slug", "titulo", "sub") if k in album}
                      | {"destaque": album.get("destaque", False), "antigo": album.get("antigo", False),
                         "itens": items})

    og = ImageOps.fit(load_image(SRC / cfg["og"]), (1200, 630), Image.LANCZOS)
    og.save(OUT / "og.jpg", "JPEG", quality=82, optimize=True, progressive=True)

    js = "window.GALERIA = " + json.dumps(albums, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (OUT / "galeria.js").write_text(js, encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"{sum(len(a['itens']) for a in albums)} itens, {total / 1e6:.1f} MB em {OUT}")


if __name__ == "__main__":
    main()
