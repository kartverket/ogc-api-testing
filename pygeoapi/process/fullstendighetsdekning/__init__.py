import logging
import json
from jsonschema import validate
from osgeo import ogr, osr, gdal
from py_linq import Enumerable
from os import path
from dateutil.parser import parse
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError


gdal.UseExceptions()
LOGGER = logging.getLogger(__name__)

PROCESS_METADATA = {
    'version': '0.1.0',
    'id': 'fullstendighetsdekning',
    'title': {
        'no': 'Fullstendighetsdekning'
    },
    'description': {
        'no': 'Tjeneste som viser fullstendighetsdekningen til et utvalg forskjellige datasett, basert på et geografisk punkt.',
    },
    'keywords': [
        'Fullstendighetsdekning',
        'Dekningskart'
    ],
    'links': [],
    'inputs': {
        'datasets': {
            'title': 'Datasett',
            'description': 'En liste med datasettnavn. Hvis listen er tom, sjekkes spørringen mot alle tilgjengelige datasett.',
            'schema': {
                'type': 'array',
                'items': {
                    'type': 'string'
                }
            },
            'minOccurs': 1,
            'maxOccurs': 1,
            'metadata': None,
            'keywords': []
        },
        'geometry': {
            'title': 'Geometri',
            'description': 'Et punkt i GeoJSON-format (WGS 84).',
            'schema': {
                'type': 'object',
                'contentMediaType': 'application/json'
            },
            'minOccurs': 1,
            'maxOccurs': 1,
            'metadata': None,
            'keywords': []
        }
    },
    'outputs': {
        'fullstendighetsdekning_response': {
            'title': 'fullstendighetsdekning_response',
            'schema': {
                'type': 'object',
                'contentMediaType': 'application/json'
            }
        }
    },
    'example': {
        'inputs': {
            'datasets': [
                'dekningkvikkleire',
                'dekninglosmasser'
            ],
            'geometry': {
                'type': 'Point',
                'coordinates': [
                    7.1,
                    62.69
                ]
            }
        }
    }
}


def get_data_source():
    config = load_config()
    db_config = config['database']

    connString = 'PG: host=%s dbname=%s user=%s password=%s' % (
        db_config['server'], db_config['name'], db_config['username'], db_config['password'])

    return ogr.Open(connString)


def get_coverage(data_source, geojson, datasets):
    if not datasets is None and datasets.any():
        config = load_config()

        layer_names = get_layer_names(data_source) \
            .where(lambda layer_name: datasets
                   .any(lambda name: config['layer_name_prefix'] + '.' + name == layer_name))
    else:
        layer_names = get_layer_names(data_source)

    if not layer_names.any():
        return {
            'type': 'Feature',
            'geometry': geojson,
            'properties': {
                'coverages': []
            }
        }

    geometry = ogr.CreateGeometryFromJson(str(geojson))
    reproject_geometry(geometry)

    feature_tuples = Enumerable([])

    for layer_name in layer_names:
        layer = data_source.GetLayer(layer_name)

        for feature in layer:
            geom = feature.GetGeometryRef()

            if geom.Intersects(geometry):
                feature_tuples.append((layer_name, feature))
                break

    coverages = feature_tuples \
        .select(lambda tuple: create_response_json(tuple)) \
        .to_list()

    return {
        'type': 'Feature',
        'geometry': geojson,
        'properties': {
            'coverages': coverages
        }
    }


def create_response_json(feature_tuple):
    if feature_tuple is None:
        return None

    feature = feature_tuple[1]
    dekningstatus = feature.GetField('dekningnavn')

    if dekningstatus is None:
        dekningstatus = feature.GetField('dekningstatus')

    return {
        'layer': feature_tuple[0].split('.')[1],
        'layerName': feature.GetField('datasettnavn'),
        'coverageStatus': dekningstatus,
        'lastUpdated': parse_date(feature.GetField('oppdateringsdato'))
    }


def reproject_geometry(geometry):
    config = load_config()
    epsg_config = config['epsg']

    source = osr.SpatialReference()
    source.ImportFromEPSG(epsg_config['source'])

    target = osr.SpatialReference()
    target.ImportFromEPSG(epsg_config['target'])

    transform = osr.CoordinateTransformation(source, target)
    geometry.Transform(transform)


def get_layer_names(data_source):
    layer_names = []

    for layer in data_source:
        layer_name = layer.GetName()

        if not layer_name in layer_names:
            layer_names.append(layer_name)

    layer_names.sort()

    return Enumerable(layer_names)


def parse_date(date_string):
    try:
        date = parse(date_string)
        return date.strftime("%Y-%m-%dT%H:%M:%S.%f")
    except:
        return date_string


def load_config():
    dir_path = path.dirname(path.realpath(__file__))
    file_path = path.join(dir_path, 'resources/config.json')

    with open(file_path, 'r') as file:
        return json.load(file)


def request_is_valid(data):
    dir_path = path.dirname(path.realpath(__file__))
    file_path = path.join(dir_path, 'resources/coverage_request.schema.json')

    with open(file_path, 'r') as file:
        schema = json.load(file)

    try:
        validate(instance=data, schema=schema)
        return True
    except:
        return False


class FullstendighetsdekningProcessor(BaseProcessor):

    def __init__(self, processor_def):
        super().__init__(processor_def, PROCESS_METADATA)

    def execute(self, data):
        mimetype = 'application/json'

        if not request_is_valid(data):
            raise ProcessorExecuteError('Invalid payload')

        datasets = None

        if 'datasets' in data:
            datasets = Enumerable(data.get('datasets'))

        data_source = get_data_source()
        outputs = get_coverage(data_source, data.get('geometry'), datasets)
        data_source = None

        return mimetype, outputs

    def __repr__(self):
        return '<FullstendighetsdekningProcessor> {}'.format(self.name)
