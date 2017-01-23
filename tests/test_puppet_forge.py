# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2017 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, 51 Franklin Street, Fifth Floor, Boston, MA 02110-1335, USA.
#
# Authors:
#     Santiago Dueñas <sduenas@bitergia.com>
#

import datetime
import sys
import unittest

import dateutil.tz
import httpretty
import pkg_resources

# Hack to make sure that tests import the right packages
# due to setuptools behaviour
sys.path.insert(0, '..')
pkg_resources.declare_namespace('perceval.backends')

from perceval.backend import BackendCommandArgumentParser
from perceval.backends.puppet.puppet_forge import (PuppetForge,
                                                   PuppetForgeClient,
                                                   PuppetForgeCommand)


PUPPET_FORGE_URL = 'https://forge.puppet.com/'
PUPPET_FORGE_MODULES_URL = PUPPET_FORGE_URL + 'v3/modules'
PUPPET_FORGE_RELEASES_URL = PUPPET_FORGE_URL + 'v3/releases'


def read_file(filename, mode='r'):
    with open(filename, mode) as f:
        content = f.read()
    return content


def setup_http_server():
    """Setup a mock HTTP server"""

    http_requests = []

    modules_bodies = [
        read_file('data/puppet_forge/puppet_forge_modules.json', 'rb'),
        read_file('data/puppet_forge/puppet_forge_modules_next.json', 'rb')
    ]
    ceph_body =  read_file('data/puppet_forge/puppet_forge_releases_ceph.json', 'rb')
    nomad_body = read_file('data/puppet_forge/puppet_forge_releases_nomad.json', 'rb')
    empty_body = read_file('data/puppet_forge/puppet_forge_empty.json', 'rb')


    def request_callback(method, uri, headers):
        last_request = httpretty.last_request()

        if uri.startswith(PUPPET_FORGE_MODULES_URL):
            body = modules_bodies.pop(0)
        elif uri.startswith(PUPPET_FORGE_RELEASES_URL):
            params = last_request.querystring
            module = params['module'][0]

            if module == 'norisnetwork-ceph':
                body = ceph_body
            elif module == 'sshuyskiy-nomad':
                body = nomad_body
            else:
                body = empty_body
        else:
            raise

        http_requests.append(last_request)

        return (200, headers, body)

    httpretty.register_uri(httpretty.GET,
                           PUPPET_FORGE_MODULES_URL,
                           responses=[
                                httpretty.Response(body=request_callback) \
                                    for _ in range(2)
                           ])
    httpretty.register_uri(httpretty.GET,
                           PUPPET_FORGE_RELEASES_URL,
                           responses=[
                                httpretty.Response(body=request_callback) \
                                    for _ in range(1)
                           ])

    return http_requests


