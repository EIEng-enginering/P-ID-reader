"""Rev N - training-free, project-configurable vector symbol catalogue.

This standalone interpretation layer makes *candidate* symbol classifications
using already-verifiable vector source evidence.  It neither downloads nor
trains models, does not expand the Worksheet R1 extraction output, and never
asserts a plant component, actuator function, protection layer or SIL.

The catalogue is a constrained declarative profile, not executable Python or
user-supplied regular expressions. No inference is made for a missing symbol.
"""
from __future__ import annotations

import re
from math import hypot, isfinite

from ..api import canonical_json, result_sha256, sha256_hex, stable_id
from .topology import validate_topology_result
from .symbols import validate_symbol_proposals
from .linework import validate_linework_proposals

SCHEMA = 'pid-reader-standalone-catalog-v1'
RESULT_SCHEMA = 'pid-reader-standalone-catalog-analysis-v1'
ALGORITHM = 'conservative-vector-template-matching-0.1'
FEATURES = {'TAGGED_OUTLINE', 'BOWTIE_VALVE', 'BOWTIE_STEM_CIRCLE'}
SHAPES = {'CLOSED_NEAR_CIRCULAR_OUTLINE', 'RECTANGULAR_OUTLINE'}
R1_CLASSES = {'VESSEL', 'TANK', 'COLUMN', 'HEAT_EXCHANGER', 'PUMP',
              'COMPRESSOR', 'FILTER', 'VALVE_MANUAL', 'VALVE_CONTROL',
              'VALVE_ONOFF', 'VALVE_CHECK', 'PSV', 'RUPTURE_DISC',
              'INSTRUMENT', 'OTHER', 'UNKNOWN'}
MAX_TEMPLATES = 128
MAX_INTERPRETATIONS = 20000
IDENT = re.compile(r'^[A-Z][A-Z0-9_]{2,63}$')
KEY = re.compile(r'^[a-z][a-z0-9-]{2,63}$')


def example_catalog() -> dict:
    """Synthetic original, licence-safe conservative starter patterns.

    The catalogue may be changed per project; adding an entry is NOT model
    training or evidence of actual classification accuracy.
    """
    entries = [
        ('instrument-bubble', 'INSTRUMENT', 'CLOSED_NEAR_CIRCULAR_OUTLINE', 'INSTRUMENT_BUBBLE_STYLE'),
        ('pump-circle-tagged', 'PUMP', 'CLOSED_NEAR_CIRCULAR_OUTLINE', 'PUMP_CIRCULAR_OUTLINE_STYLE'),
        ('pump-rect-tagged', 'PUMP', 'RECTANGULAR_OUTLINE', 'PUMP_RECTANGULAR_OUTLINE_STYLE'),
        ('vessel-rect-tagged', 'VESSEL', 'RECTANGULAR_OUTLINE', 'VESSEL_RECTANGULAR_OUTLINE_STYLE'),
        ('tank-rect-tagged', 'TANK', 'RECTANGULAR_OUTLINE', 'TANK_RECTANGULAR_OUTLINE_STYLE'),
        ('column-rect-tagged', 'COLUMN', 'RECTANGULAR_OUTLINE', 'COLUMN_RECTANGULAR_OUTLINE_STYLE'),
        ('compressor-rect-tagged', 'COMPRESSOR', 'RECTANGULAR_OUTLINE', 'COMPRESSOR_RECTANGULAR_OUTLINE_STYLE'),
        ('exchanger-rect-tagged', 'HEAT_EXCHANGER', 'RECTANGULAR_OUTLINE', 'EXCHANGER_RECTANGULAR_OUTLINE_STYLE'),
        ('filter-rect-tagged', 'FILTER', 'RECTANGULAR_OUTLINE', 'FILTER_RECTANGULAR_OUTLINE_STYLE'),
    ]
    templates=[{'template_id': key, 'feature': 'TAGGED_OUTLINE',
                'candidate_class': classification, 'outline_shape': shape,
                'source_classes': [source]} for key, source, shape, classification in entries]
    templates += [
        {'template_id': 'bowtie-six-stroke', 'feature': 'BOWTIE_VALVE',
         'candidate_class': 'GENERIC_BOWTIE_VALVE_STYLE'},
        {'template_id': 'bowtie-with-stem-circle', 'feature': 'BOWTIE_STEM_CIRCLE',
         'candidate_class': 'VALVE_WITH_STEM_CIRCLE_STYLE'}]
    return {'schema': SCHEMA, 'catalogue_name': 'Synthetic generic vector templates',
            'revision': '1', 'licence': 'Original synthetic definitions',
            'templates': templates}


