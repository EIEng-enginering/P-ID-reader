"""Explicit public-weight setup command. Inference never calls this module."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile
from .core import digest,verify_model

CATALOG={
 'trocr':dict(repo='microsoft/trocr-small-printed',revision='04e994ab854b0089d4929f48c2b4dbe2ce78a340',
              files=['README.md','config.json','generation_config.json','model.safetensors','preprocessor_config.json',
                     'sentencepiece.bpe.model','special_tokens_map.json','tokenizer_config.json'],
              license_note='Model card has no explicit license field at inspection; local evaluation only, distribution terms unresolved.'),
 'rfdetr':dict(repo='dimtri009/rfdetr-pid-detector',revision='bc41b7c6c2dfe8b05e91842b53a45c4af6e419c6',
               files=['README.md','checkpoint_best_total.pth'],license_note='Model card declares Apache-2.0; retain upstream notices.')}
EASY=[('craft_mlt_25k.pth','https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip','2f8227d2def4037cdb3b34389dcf9ec1'),
      ('english_g2.pth','https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip','5864788e1821be9e454ec108d61b887d')]
# Exact published IDs retained, including spelling and duplicate classes.
CLASSES=['Not_used', 'Gate_Valve', 'Ball_Valve', 'Globe_valve_NO', 'Gate_valve_NO', 'Globe_valve_NO', 'Butterfly_valve', 'Plug_valve', 'Check_valve', 'Diaphragm_valve', 'Needle_valve', 'Half_Filled_Gate_Valve', 'Gate_Valve_NC', 'Globle_valve_NC', 'Control_Valve', 'Rotary_Valve', 'Ball_valve_NC', 'Paddle_blind', 'Spectacle_blind_Closed', 'Spectacle_blind_Open', 'Reducer', 'Flange_or_Nozzle', 'Rupture_disk', 'Pipe_Insulation_or_Tracing', 'Flow_Arrow', 'Sight_glass', 'Instrument_Field', 'Instrument_Field', 'Instrument_Panel', 'Instrument_Aux_Panel', 'Box', 'Instrument_Panel', 'Box']

def fetch(url,path):
    req=urllib.request.Request(url,headers={'User-Agent':'PIDReader-model-provision/1'})
    with urllib.request.urlopen(req,timeout=60) as source,open(path,'wb') as dest:shutil.copyfileobj(source,dest,1024*1024)

def provision(engine,destination):
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=True)
    root=dest/engine;manifest_path=dest/(engine+'.manifest.json')
    if root.exists() or manifest_path.exists():
        if not manifest_path.exists():raise ValueError('Existing model directory has no manifest; choose another destination')
        manifest=json.loads(manifest_path.read_text(encoding='utf8'));verify_model(manifest);return manifest_path
    with tempfile.TemporaryDirectory(prefix='pid-provision-',dir=dest) as tmp:
        stage=Path(tmp)/engine;stage.mkdir()
        if engine=='easyocr':
            for filename,url,expected in EASY:
                archive=Path(tmp)/(filename+'.zip');fetch(url,archive)
                with zipfile.ZipFile(archive) as z:
                    # Read the named entry only, never extract paths from an archive.
                    data=z.read(filename)
                if hashlib.md5(data).hexdigest()!=expected:raise ValueError('Upstream EasyOCR checksum mismatch')
                (stage/filename).write_bytes(data)
            fetch('https://raw.githubusercontent.com/JaidedAI/EasyOCR/v1.7.2/LICENSE',stage/'LICENSE')
            source='https://github.com/JaidedAI/EasyOCR';revision='EasyOCR-1.7.2 + named pre-v1.1.6/v1.3 weight releases'
            note='EasyOCR source Apache-2.0; CRAFT attribution required; retain LICENSE and exact release URLs.'
        else:
            spec=CATALOG[engine];source='https://huggingface.co/'+spec['repo'];revision=spec['revision'];note=spec['license_note']
            for filename in spec['files']:fetch(source+'/resolve/'+revision+'/'+filename,stage/filename)
        manifest=dict(engine=engine,model_dir=str(root),source_url=source,revision=revision,license_note=note,
                      files={str(p.relative_to(stage)):digest(p) for p in stage.rglob('*') if p.is_file()})
        if engine=='rfdetr':manifest.update(checkpoint='checkpoint_best_total.pth',classes={str(i):v for i,v in enumerate(CLASSES)})
        shutil.move(str(stage),root)
        manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf8')
    verify_model(manifest);return manifest_path

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Explicit setup: downloads public weights only; sends no drawings.')
    p.add_argument('engine',choices=['easyocr','trocr','rfdetr']);p.add_argument('destination',type=Path);a=p.parse_args()
    print(provision(a.engine,a.destination))