class TestPuppetForgeBackend(unittest.TestCase):
    """Puppet forge backend tests"""

    def test_initialization(self):
        """Test whether attributes are initializated"""

        forge = PuppetForge(max_items=5, tag='test')

        self.assertEqual(forge.origin, 'https://forge.puppet.com/')
        self.assertEqual(forge.tag, 'test')
        self.assertEqual(forge.max_items, 5)
        self.assertIsInstance(forge.client, PuppetForgeClient)

        # When tag is empty or None it will be set to
        # the value in URL
        forge = PuppetForge(max_items=5)
        self.assertEqual(forge.origin, 'https://forge.puppet.com/')
        self.assertEqual(forge.tag, 'https://forge.puppet.com/')

        forge = PuppetForge(max_items=5, tag='')
        self.assertEqual(forge.origin, 'https://forge.puppet.com/')
        self.assertEqual(forge.tag, 'https://forge.puppet.com/')

    def test_has_caching(self):
        """Test if it returns False when has_caching is called"""

        self.assertEqual(PuppetForge.has_caching(), False)

    def test_has_resuming(self):
        """Test if it returns False when has_resuming is called"""

        self.assertEqual(PuppetForge.has_resuming(), False)

    @httpretty.activate
    def test_fetch(self):
        """Test whether it fetches a set of modules"""

        http_requests = setup_http_server()

        forge = PuppetForge(max_items=2)
        modules = [module for module in forge.fetch()]

        expected = [('ceph', 'a7709201e03bfec46e34e4d0065bb8bdc3f4e5b9', 1484906394.0, 2),
                    ('nomad', '2fea1072d8ef4d107839c20b7d9926574c4df587', 1484896006.0, 1),
                    ('consul', '234b9505bf47f2f48f8576a9a906732fe6c06e3c', 1484895908.0, 0)]

        self.assertEqual(len(modules), len(expected))

        for x in range(len(modules)):
            module = modules[x]
            expc = expected[x]
            self.assertEqual(module['data']['name'], expc[0])
            self.assertEqual(module['uuid'], expc[1])
            self.assertEqual(module['origin'], 'https://forge.puppet.com/')
            self.assertEqual(module['updated_on'], expc[2])
            self.assertEqual(module['category'], 'module')
            self.assertEqual(module['tag'], 'https://forge.puppet.com/')
            self.assertEqual(len(module['data']['releases']), expc[3])

        # Check requests
        expected = [
            {
             'limit' : ['2'],
             'sort_by' : ['latest_release']
            },
            {
             'limit' : ['2'],
             'module' : ['norisnetwork-ceph'],
             'show_deleted' : ['true'],
             'sort_by' : ['release_date']
            },
            {
             'limit' : ['2'],
             'module' : ['sshuyskiy-nomad'],
             'show_deleted' : ['true'],
             'sort_by' : ['release_date']
            },
            {
             'limit' : ['2'],
             'offset' : ['2'],
             'sort_by' : ['latest_release']
            },
            {
             'limit' : ['2'],
             'module' : ['sshuyskiy-consul'],
             'show_deleted' : ['true'],
             'sort_by' : ['release_date']
            }
        ]

        self.assertEqual(len(http_requests), len(expected))

        for i in range(len(expected)):
            self.assertDictEqual(http_requests[i].querystring, expected[i])

    @httpretty.activate
    def test_fetch_from_date(self):
        """Test whether if fetches a set of modules from the given date"""

        http_requests = setup_http_server()

        from_date = datetime.datetime(2017, 1, 20, 8, 0, 0)

        forge = PuppetForge(max_items=2)
        modules = [module for module in forge.fetch(from_date=from_date)]

        expected = [('ceph', 'a7709201e03bfec46e34e4d0065bb8bdc3f4e5b9', 1484906394.0, 2)]

        self.assertEqual(len(modules), len(expected))

        for x in range(len(modules)):
            module = modules[x]
            expc = expected[x]
            self.assertEqual(module['data']['name'], expc[0])
            self.assertEqual(module['uuid'], expc[1])
            self.assertEqual(module['origin'], 'https://forge.puppet.com/')
            self.assertEqual(module['updated_on'], expc[2])
            self.assertEqual(module['category'], 'module')
            self.assertEqual(module['tag'], 'https://forge.puppet.com/')
            self.assertEqual(len(module['data']['releases']), expc[3])

        # Check requests
        expected = [
            {
             'limit' : ['2'],
             'sort_by' : ['latest_release']
            },
            {
             'limit' : ['2'],
             'module' : ['norisnetwork-ceph'],
             'show_deleted' : ['true'],
             'sort_by' : ['release_date']
            }
        ]

        self.assertEqual(len(http_requests), len(expected))

        for i in range(len(expected)):
            self.assertDictEqual(http_requests[i].querystring, expected[i])

    @httpretty.activate
    def test_fetch_empty(self):
        """Test if nothing is returned when there are no modules"""

        http_requests = setup_http_server()

        from_date = datetime.datetime(2017, 1, 21)

        forge = PuppetForge(max_items=2)
        modules = [module for module in forge.fetch(from_date=from_date)]

        self.assertEqual(len(modules), 0)

        # Check requests
        expected = [
            {
             'limit' : ['2'],
             'sort_by' : ['latest_release']
            }
        ]

        self.assertEqual(len(http_requests), len(expected))

        for i in range(len(expected)):
            self.assertDictEqual(http_requests[i].querystring, expected[i])

    def test_parse_json(self):
        """Test if it parses a JSON stream"""

        raw_json = read_file('data/puppet_forge/puppet_forge_modules.json')

        items = PuppetForge.parse_json(raw_json)
        results = [item for item in items]

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['name'], 'ceph')
        self.assertEqual(results[1]['name'], 'nomad')

        # Parse a file without results
        raw_json = read_file('data/puppet_forge/puppet_forge_empty.json')

        items = PuppetForge.parse_json(raw_json)
        results = [item for item in items]

        self.assertEqual(len(results), 0)


