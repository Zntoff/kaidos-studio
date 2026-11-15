"""Generate Kairos's SVG mark, outlined wordmark and Windows icon.

Owner-supplied identity guide; Inter is SIL OFL 1.1. Requires Pillow and fonttools.
"""
from pathlib import Path
from PIL import Image, ImageDraw
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'clipper/web/static/brand'
MARK = 'M21 0H57L75 18V96H21Z M31 10V86H65V22.142L52.858 10Z M42 42H54V54H42Z M0 45H15V51H0Z M81 45H96V51H81Z'


def svg(body, viewbox, color):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" fill="{color}">{body}</svg>\n'


def wordmark():
    font = instantiateVariableFont(TTFont(WEB/'fonts/Inter-Variable.ttf'), {'wght':600, 'opsz':32})
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = 100 / font['head'].unitsPerEm
    x, parts, i_right, k_left, k_top = 0, [], 0, 0, 0
    for c in 'kairos':
        name = cmap[ord('\u0131' if c == 'i' else c)]
        pen = SVGPathPen(glyphs); glyphs[name].draw(pen)
        bounds = BoundsPen(glyphs); glyphs[name].draw(bounds)
        if c == 'k':
            k_left = bounds.bounds[0]*scale
            k_top = bounds.bounds[3]*scale
        if c == 'i': i_right = x + bounds.bounds[2]*scale
        parts.append(f'<path transform="translate({x:.4f} 0) scale({scale:.8f} {-scale:.8f})" d="{pen.getCommands()}"/>')
        x += font['hmtx'][name][0]*scale - 1.2
    y, h, stem = -k_top-12, 12, 12
    parts.append(f'<path fill-rule="evenodd" d="M0 {y}H{i_right:.4f}V{y+h}H0Z M{k_left:.4f} {y+2}H{k_left+stem:.4f}V{y+h}H{k_left:.4f}Z"/>')
    return ''.join(parts), x+1.2, k_top+12


def render(bg, fg, size):
    unit, origin = 2048*.6/96, 2048*.2
    p = lambda x: origin+x*unit
    img=Image.new('RGBA',(2048,2048),(0,0,0,0)); d=ImageDraw.Draw(img)
    d.rounded_rectangle((0,0,2047,2047),radius=448,fill=bg,outline=(42,42,42,255),width=5)
    d.polygon([(p(x),p(y)) for x,y in [(21,0),(57,0),(75,18),(75,96),(21,96)]],fill=fg)
    d.polygon([(p(x),p(y)) for x,y in [(31,10),(52.858,10),(65,22.142),(65,86),(31,86)]],fill=bg)
    for box in [(42,42,54,54),(0,45,15,51),(81,45,96,51)]: d.rectangle(tuple(p(v) for v in box),fill=fg)
    return img.resize((size,size),Image.Resampling.LANCZOS)


def main():
    body,width,height=wordmark()
    symbol=f'<path fill-rule="evenodd" d="{MARK}"/>'
    for suffix,color in [('white','#FAFAFA'),('black','#0A0A0A')]:
        (WEB/f'mark-{suffix}.svg').write_text(svg(symbol,'0 0 96 96',color),encoding='utf-8')
        (WEB/f'wordmark-{suffix}.svg').write_text(svg(body,f'0 {-height:.4f} {width:.4f} {height+2:.4f}',color),encoding='utf-8')
        logo=f'<g transform="translate(0 4) scale(.75)">{symbol}</g><g transform="translate(94 {height:.4f})">{body}</g>'
        (WEB/f'logo-{suffix}.svg').write_text(svg(logo,f'0 0 {94+width:.4f} {height+2:.4f}',color),encoding='utf-8')
    (WEB/'mark.svg').write_text((WEB/'mark-white.svg').read_text(),encoding='utf-8')
    favicon=f'<style>path{{fill:#0A0A0A}}@media(prefers-color-scheme:dark){{path{{fill:#FAFAFA}}}}</style>{symbol}'
    (WEB/'favicon.svg').write_text(svg(favicon,'-8 -8 112 112','#0A0A0A'),encoding='utf-8')
    brand=ROOT/'assets/brand';brand.mkdir(exist_ok=True)
    render((0,0,0,255),(250,250,250,255),256).save(ROOT/'desktop/ClipperStudio/app.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    for suffix,bg,fg in [('black',(0,0,0,255),(250,250,250,255)),('white',(255,255,255,255),(10,10,10,255))]:
        render(bg,fg,1024).save(brand/f'icon-{suffix}.png')
    print('Generated Kairos marks, outlined logos, favicon and Windows icon.')


if __name__=='__main__': main()
