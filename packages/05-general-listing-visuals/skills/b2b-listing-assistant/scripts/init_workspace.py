"""Issue an independent blank intake folder and ZIP for the user to fill and save."""
import argparse,json,shutil
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

def create(destination):
    destination=Path(destination).resolve()
    if destination.drive.upper() not in ('D:','E:'):raise ValueError('output must be on D: or E:')
    source=Path(__file__).resolve().parents[1]/'assets/intake-folder-template'
    if not source.is_dir():raise FileNotFoundError('blank intake template missing')
    if destination.is_relative_to(source):raise ValueError('cannot write into blank master template')
    archive=destination.parent/(destination.name+'.zip')
    if destination.exists() or archive.exists():raise FileExistsError('choose a new workspace; existing material is not overwritten')
    shutil.copytree(source,destination)
    with ZipFile(archive,'x',ZIP_DEFLATED) as z:
        for file in destination.rglob('*'):
            if file.is_file():z.write(file,Path(destination.name)/file.relative_to(destination))
    with ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('template archive failed CRC check')
    return {'status':'awaiting_user_materials','folder':str(destination),'zip':str(archive),'guide':str(destination/'00-使用说明.html'),'instructions':'Give these concrete links to the user; ask them to fill, add files and save this copy. Do not modify the blank master or treat it as confirmed company data.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args();print(json.dumps(create(a.output),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
