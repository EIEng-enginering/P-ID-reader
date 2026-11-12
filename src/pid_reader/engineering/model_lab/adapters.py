"""Lazy optional backends; all assets supplied locally. Never imported at startup."""

import hashlib
import json

_MODELS={}
# Measured on Windows (S418, 2020x1633 tile): EasyOCR/CRAFT peaked at 7.7 GiB on 3.3 Mpx and 3.5 GiB on 1.2 Mpx, on a 15.8 GiB machine.
# The input is therefore bounded; boxes are mapped back to the full crop so downstream coordinates are unchanged.
EASYOCR_MAX_PIXELS=1_300_000

def clip_xyxy(box,size):
    """Clip a model box to the crop it was read from. Detectors and polygon text finders may overshoot the edge by a pixel or
    more; that is geometry noise, not a reason to lose the whole crop. Boxes with no visible area are dropped (None)."""
    w,h=size
    x0,y0,x1,y1=(float(v) for v in box)
    x0,x1=max(0.0,min(x0,x1)),min(float(w),max(x0,x1))
    y0,y1=max(0.0,min(y0,y1)),min(float(h),max(y0,y1))
    if x1-x0<1.0 or y1-y0<1.0:return None
    return [x0,y0,x1,y1]

def infer(engine, image, root, manifest):
    key=(engine,str(root),hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())
    if engine=='easyocr':
        import easyocr
        import numpy as np
        if key not in _MODELS:
            _MODELS[key]=easyocr.Reader(['en'],gpu=False,model_storage_directory=str(root),
                                      download_enabled=False,verbose=False)
        reader=_MODELS[key]
        factor=1.0;source=image
        if image.width*image.height>EASYOCR_MAX_PIXELS:
            factor=(EASYOCR_MAX_PIXELS/(image.width*image.height))**.5
            source=image.resize((max(1,int(image.width*factor)),max(1,int(image.height*factor))))
        rows=reader.readtext(np.asarray(source),detail=1,paragraph=False)
        out=[]
        for poly,text,score in rows:
            box=clip_xyxy([min(p[0] for p in poly)/factor,min(p[1] for p in poly)/factor,max(p[0] for p in poly)/factor,max(p[1] for p in poly)/factor],image.size)
            if box is not None and str(text).strip():out.append(dict(kind='TEXT',text=text,score=float(score),xyxy=box))
        return out
    if engine=='trocr':
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        torch.set_num_threads(2)
        if key not in _MODELS:
            processor=TrOCRProcessor.from_pretrained(str(root),local_files_only=True,use_fast=False)
            torch.manual_seed(0)
            model=VisionEncoderDecoderModel.from_pretrained(str(root),local_files_only=True,
                                                            use_safetensors=True).to('cpu').eval()
            _MODELS[key]=(processor,model)
        processor,model=_MODELS[key]
        with torch.inference_mode():
            ids=model.generate(processor(images=image,return_tensors='pt').pixel_values,max_new_tokens=96)
        text=processor.batch_decode(ids,skip_special_tokens=True)[0]
        # TrOCR does not localize individual words or supply calibrated confidence.
        return [dict(kind='TEXT',text=text,score=None,xyxy=[0,0,*image.size])]
    if engine=='rfdetr':
        from rfdetr import RFDETRBase
        if key not in _MODELS:
            _MODELS[key]=RFDETRBase(pretrain_weights=str(root/manifest['checkpoint']),device='cpu')
        model=_MODELS[key]
        detections=model.predict(image,threshold=.5)
        rows=[]
        for box,cid,score in zip(detections.xyxy,detections.class_id,detections.confidence):
            cid=int(cid)
            clipped=clip_xyxy(box,image.size)
            if clipped is None:continue
            rows.append(dict(kind='SYMBOL',xyxy=clipped,score=float(score),
                             class_id=cid,class_name=manifest['classes'].get(str(cid),'UNMAPPED')))
        return rows
    raise ValueError('Unsupported model')