def validate_catalog(catalog: dict) -> list[str]:
    errors=[]
    if not isinstance(catalog, dict):
        return ['Catalogue must be a JSON object']
    if set(catalog) != {'schema', 'catalogue_name', 'revision', 'licence', 'templates'}:
        errors.append('Unknown or missing catalogue field')
    if catalog.get('schema') != SCHEMA:
        errors.append('Unsupported catalogue schema')
    for key, maximum in (('catalogue_name', 120), ('revision', 50), ('licence', 180)):
        v=catalog.get(key)
        if not isinstance(v, str) or not v.strip() or len(v)>maximum:
            errors.append('Invalid catalogue '+key)
    templates=catalog.get('templates')
    if not isinstance(templates, list) or not 1<=len(templates)<=MAX_TEMPLATES:
        return errors+['Catalogue must have 1-128 templates']
    ids=set()
    for index, t in enumerate(templates):
        if not isinstance(t,dict):
            errors.append(f'Template {index} is not an object');continue
        feature=t.get('feature')
        expected={'template_id','feature','candidate_class'}
        if feature=='TAGGED_OUTLINE':
            expected|={'outline_shape','source_classes'}
        if set(t) != expected:
            errors.append(f'Template {index} has extra/missing fields')
        key=t.get('template_id')
        if not isinstance(key,str) or not KEY.fullmatch(key) or key in ids:
            errors.append(f'Invalid or duplicate template key at {index}')
        ids.add(key)
        cls=t.get('candidate_class')
        if not isinstance(cls,str) or not IDENT.fullmatch(cls):
            errors.append(f'Invalid candidate class at {index}')
        if feature not in FEATURES:
            errors.append(f'Unsupported feature at {index}')
        if feature=='TAGGED_OUTLINE':
            classes=t.get('source_classes')
            if t.get('outline_shape') not in SHAPES:
                errors.append(f'Unsupported outline shape at {index}')
            if (not isinstance(classes,list) or not 1<=len(classes)<=len(R1_CLASSES)
                    or not all(isinstance(c,str) for c in classes)
                    or len(classes)!=len(set(map(str,classes)))
                    or any(isinstance(c,str) and c not in R1_CLASSES for c in classes)):
                errors.append(f'Invalid permitted source classes at {index}')
    return errors


def _near(a, b, tol=0.006):
    return hypot(a[0]-b[0],a[1]-b[1])<=tol


def _circle_on_stem(valve: dict, circle: dict, seg: dict) -> bool:
    """Only detects a shaft between a valve centre and untagged circle edge.

    Geometry is in the *normalised drawing frame*, so tolerances are conservative
    and deliberately bounded; dense/non-square drawings may need future tuning.
    """
    if valve['page']!=circle['page'] or valve['page']!=seg['page']:
        return False
    if seg.get('style')!='SOLID_OR_UNKNOWN' or seg['id'] in valve['evidence_segment_ids']:
        return False
    box=circle['bbox']
    cx=(box['x0']+box['x1'])/2
    cy=(box['y0']+box['y1'])/2
    rx=(box['x1']-box['x0'])/2
    ry=(box['y1']-box['y0'])/2
    if not (.006<=min(rx,ry) <=.075) or max(rx,ry)>2*min(rx,ry):
        return False
    vx,vy=valve['centre']
    if valve['orientation']=='HORIZONTAL_AXIS':
        if abs(cx-vx)>.007 or abs(cy-vy)<.020 or abs(cy-vy)>.25:return False
    elif valve['orientation']=='VERTICAL_AXIS':
        if abs(cy-vy)>.007 or abs(cx-vx)<.020 or abs(cx-vx)>.25:return False
    else:
        return False
    for valve_end,circle_end in ((seg['endpoints'][0],seg['endpoints'][1]),
                                (seg['endpoints'][1],seg['endpoints'][0])):
        if not _near(valve_end,[vx,vy],.008):continue
        if not (box['x0']-.004<=circle_end[0]<=box['x1']+.004 and box['y0']-.004<=circle_end[1]<=box['y1']+.004):continue
        rho=hypot((circle_end[0]-cx)/rx, (circle_end[1]-cy)/ry)
        if not (.72<=rho<=1.28):continue
        if valve['orientation']=='HORIZONTAL_AXIS':
            if abs(valve_end[0]-circle_end[0])>.008:continue
        else:
            if abs(valve_end[1]-circle_end[1])>.008:continue
        return True
    return False


