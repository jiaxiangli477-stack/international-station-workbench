"""Create a neutral product-image preview from an authorized real product photograph."""
import argparse
from pathlib import Path
from PIL import Image, ImageOps

def render(source, destination):
    source=Path(source);destination=Path(destination)
    if not source.is_file(): raise FileNotFoundError(source)
    with Image.open(source) as raw:
        image=ImageOps.exif_transpose(raw).convert('RGBA')
    if image.getchannel('A').getbbox() is None: raise ValueError('产品照片全部透明，没有可用图像')
    if destination.suffix.lower() != '.png': raise ValueError('output must use .png extension')
    image.thumbnail((760,760),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(1000,1000),(255,255,255,255))
    canvas.alpha_composite(image,((1000-image.width)//2,(1000-image.height)//2))
    destination.parent.mkdir(parents=True,exist_ok=True)
    canvas.convert('RGB').save(destination,format='PNG')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--photo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); out=a.output.resolve()
    if out.drive.upper() not in ('D:','E:'):raise ValueError('output must be on D: or E:')
    render(a.photo,out);print('preview:',out)
if __name__=='__main__':main()
