# -*- coding: utf-8 -*-
"""SAM 2.1(hiera-tiny, Apache-2.0, Meta) 작업자. 별도 환경(.venv_sam, torch CPU)에서만 돈다. 하네스 본체는 이 파일을 부르기만 한다.
입력: <in.npz>(image: 행·열·RGB uint8) + <prompts.json>([{"id", "box": [x0,y0,x1,y1], "pos": [[x,y],...], "neg": [[x,y],...]}])
출력: <out.npz>(id 마다 bool 마스크). 실행: .venv_sam/Scripts/python.exe tools/sam_worker.py in.npz prompts.json out.npz
"""
import json
import sys

import numpy as np
import torch
from PIL import Image
from transformers import Sam2Model, Sam2Processor

MODEL = 'facebook/sam2.1-hiera-tiny'


def main(inp, pp, outp):
    img = Image.fromarray(np.load(inp)['image'])
    prompts = json.load(open(pp, encoding='utf-8'))
    proc = Sam2Processor.from_pretrained(MODEL)
    model = Sam2Model.from_pretrained(MODEL).eval()
    out = {}
    base = proc(images=img, return_tensors='pt')
    with torch.no_grad():
        emb = model.get_image_embeddings(base['pixel_values'])   # 그림 부호화는 한 번만(힌트마다 다시 하면 느림)
    for p in prompts:
        kw = {'images': img, 'return_tensors': 'pt'}
        if p.get('box'):
            kw['input_boxes'] = [[[float(v) for v in p['box']]]]
        pts = [list(map(float, q)) for q in p.get('pos', [])] + [list(map(float, q)) for q in p.get('neg', [])]
        if pts:
            kw['input_points'] = [[pts]]
            kw['input_labels'] = [[[1] * len(p.get('pos', [])) + [0] * len(p.get('neg', []))]]
        inputs = proc(**kw)
        inputs.pop('pixel_values', None)
        with torch.no_grad():
            o = model(image_embeddings=emb, multimask_output=False, **inputs)
        m = proc.post_process_masks(o.pred_masks, inputs['original_sizes'])[0]
        out[str(p['id'])] = np.asarray(m).reshape(-1, *m.shape[-2:])[0].astype(bool)
    np.savez_compressed(outp, **out)
    print('SAM 마스크 %d개' % len(out))


if __name__ == '__main__':
    main(*sys.argv[1:4])
