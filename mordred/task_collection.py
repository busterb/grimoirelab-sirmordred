#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Bitergia
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
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Authors:
#     Luis Cañas-Díaz <lcanas@bitergia.com>
#     Alvaro del Castillo <acs@bitergia.com>
#

import json
import logging
import os
import sys
import time

import requests

from grimoire_elk.arthur import feed_backend
from mordred.task import Task

logger = logging.getLogger(__name__)


class TaskRawDataCollection(Task):
    """ Basic class shared by all collection tasks """

    def __init__(self, conf, repos=None, backend_name=None):
        super().__init__(conf)
        self.repos = repos
        self.backend_name = backend_name
        # This will be options in next iteration
        self.clean = False

    def run(self):
        cfg = self.conf

        if 'collect' in cfg[self.backend_name] and \
            cfg[self.backend_name]['collect'] == False:
            logging.info('%s collect disabled', self.backend_name)
            return

        t2 = time.time()
        logger.info('[%s] raw data collection starts', self.backend_name)
        clean = False

        fetch_cache = False
        if 'fetch-cache' in self.conf[self.backend_name] and \
            self.conf[self.backend_name]['fetch-cache']:
            fetch_cache = True

        for repo in self.repos:
            p2o_args = self._compose_p2o_params(self.backend_name, repo)
            filter_raw = p2o_args['filter-raw'] if 'filter-raw' in p2o_args else None
            if filter_raw:
                # If filter-raw exists the goal is to enrich already collected
                # data, so don't collect anything
                logging.warning("Not collecting filter raw repository: %s", repo)
                continue
            url = p2o_args['url']
            backend_args = self._compose_perceval_params(self.backend_name, repo)
            logger.debug(backend_args)
            logger.debug('[%s] collection starts for %s', self.backend_name, repo)
            es_col_url = self._get_collection_url()
            ds = self.backend_name
            feed_backend(es_col_url, clean, fetch_cache, ds, backend_args,
                         cfg[ds]['raw_index'], cfg[ds]['enriched_index'], url)
        t3 = time.time()
        spent_time = time.strftime("%H:%M:%S", time.gmtime(t3-t2))
        logger.info('[%s] Data collection finished in %s',
                    self.backend_name, spent_time)

class TaskRawDataArthurCollection(Task):
    """ Basic class to control arthur for data collection """

    ARTHUR_URL = 'http://127.0.0.1:8080'
    ARTHUR_TASK_DELAY = 60  # sec, it should be configured per kind of backend
    REPOSITORY_DIR = "/tmp"

    def __init__(self, conf, repos=None, backend_name=None):
        super().__init__(conf)
        self.repos = repos
        self.backend_name = backend_name

    def __create_arthur_json(self, repo, backend_args):
        """ Create the JSON for configuring arthur to collect data

        https://github.com/grimoirelab/arthur#adding-tasks
        Sample for git:

        {
        "tasks": [
            {
                "task_id": "arthur.git",
                "backend": "git",
                "backend_args": {
                    "gitpath": "/tmp/arthur_git/",
                    "uri": "https://github.com/grimoirelab/arthur.git"
                },
                "cache": {
                    "cache": true,
                    "fetch_from_cache": false
                },
                "scheduler": {
                    "delay": 10
                }
            }
        ]
        }
        """

        ajson = {"tasks":[{}]}
        # This is the perceval tag
        ajson["tasks"][0]['task_id'] = repo + "_" + self.backend_name
        ajson["tasks"][0]['backend'] = self.backend_name
        backend_args = self._compose_arthur_params(self.backend_name, repo)
        if self.backend_name == 'git':
            backend_args['gitpath'] = os.path.join(self.REPOSITORY_DIR, repo)
        backend_args['tag'] = ajson["tasks"][0]['task_id']
        ajson["tasks"][0]['backend_args'] = backend_args
        ajson["tasks"][0]['cache'] = {"cache": True, "fetch_from_cache": False}
        ajson["tasks"][0]['scheduler'] = {"delay": self.ARTHUR_TASK_DELAY}

        return(ajson)

    def run(self):
        cfg = self.conf

        if 'collect' in cfg[self.backend_name] and \
            cfg[self.backend_name]['collect'] == False:
            logging.info('%s collect disabled', self.backend_name)
            return

        t2 = time.time()
        logger.info('Programming arthur for [%s] raw data collection', self.backend_name)
        clean = False

        fetch_cache = False
        if 'fetch-cache' in self.conf[self.backend_name] and \
            self.conf[self.backend_name]['fetch-cache']:
            fetch_cache = True

        for repo in self.repos:
            p2o_args = self._compose_p2o_params(self.backend_name, repo)
            filter_raw = p2o_args['filter-raw'] if 'filter-raw' in p2o_args else None
            if filter_raw:
                # If filter-raw exists the goal is to enrich already collected
                # data, so don't collect anything
                logging.warning("Not collecting filter raw repository: %s", repo)
                continue
            url = p2o_args['url']
            backend_args = self._compose_perceval_params(self.backend_name, repo)
            logger.debug(backend_args)
            arthur_repo_json = self.__create_arthur_json(repo, backend_args)
            logger.debug('JSON config for arthur %s', json.dumps(arthur_repo_json))

            # First check is the task already exists
            try:
                r = requests.post(self.ARTHUR_URL+"/tasks")
            except requests.exceptions.ConnectionError as ex:
                logging.error("Can not connect to %s", self.ARTHUR_URL)
                sys.exit(1)

            task_ids = [task['task_id'] for task in r.json()['tasks']]
            new_task_ids = [task['task_id'] for task in arthur_repo_json['tasks']]
            # TODO: if a tasks already exists maybe we should delete and readd it
            already_tasks = list(set(task_ids).intersection(set(new_task_ids)))
            if len(already_tasks) > 0:
                logger.warning("Tasks not added to arthur because there are already existing tasks %s", already_tasks)
            else:
                r = requests.post(self.ARTHUR_URL+"/add", json=arthur_repo_json)
                r.raise_for_status()
                logger.info('[%s] collection configured in arthur for %s', self.backend_name, repo)
