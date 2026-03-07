# =================================================================

# Authors: Tom Kralidis <tomkralidis@gmail.com>
#
# Copyright (c) 2026 Tom Kralidis
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
# =================================================================

from copy import deepcopy
from http import HTTPStatus
import logging
from typing import Tuple

from . import APIRequest, API
from pygeoapi.plugin import load_plugin
from pygeoapi.provider import get_provider_by_type
from pygeoapi.util import render_j2_template

LOGGER = logging.getLogger(__name__)

CONFORMANCE_CLASSES = [
    'http://www.opengis.net/spec/wms/1.0'
]


DEFAULT_CRS = 'http://www.opengis.net/def/crs/EPSG/0/4326'


def wms(api: API, request: APIRequest) -> Tuple[dict, int, str]:
    """
    WMS shim

    :param request: A request object

    :returns: tuple of headers, status code, content
    """

    locator = None
    tpl_config = api.tpl_config['server']['templates']

    headers = request.get_response_headers(**api.api_headers)
    headers['Content-Type'] = 'application/xml'

    LOGGER.debug('Parsing basic service options')

    service = request.params.get('service')
    version = request.params.get('version')
    request_ = request.params.get('request')

    if None in [service, version, request_]:
        response = _get_exception(
            api.tpl_config,
            request.locale,
            tpl_config,
            'MissingParameterValue',
            None,
            'Missing required service/version/request parameters'
        )
        return headers, HTTPStatus.OK, response

    if service != 'WMS':
        locator = 'service'
    if version != '1.3.0':
        locator = 'version'
    if request_ not in ['GetCapabilities', 'GetMap']:
        locator = 'request'

    if locator is not None:
        response = _get_exception(
            api.tpl_config,
            request.locale,
            tpl_config,
            'InvalidParameterValue',
            locator,
            f"Invalid {locator} parameter"
        )
        return headers, HTTPStatus.OK, response

    if request_ == 'GetCapabilities':
        media_type, response = _getcapabilities(api, request)

    if request_ == 'GetMap':
        media_type, response = _getmap(api, request)
        headers['Content-Type'] = media_type

    return headers, HTTPStatus.OK, response


def _getcapabilities(api, request) -> Tuple[str, bytes]:

    tpl_config = api.tpl_config['server']['templates']

    data = {
        'config': api.config,
        'layers': []
    }

    for key, value in api.config['resources'].items():
        LOGGER.debug('Loading provider')
        try:
            collection_def = get_provider_by_type(
                api.config['resources'][key]['providers'], 'map')

            _ = load_plugin('provider', collection_def)

            layer_info = {
                'title': value['title'],
                'abstract': value['description'],
                'spatial': value['extents']['spatial'],
                'temporal': value['extents'].get('temporal')
            }
            data['layers'].append(layer_info)
        except Exception as err:
            LOGGER.debug(f'Cannot generate map collection {key}: {err}')

    print("DATA", data['layers'])
    return ('application/xml',
            render_j2_template(
                api.tpl_config, tpl_config,
                'wms-capabilities.xml',
                data, request.locale))


def _getmap(api, request) -> Tuple[str, bytes]:
    tpl_config = api.tpl_config['server']['templates']
    required_getmap_params = [
        'layers',
        'bbox',
        'crs',
        'styles',
        'width',
        'height',
        'format',
    ]
    for rgp in required_getmap_params:
        if request.params.get(rgp) is None:
            return 'application/xml', _get_exception(
                api.tpl_config,
                request.locale,
                api.tpl_config,
                'MissingParameterValue',
                rgp,
                f"Missing {rgp} parameter"
            )

    if request.params['layers'] not in api.config['resources'].keys():
        response = _get_exception(
            api.tpl_config,
            request.locale,
            tpl_config,
            'InvalidParameterValue',
            'layers',
            'Invalid layers parameter'
        )
        return 'application/xml', response

    try:
        collection_def = get_provider_by_type(
            api.config['resources'][request.params['layers']]['providers'],
            'map')

        p = load_plugin('provider', collection_def)
    except Exception as err:
        LOGGER.debug(err)
        response = _get_exception(
            api.tpl_config,
            request.locale,
            tpl_config,
            'NoApplicableCode',
            'layers',
            'layer not configured for maps'
        )
        return 'application/xml', response

        LOGGER.debug(f'Cannot generate map collection: {err}')

    print("BBOX", request.params['bbox'])
    bbox2 = [float(b) for b in request.params['bbox'].split(',')]
    print("BBOX2", bbox2)
    map_bytes = p.query(
        width=request.params['width'],
        height=request.params['height'],
        bbox=bbox2
    )

    return 'image/png', map_bytes