def build_catalog_analysis(extraction:dict, topology:dict, symbols:dict, linework:dict, catalog:dict) -> dict:
    problems=validate_catalog(catalog)
    if problems:raise ValueError('Invalid catalogue: '+'; '.join(problems[:3]))
    if not isinstance(extraction,dict) or extraction.get('provenance',{}).get('result_sha256')!=result_sha256(extraction):
        raise ValueError('R1 source extraction hash mismatch')
    if validate_topology_result(topology) or validate_symbol_proposals(symbols,extraction,topology) or validate_linework_proposals(linework,extraction,topology,symbols):
        raise ValueError('Source vector evidence cannot be validated')
    sha=extraction['document']['sha256']
    if any(x['source_sha256']!=sha for x in (topology,symbols,linework)):
        raise ValueError('Source PDF hashes disagree')
    catalog_sha=sha256_hex(canonical_json(catalog).encode('utf-8'))
    template_order=sorted(catalog['templates'],key=lambda t:t['template_id'])
    object_by_id={o['id']:o for o in extraction['objects']}
    shape_by_id={s['id']:s for s in topology['shape_candidates']}
    symbol_by_shape={x['shape_id']:x for x in symbols['symbol_candidates']}
    segments_by_page={}
    for seg in topology['segments']:
        segments_by_page.setdefault(seg['page'],[]).append(seg)
    interpretations=[]
    for template in template_order:
        feature=template['feature']
        if feature=='TAGGED_OUTLINE':
            for symbol in symbols['symbol_candidates']:
                if symbol['outline_kind'] != template['outline_shape'] or len(symbol['tag_object_ids'])!=1:
                    continue
                obj=object_by_id[symbol['tag_object_ids'][0]]
                if obj['class'] not in template['source_classes']:continue
                evidence={'symbol_id': symbol['id'], 'shape_id':symbol['shape_id'],
                          'tag_object_id':obj['id']}
                interpretations.append((template,symbol['page'],symbol['bbox'],evidence,'TAG_AND_OUTLINE'))
        elif feature=='BOWTIE_VALVE':
            for valve in linework['valve_candidates']:
                evidence={'valve_id':valve['id'],'stroke_ids':valve['evidence_segment_ids']}
                interpretations.append((template,valve['page'],valve['bbox'],evidence,'SIX_STROKE_GLYPH'))
        elif feature=='BOWTIE_STEM_CIRCLE':
            for valve in linework['valve_candidates']:
                for symbol in symbols['symbol_candidates']:
                    shape=shape_by_id[symbol['shape_id']]
                    if (shape['shape']!='CLOSED_NEAR_CIRCULAR_OUTLINE'
                            or symbol['tag_object_ids']):
                        continue
                    for seg in segments_by_page.get(valve['page'],[]):
                        if _circle_on_stem(valve,shape,seg):
                            coords=[valve['bbox'],shape['bbox']]
                            box={k:round((min if k in ('x0','y0') else max)(v[k] for v in coords),7)
                                 for k in ('x0','y0','x1','y1')}
                            evidence={'valve_id':valve['id'],'actuator_shape_id':shape['id'],
                                      'stem_segment_id':seg['id']}
                            interpretations.append((template,valve['page'],box,evidence,'VALVE_CIRCLE_STEM_COMBINATION'))
    # A catalogue entry is not automatically accepted, and score is NOT calibrated.
    predictions=[];seen=set()
    for template,page,box,evidence,basis in interpretations:
        cid=stable_id('catalog-candidate',sha,catalog_sha,template['template_id'],evidence)
        if cid in seen:continue
        seen.add(cid)
        predictions.append({'id':cid,'page':page,'bbox':box,'template_id':template['template_id'],
           'candidate_class':template['candidate_class'],'basis':basis,'evidence':evidence,
           'state':'PROPOSED_UNVERIFIED',
           'limitations':'Symbol template/style match on drawing only; not proven equipment or valve function.'})
        if len(predictions)>MAX_INTERPRETATIONS:
            raise ValueError('Catalogue analysis candidate budget exceeded')
    predictions.sort(key=lambda item:(item['page'],item['id']))
    result={'schema':RESULT_SCHEMA,'algorithm':ALGORITHM,'source_sha256':sha,
            'extraction_sha256':extraction['provenance']['result_sha256'],
            'topology_sha256':topology['result_sha256'],
            'symbol_sha256':symbols['result_sha256'],
            'linework_sha256':linework['result_sha256'], 'catalogue_sha256':catalog_sha,
            'catalogue_name':catalog['catalogue_name'],'catalogue_revision':catalog['revision'],
            'candidates':predictions,
            'limitations':('Training-free vector and tag matching only; no model was trained or executed. '
               'Templates do not validate physical equipment identity, plant state, signal function, IPL or SIL.')}
    result['result_sha256']=sha256_hex(canonical_json(result).encode('utf-8'))
    return result


def validate_catalog_analysis(result:dict,extraction:dict,topology:dict,symbols:dict,linework:dict,catalog:dict)->list[str]:
    """Recompute from source evidence, not merely a re-hashable result document."""
    try:
        expected=build_catalog_analysis(extraction,topology,symbols,linework,catalog)
        return [] if expected==result else ['Catalogue proposals differ from source-derived reproducible result']
    except (ValueError,TypeError,KeyError,IndexError,OverflowError) as e:
        return ['Catalogue evidence cannot be validated: '+str(e)[:130]]