class TestPuppetForgeClient(unittest.TestCase):
    """PuppetForgeClient REST API unit tests.

    These tests not check the body of the response, only if the call
    was well formed and if a response was obtained. Due to this, take
    into account that the body returned on each request might not
    match with the parameters from the request.
    """
    def test_init(self):
        """Test initialization"""

        client = PuppetForgeClient(PUPPET_FORGE_URL, max_items=2)
        self.assertEqual(client.base_url, PUPPET_FORGE_URL)
        self.assertEqual(client.max_items, 2)

    @httpretty.activate
    def test_modules(self):
        """Test modules API call"""

        http_requests = setup_http_server()

        client = PuppetForgeClient(PUPPET_FORGE_URL, max_items=2)

        # Call API
        modules = client.modules()
        result = [module for module in modules]

        self.assertEqual(len(result), 2)

        expected = [
            {
             'limit' : ['2'],
             'sort_by' : ['latest_release']
            },
            {
             'limit' : ['2'],
             'offset' : ['2'],
             'sort_by' : ['latest_release']
            },
        ]

        self.assertEqual(len(http_requests), 2)

        for x in range(0, len(http_requests)):
            req = http_requests[x]
            self.assertEqual(req.method, 'GET')
            self.assertRegex(req.path, '/v3/modules')
            self.assertDictEqual(req.querystring, expected[x])

    @httpretty.activate
    def test_releases(self):
        """Test releases API call"""

        http_requests = setup_http_server()

        client = PuppetForgeClient(PUPPET_FORGE_URL, max_items=2)

        # Call API
        releases = client.releases('norisnetwork', 'ceph')
        result = [release for release in releases]

        self.assertEqual(len(result), 1)

        expected = [
            {
             'limit' : ['2'],
             'module' : ['norisnetwork-ceph'],
             'show_deleted' : ['true'],
             'sort_by' : ['release_date']
            }
        ]

        self.assertEqual(len(http_requests), 1)

        for x in range(0, len(http_requests)):
            req = http_requests[x]
            self.assertEqual(req.method, 'GET')
            self.assertRegex(req.path, '/v3/releases')
            self.assertDictEqual(req.querystring, expected[x])


class TestPuppetForgeCommand(unittest.TestCase):
    """Tests for PuppetForgeCommand class"""

    def test_backend_class(self):
        """Test if the backend class is PuppetForge"""

        self.assertIs(PuppetForgeCommand.BACKEND, PuppetForge)

    def test_setup_cmd_parser(self):
        """Test if it parser object is correctly initialized"""

        parser = PuppetForgeCommand.setup_cmd_parser()
        self.assertIsInstance(parser, BackendCommandArgumentParser)

        args = ['--max-items', '5',
                '--tag', 'test',
                '--from-date', '2016-01-01']

        expected_ts = datetime.datetime(2016, 1, 1, 0, 0, 0,
                                        tzinfo=dateutil.tz.tzutc())

        parsed_args = parser.parse(*args)
        self.assertEqual(parsed_args.max_items, 5)
        self.assertEqual(parsed_args.tag, 'test')
        self.assertEqual(parsed_args.from_date, expected_ts)


if __name__ == "__main__":
    unittest.main(warnings='ignore')