def _get_exception(api_tpl_config, request_locale, tpl_config, code: str,
                   locator: str | None, exception: str) -> str:

    data = {
        'code': code,
        'locator': locator,
        'exception': exception
    }

    return render_j2_template(api_tpl_config, tpl_config, 'wms-exception.xml',
                              data, request_locale)


def get_oas_30(cfg: dict, locale: str) -> tuple[list[dict[str, str]], dict[str, dict]]:  # noqa
    """
    Get OpenAPI fragments

    :param cfg: `dict` of configuration
    :param locale: `str` of locale

    :returns: `tuple` of `list` of tag objects, and `dict` of path objects
    """

    LOGGER.debug('setting up WMS endpoint')

    paths = {}

    paths['/wms'] = {
        'get': {
            'summary': 'WMS endpoint',
            'description': 'WMS endpoint',
            'tags': ['wms'],
            'operationId': 'wms',
            'parameters': [{
                'name': 'service',
                'in': 'query',
                'description': 'OGC service type',
                'required': True,
                'schema': {
                    'type': 'string',
                    'enum': [
                        'WMS'
                    ]
                }}, {
                'name': 'version',
                'in': 'query',
                'description': 'WMS version',
                'required': True,
                'schema': {
                    'type': 'string',
                    'enum': [
                        '1.3.0'
                    ]
                }}, {
                'name': 'request',
                'in': 'query',
                'description': 'Request operation',
                'required': True,
                'schema': {
                    'type': 'string',
                    'enum': [
                        'GetCapabilities'
                    ]
                }
            }],
            'responses': {
                '200': {
                    'description': 'Response',
                    'content': {
                        'application/xml': {}
                    }
                }
            }
        }
    }

    paths['/wms/map'] = {
        'get': {
            'summary': 'WMS GetMap endpoint',
            'description': 'WMS GetMap endpoint',
            'tags': ['wms'],
            'operationId': 'wmsGetMap',
            'parameters': [{
                'name': 'request',
                'in': 'query',
                'description': 'Request operation',
                'required': True,
                'schema': {
                    'type': 'string',
                    'enum': [
                        'GetMap'
                    ]
                }}, {
                'name': 'layers',
                'in': 'query',
                'explode': False,
                'description': 'layers',
                'required': True,
                'schema': {
                    'type': 'array',
                    'minItems': 1,
                    'items': {
                        'type': 'string'
                    }
                }}, {
                'name': 'bbox',
                'in': 'query',
                'explode': False,
                'description': 'WMS bbox',
                'required': True,
                'schema': {
                    'type': 'array',
                    'minItems': 4,
                    'maxItems': 4,
                    'items': {
                        'type': 'number'
                    }
                }}, {
                'name': 'crs',
                'in': 'query',
                'description': 'WMS crs',
                'required': True,
                'schema': {
                    'type': 'string',
                    'default': 'EPSG:4326'
                }}, {
                'name': 'width',
                'in': 'query',
                'description': 'WMS width',
                'required': True,
                'schema': {
                    'type': 'integer',
                    'default': 800
                }}, {
                'name': 'height',
                'in': 'query',
                'description': 'WMS height',
                'required': True,
                'schema': {
                    'type': 'integer',
                    'default': 600
                }}, {
                'name': 'format',
                'in': 'query',
                'description': 'WMS format',
                'explode': False,
                'required': True,
                'schema': {
                    'type': 'string',
                    'default': 'image/png'
                }}, {
                'name': 'styles',
                'in': 'query',
                'description': 'WMS styles',
                'explode': False,
                'required': True,
                'schema': {
                    'type': 'array',
                    'items': {
                        'type': 'string'
                    },
                    'default': 'default'
                }
            }],
            'responses': {
                '200': {
                    'description': 'Response',
                    'content': {
                        'image/png': {}
                    }
                }
            }
        }
    }

    wms_map_get_parameters = deepcopy(paths['/wms']['get']['parameters'])
    wms_map_get_parameters.pop()

    paths['/wms/map']['get']['parameters'] = wms_map_get_parameters + \
        paths['/wms/map']['get']['parameters']

    return [{'name': 'wms'}], {'paths': paths}
