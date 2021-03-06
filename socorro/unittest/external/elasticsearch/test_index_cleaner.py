# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import mock
import pyelasticsearch

from nose.plugins.attrib import attr
from nose.tools import assert_raises

from configman import ConfigurationManager, environment

from socorro.external.elasticsearch.index_cleaner import IndexCleaner
from socorro.external.elasticsearch.crashstorage import (
    ElasticSearchCrashStorage
)
from socorro.lib.datetimeutil import utc_now
from socorro.unittest.external.elasticsearch.unittestbase import (
    ElasticSearchTestCase,
    maximum_es_version
)

# Remove debugging noise during development
# import logging
# logging.getLogger('pyelasticsearch').setLevel(logging.ERROR)
# logging.getLogger('requests').setLevel(logging.ERROR)


@attr(integration='elasticsearch')
class IntegrationTestIndexCleaner(ElasticSearchTestCase):

    def __init__(self, *args, **kwargs):
        super(
            IntegrationTestIndexCleaner,
            self
        ).__init__(*args, **kwargs)

        storage_config = self._setup_config()
        with storage_config.context() as config:
            self.storage = ElasticSearchCrashStorage(config)

    def setUp(self):
        self.indices = []

    def tearDown(self):
        # Clean up created indices.
        for index in self.indices:
            try:
                self.storage.es.delete_index(index)
            # "Missing" indices have already been deleted, no need to worry.
            except pyelasticsearch.exceptions.ElasticHttpNotFoundError:
                pass

        super(IntegrationTestIndexCleaner, self).tearDown()

    def _setup_config(self):
        mock_logging = mock.Mock()

        storage_conf = ElasticSearchCrashStorage.get_required_config()
        storage_conf.add_option('logger', default=mock_logging)

        cleaner_conf = IndexCleaner.get_required_config()
        cleaner_conf.add_option('logger', default=mock_logging)

        return ConfigurationManager(
            [storage_conf, cleaner_conf],
            values_source_list=[environment],
            argv_source=[]
        )

    @maximum_es_version('0.90')
    def test_correct_indices_are_deleted(self):
        config_manager = self._setup_config()
        with config_manager.context() as config:
            # clear the indices cache so the index is created on every test
            self.storage.indices_cache = set()

            es = self.storage.es

            # Create old indices to be deleted.
            self.storage.create_index('socorro200142', {})
            self.indices.append('socorro200142')

            self.storage.create_index('socorro200000', {})
            self.indices.append('socorro200000')

            # Create an old aliased index.
            self.storage.create_index('socorro200201_20030101', {})
            self.indices.append('socorro200201_20030101')
            es.update_aliases({
                'actions': [{
                    'add': {
                        'index': 'socorro200201_20030101',
                        'alias': 'socorro200201'
                    }
                }]
            })

            # Create a recent aliased index.
            last_week_index = self.storage.get_index_for_crash(
                utc_now() - datetime.timedelta(weeks=1)
            )
            self.storage.create_index('socorro_some_aliased_index', {})
            self.indices.append('socorro_some_aliased_index')
            es.update_aliases({
                'actions': [{
                    'add': {
                        'index': 'socorro_some_aliased_index',
                        'alias': last_week_index
                    }
                }]
            })

            # Create a recent index that should not be deleted.
            now_index = self.storage.get_index_for_crash(utc_now())
            self.storage.create_index(now_index, {})
            self.indices.append(now_index)

            # These will raise an error if an index was not correctly created.
            es.status('socorro200142')
            es.status('socorro200000')
            es.status('socorro200201')
            es.status(now_index)
            es.status(last_week_index)

            api = IndexCleaner(config)
            api.delete_old_indices()

            # Verify the recent index is still there.
            es.status(now_index)
            es.status(last_week_index)

            # Verify the old indices are gone.
            assert_raises(
                pyelasticsearch.exceptions.ElasticHttpNotFoundError,
                es.status,
                'socorro200142'
            )

            assert_raises(
                pyelasticsearch.exceptions.ElasticHttpNotFoundError,
                es.status,
                'socorro200000'
            )

            assert_raises(
                pyelasticsearch.exceptions.ElasticHttpNotFoundError,
                es.status,
                'socorro200201'
            )

    @maximum_es_version('0.90')
    def test_other_indices_are_not_deleted(self):
        """Verify that non-week-based indices are not removed. For example,
        the socorro_email index should not be deleted by the cron job.
        """
        config_manager = self._setup_config()
        with config_manager.context() as config:
            # clear the indices cache so the index is created on every test
            self.storage.indices_cache = set()

            es = self.storage.es

            # Create the socorro emails index.
            self.storage.create_emails_index()
            self.indices.append('socorro_emails')

            # This will raise an error if the index was not correctly created.
            es.status('socorro_emails')

            api = IndexCleaner(config)
            api.delete_old_indices()

            # Verify the email index is still there. This will raise an error
            # if the index does not exist.
            es.status('socorro_emails')
