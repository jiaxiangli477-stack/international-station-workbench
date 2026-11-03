"""Build the portable single HTML from already-authorized public dashboard assets."""
from pathlib import Path
import re

def export_single(directory, output):
    root=Path(directory)
    html=(root/'index.html').read_text(encoding='utf-8-sig')
    css=(root/'styles.css').read_text(encoding='utf-8-sig')
    html=re.sub(r'<link[^>]+href="styles\.css[^\"]*"[^>]*>',lambda m:'<style>'+css+'</style>',html)
    # Remove the named dynamic plaintext/encrypted app loader before inlining libraries.
    html,count=re.subn(r'<script>\s*\(function\(\)\{[\s\S]*?function loadApp\([\s\S]*?</script>','',html,count=1)
    if count!=1:
        raise ValueError('未识别面板原有加载器，保留原文件并停止单文件导出')
    for name in ('chart.umd.min.js','dashboard_data.js'):
        js=(root/name).read_text(encoding='utf-8-sig').replace('</script','<\\/script')
        html,n=re.subn(r'<script src="'+re.escape(name)+r'[^\"]*"></script>',lambda m:'<script>'+js+'</script>',html)
        if n!=1:raise ValueError('缺少单文件导出的固定资源：'+name)
    app=(root/'app.js').read_text(encoding='utf-8-sig').replace('</script','<\\/script')
    html=html.replace('</body>','<script>'+app+'</script>\n</body>')
    html=html.replace('<button class="btn">改密码</button>','').replace('<button class="btn">退出</button>','')
    output=Path(output);output.write_text(html,encoding='utf-8')
    return output
